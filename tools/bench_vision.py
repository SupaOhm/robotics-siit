#!/usr/bin/env python3
"""
bench_vision.py - Lane 5, Phase 1: FPS benchmark for MediaPipe Hands + YOLO.

Runs on the ROSMASTER M1 (Raspberry Pi 5, inside or outside Docker) or on a
laptop (Windows/Linux/VM). No ROS needed. No window is opened, so it works over SSH.

It measures these configurations at each resolution:
  camera_only       camera read only (the ceiling: the camera's own FPS)
  mediapipe_only    MediaPipe Hands on every frame
  yolo_only         YOLO on every frame (also gives the one-shot "classify" latency)
  both_every_frame  MediaPipe + YOLO on every frame
  both_alternate    MediaPipe every frame, YOLO every N frames (--every)

Usage examples:
  # On the robot, with the detector's settings (D20: NCNN, 320 px). Answers the
  # "time limit per YOLO frame" question in docs/interfaces.md:
  python3 bench_vision.py --model yolo11n_ncnn_model --sizes 320x240 \
      --configs camera_only,yolo_only --seconds 20 --csv robot_ncnn.csv
  python3 bench_vision.py --model yolo11n.pt --sizes 320x240 \
      --configs camera_only,yolo_only --seconds 20 --csv robot_pt.csv

  python3 bench_vision.py                          # camera 0, 15 s per config
  python3 bench_vision.py --source 1               # another camera index
  python3 bench_vision.py --source test.mp4        # a video file (loops)
  python3 bench_vision.py --model yolo11n_ncnn_model   # NCNN export (faster on a Pi)
  python3 bench_vision.py --seconds 10 --sizes 320x240
  python3 bench_vision.py --fake                   # test this script without camera/models

Hold one hand in front of the camera during the MediaPipe tests: with a hand in
view, MediaPipe tracks it, which is the realistic case for gesture control.

YOLO times wrap model.predict only (letterbox, inference, NMS), frame after frame
once warmed up. They leave out the wait for a camera frame, cv_bridge and DDS.
The MediaPipe settings here are not gesture_node's, so MediaPipe times are a
rough guide; time gesture_node itself for the real number.

Results are printed as a table and saved to bench_results.csv, one row as each
config finishes.
"""

import argparse
import csv
import os
import platform
import sys
import time

CONFIGS = ("camera_only", "mediapipe_only", "yolo_only", "both_every_frame", "both_alternate")
TARGET_FPS_DEFAULT = 15.0
# Proposed time limit for one YOLO frame on the robot. CLASSIFY waits 3 s for a
# reply and retries once (docs/interfaces.md). The budget is: wait for the next
# camera frame + YOLO + cv_bridge and DDS <= 3 s. See docs/benchmark-yolo.md.
YOLO_LIMIT_MS_DEFAULT = 1000.0
# detector_node keeps boxes above min(person_threshold, object_threshold) = 0.25
# (src/object_detection/config/detector.yaml), so NMS sees the same boxes.
CONF_DEFAULT = 0.25
# detector.yaml image_size and the NCNN export (D20).
IMGSZ_DEFAULT = 320
# A recommended setting must beat the target FPS by this factor, so a busy CPU
# (driver, LiDAR, other nodes) doesn't push it under the target.
FPS_MARGIN = 1.10


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def cpu_temp_c():
    """Raspberry Pi / Linux CPU temperature in Celsius, or None."""
    path = "/sys/class/thermal/thermal_zone0/temp"
    try:
        with open(path) as f:
            return int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def parse_sizes(text):
    sizes = []
    for part in text.split(","):
        w, h = part.lower().strip().split("x")
        sizes.append((int(w), int(h)))
    return sizes


# ----------------------------------------------------------------------------
# Frame sources
# ----------------------------------------------------------------------------
class FakeSource:
    """Black frames, for testing the script without a camera."""

    def __init__(self, width, height):
        import numpy as np
        self.frame = np.zeros((height, width, 3), dtype=np.uint8)

    def read(self):
        time.sleep(0.002)
        return self.frame

    def release(self):
        pass


class CvSource:
    """A camera index or a video file, resized to the requested size.

    A camera is read in a background thread, like a ROS camera node: read() returns
    the newest frame and waits only until a frame newer than the last one arrives.
    So slow processing skips stale frames instead of waiting a full extra frame.
    """

    def __init__(self, source, width, height, cap=None):
        import cv2
        self.cv2 = cv2
        self.width, self.height = width, height
        self.is_file = not str(source).isdigit()
        self.source = source if self.is_file else int(source)
        self.cap = cap if cap is not None else cv2.VideoCapture(self.source)
        if not self.cap.isOpened():
            raise RuntimeError(
                f"Cannot open source {source!r}. Is another program (camera node, "
                "Yahboom app, joystick container) using the camera? Stop it and retry.")
        self.threaded = not self.is_file
        if self.threaded:
            # Ask for MJPG at 30 FPS: many USB webcams only reach 30 FPS in MJPG.
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            import threading
            self._cond = threading.Condition()
            self._frame, self._seq, self._last_seq = None, 0, 0
            self._error, self._running = None, True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _resize(self, frame):
        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            frame = self.cv2.resize(frame, (self.width, self.height))
        return frame

    def _loop(self):
        while self._running:
            ok, frame = self.cap.read()
            with self._cond:
                if not ok:
                    self._error = "Camera stopped delivering frames."
                    self._cond.notify_all()
                    return
                self._frame = self._resize(frame)
                self._seq += 1
                self._cond.notify_all()

    def read(self):
        if not self.threaded:
            ok, frame = self.cap.read()
            if not ok:                                   # loop the video
                self.cap.set(self.cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self.cap.read()
            if not ok:
                raise RuntimeError("Video file stopped delivering frames.")
            return self._resize(frame)
        with self._cond:
            got = self._cond.wait_for(
                lambda: self._seq != self._last_seq or self._error is not None, timeout=5.0)
            if self._error or not got:
                raise RuntimeError(self._error or "No frame from the camera for 5 s.")
            self._last_seq = self._seq
            return self._frame

    def release(self):
        if self.threaded:
            self._running = False
            self._thread.join(timeout=2.0)
        self.cap.release()


# ----------------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------------
class FakeHands:
    def process(self, frame):
        time.sleep(0.020)


class FakeYolo:
    def __init__(self, imgsz):
        self.imgsz = imgsz

    def predict(self, frame):
        time.sleep(0.080 if self.imgsz >= 640 else 0.030)


HAND_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
                  "hand_landmarker/float16/latest/hand_landmarker.task")


class MediaPipeHands:
    """Hand landmarks with whichever MediaPipe API is installed.

    - Old MediaPipe (0.10.x up to about 0.10.21): mp.solutions.hands
    - New MediaPipe (later 0.10.x and 1.x): Tasks API (HandLandmarker), which needs
      the model file hand_landmarker.task (downloaded automatically if missing).
    """

    def __init__(self, model_path="hand_landmarker.task"):
        try:
            import cv2
            import mediapipe as mp
        except ImportError as e:
            sys.exit(f"MediaPipe/OpenCV not installed ({e}).\n"
                     "Install: pip install mediapipe opencv-python")
        self.cv2 = cv2
        self.mp = mp
        self.version = getattr(mp, "__version__", "?")
        if hasattr(mp, "solutions"):
            self.api = "solutions"
            self.hands = mp.solutions.hands.Hands(
                static_image_mode=False, max_num_hands=1,
                model_complexity=0, min_detection_confidence=0.5,
                min_tracking_confidence=0.5)
        else:
            self.api = "tasks"
            self._ensure_model(model_path)
            vision = mp.tasks.vision
            options = vision.HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=1)
            self.hands = vision.HandLandmarker.create_from_options(options)
            self.last_ts = -1
        print(f"MediaPipe {self.version} ({self.api} API)")

    @staticmethod
    def _ensure_model(path):
        if os.path.exists(path):
            return
        print(f"Downloading {os.path.basename(path)} (about 8 MB) ...", flush=True)
        try:
            import urllib.request
            urllib.request.urlretrieve(HAND_MODEL_URL, path)
        except Exception as e:  # noqa: BLE001 - show any network error plainly
            sys.exit(f"Could not download the hand model ({e}).\n"
                     f"Download it in a browser and put it next to this script:\n  {HAND_MODEL_URL}")

    def process(self, frame):
        rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
        if self.api == "solutions":
            self.hands.process(rgb)
            return
        ts = int(time.monotonic() * 1000)
        if ts <= self.last_ts:              # timestamps must strictly increase
            ts = self.last_ts + 1
        self.last_ts = ts
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        self.hands.detect_for_video(image, ts)

    def close(self):
        try:
            self.hands.close()
        except Exception:  # noqa: BLE001 - closing must never crash the report
            pass


class UltralyticsYolo:
    def __init__(self, model_path, imgsz, conf):
        try:
            from ultralytics import YOLO
        except ImportError as e:
            sys.exit(f"Ultralytics not installed ({e}).\nInstall: pip install ultralytics")
        self.model = YOLO(model_path, task="detect")   # NCNN folders can't guess the task
        self.imgsz = imgsz
        self.conf = conf

    def predict(self, frame):
        self.model.predict(frame, imgsz=self.imgsz, conf=self.conf, verbose=False)


# ----------------------------------------------------------------------------
# Benchmark
# ----------------------------------------------------------------------------
def run_config(name, source, hands, yolo, seconds, every, warmup):
    use_mp = name in ("mediapipe_only", "both_every_frame", "both_alternate")
    use_yolo = name in ("yolo_only", "both_every_frame", "both_alternate")

    # Warm-up (first inferences are slow: model loading, caches)
    t_end = time.perf_counter() + warmup
    while time.perf_counter() < t_end:
        frame = source.read()
        if use_mp:
            hands.process(frame)
        if use_yolo:
            yolo.predict(frame)

    frames, mp_times, yolo_times = 0, [], []
    temp_start = cpu_temp_c()
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        frame = source.read()
        if use_mp:
            t = time.perf_counter()
            hands.process(frame)
            mp_times.append(time.perf_counter() - t)
        run_yolo = use_yolo and (name != "both_alternate" or frames % every == 0)
        if run_yolo:
            t = time.perf_counter()
            yolo.predict(frame)
            yolo_times.append(time.perf_counter() - t)
        frames += 1
    elapsed = time.perf_counter() - t0

    avg_ms = lambda xs: (sum(xs) / len(xs) * 1000.0) if xs else None
    mp_ms, yolo_ms = avg_ms(mp_times), avg_ms(yolo_times)
    yolo_sorted = sorted(yolo_times)
    # Compute-only FPS: what the processing alone allows, if the camera were never the limit
    per_frame_ms = (mp_ms or 0.0) + (yolo_ms or 0.0) * (1.0 / every if name == "both_alternate" else 1.0)
    return {
        "config": name,
        "frames": frames,
        "fps": frames / elapsed if elapsed > 0 else 0.0,
        "compute_fps": (1000.0 / per_frame_ms) if per_frame_ms > 0 else None,
        "mediapipe_ms": mp_ms,
        "mediapipe_p95_ms": percentile_ms(sorted(mp_times), 95),
        "yolo_ms": yolo_ms,
        "yolo_p95_ms": percentile_ms(yolo_sorted, 95),
        "yolo_max_ms": yolo_sorted[-1] * 1000.0 if yolo_sorted else None,
        "temp_start_c": temp_start,
        "temp_end_c": cpu_temp_c(),
    }


def percentile_ms(sorted_seconds, q):
    """q-th percentile (nearest rank) of sorted durations in seconds, in ms; None if empty."""
    if not sorted_seconds:
        return None
    rank = max(1, -(-len(sorted_seconds) * q // 100))   # ceil(n * q / 100)
    return sorted_seconds[int(rank) - 1] * 1000.0


def fmt(v, digits=1):
    return "-" if v is None else f"{v:.{digits}f}"


def main():
    ap = argparse.ArgumentParser(description="MediaPipe + YOLO FPS benchmark (Lane 5).")
    ap.add_argument("--source", default="0", help="camera index or video file (default 0)")
    ap.add_argument("--model", default="yolo11n.pt",
                    help="YOLO model: yolo11n.pt, yolov8n.pt, or an NCNN export folder")
    ap.add_argument("--sizes", default="640x480,320x240", help="resolutions to test")
    ap.add_argument("--seconds", type=float, default=15.0, help="seconds per config")
    ap.add_argument("--warmup", type=float, default=2.0, help="warm-up seconds per config")
    ap.add_argument("--every", type=int, default=3, help="YOLO every N frames in both_alternate")
    ap.add_argument("--target", type=float, default=TARGET_FPS_DEFAULT, help="target FPS")
    ap.add_argument("--yolo-limit-ms", type=float, default=YOLO_LIMIT_MS_DEFAULT,
                    help="time limit for one YOLO frame on the robot (docs/interfaces.md, "
                         "Still open, Lane 5); the slowest frame must stay under it")
    ap.add_argument("--configs", default=",".join(CONFIGS),
                    help="comma-separated, from: " + ", ".join(CONFIGS))
    ap.add_argument("--imgsz", type=int, default=IMGSZ_DEFAULT,
                    help="YOLO input size at every resolution (default 320, as in "
                         "detector.yaml and the NCNN export)")
    ap.add_argument("--conf", type=float, default=CONF_DEFAULT,
                    help="YOLO confidence threshold (default 0.25, as detector_node)")
    ap.add_argument("--hand-model", default="hand_landmarker.task",
                    help="MediaPipe hand model file (new MediaPipe only; downloaded if missing)")
    ap.add_argument("--csv", default="bench_results.csv")
    ap.add_argument("--fake", action="store_true", help="no camera/models; test the script")
    args = ap.parse_args()

    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    unknown = [c for c in configs if c not in CONFIGS]
    if unknown or not configs:
        ap.error(f"unknown config {', '.join(unknown) or '(none given)'}; "
                 f"choose from {', '.join(CONFIGS)}")
    if args.every < 1:
        ap.error("--every must be 1 or more")
    sizes = parse_sizes(args.sizes)
    imgsz = args.imgsz

    print(f"Machine: {platform.node()} | {platform.machine()} | Python {platform.python_version()}")
    print(f"Source: {'FAKE' if args.fake else args.source} | Model: {'FAKE' if args.fake else args.model}")
    print(f"YOLO imgsz {imgsz}, conf {args.conf} | {args.seconds:.0f} s per config, "
          f"YOLO every {args.every} frames in both_alternate\n")

    fields = ["resolution", "config", "fps", "compute_fps", "frames", "mediapipe_ms",
              "mediapipe_p95_ms", "yolo_ms", "yolo_p95_ms", "yolo_max_ms", "yolo_imgsz",
              "yolo_conf", "temp_start_c", "temp_end_c"]
    csv_file = open(args.csv, "w", newline="")
    writer = csv.DictWriter(csv_file, fieldnames=fields)
    writer.writeheader()
    csv_file.flush()

    hands = FakeHands() if args.fake else None
    results = []
    try:
        for (w, h) in sizes:
            source = FakeSource(w, h) if args.fake else CvSource(args.source, w, h)
            if not args.fake:
                if hands is None and any("mediapipe" in c or "both" in c for c in configs):
                    hands = MediaPipeHands(args.hand_model)
            yolo = None
            if any("yolo" in c or "both" in c for c in configs):
                yolo = FakeYolo(imgsz) if args.fake else UltralyticsYolo(args.model, imgsz, args.conf)
            try:
                for name in configs:
                    print(f"  running {name:17s} at {w}x{h} ...", flush=True)
                    r = run_config(name, source, hands, yolo, args.seconds, args.every, args.warmup)
                    r.update({"resolution": f"{w}x{h}",
                              "yolo_imgsz": imgsz if r["yolo_ms"] is not None else None,
                              "yolo_conf": args.conf if r["yolo_ms"] is not None else None})
                    results.append(r)
                    writer.writerow({k: r.get(k) for k in fields})   # saved even if a later config fails
                    csv_file.flush()
            finally:
                source.release()
    finally:
        csv_file.close()
        if hasattr(hands, "close"):
            hands.close()

    # Table
    print("\nFPS = real end-to-end FPS. Compute FPS = processing only (camera not counted).")
    print("YOLO times: mean / 95th percentile / slowest frame.")
    row = "{:<8} {:<17} {:>6} {:>8} {:>6} {:>17} {:>9}"
    print(row.format("res", "config", "FPS", "Compute", "MP ms", "YOLO ms mean/p95/max", "temp C"))
    print("-" * 77)
    for r in results:
        if r["temp_start_c"] is None:
            temp = "-"
        else:
            temp = f"{fmt(r['temp_start_c'], 0)}->{fmt(r['temp_end_c'], 0)}"
        if r["yolo_ms"] is None:
            yolo = "-"
        else:
            yolo = f"{fmt(r['yolo_ms'], 0)}/{fmt(r['yolo_p95_ms'], 0)}/{fmt(r['yolo_max_ms'], 0)}"
        print(row.format(r["resolution"], r["config"], fmt(r["fps"]), fmt(r["compute_fps"]),
                         fmt(r["mediapipe_ms"]), yolo, temp))

    print(f"\nSaved {os.path.abspath(args.csv)}")

    # Recommendation
    preferred = ["both_every_frame", "both_alternate"]
    by_preference = lambda r: (preferred.index(r["config"]), -int(r["resolution"].split("x")[0]))
    together = [r for r in results if r["config"] in preferred]
    with_margin = sorted((r for r in together if r["fps"] >= args.target * FPS_MARGIN),
                         key=by_preference)
    just_met = sorted((r for r in together if r["fps"] >= args.target), key=by_preference)
    print(f"\nTarget: {args.target:.0f} FPS with MediaPipe + YOLO together")
    if not together:
        print("  (MediaPipe + YOLO together was not tested in this run)")
    elif with_margin:
        # Prefer every-frame over alternate, then the higher resolution
        best = with_margin[0]
        print(f"  MET: use {best['config']} at {best['resolution']} ({best['fps']:.1f} FPS, "
              f"at least {FPS_MARGIN - 1:.0%} above the target)")
    elif just_met:
        best = just_met[0]
        print(f"  MET WITH NO MARGIN: {best['config']} at {best['resolution']} gives only "
              f"{best['fps']:.1f} FPS. A busy robot may drop under {args.target:.0f}.")
        print("  Prefer a lower resolution or a larger --every.")
    else:
        print("  NOT MET with MediaPipe + YOLO together. Options, best first:")
        print("   1. Run YOLO only on demand (when the robot has stopped), not every frame")
        print("   2. Export YOLO to NCNN:  yolo export model=yolo11n.pt format=ncnn")
        print("   3. Lower the resolution or raise --every")
        print("   4. Run MediaPipe gestures on the laptop instead of the robot")
    yolo_once = [r for r in results if r["config"] == "yolo_only" and r["yolo_ms"]]
    if yolo_once:
        print(f"\nYOLO time limit: {args.yolo_limit_ms:.0f} ms per frame (slowest frame must fit)")
    for r in yolo_once:
        verdict = "PASS" if r["yolo_max_ms"] <= args.yolo_limit_ms else "FAIL"
        print(f"  {verdict} at {r['resolution']}: mean {r['yolo_ms']:.0f} ms, "
              f"p95 {r['yolo_p95_ms']:.0f} ms, slowest {r['yolo_max_ms']:.0f} ms")
        if verdict == "FAIL":
            print("        Over the limit: move the detector to the laptop (D18), "
                  "or use NCNN / a smaller image size.")
    cams = [r for r in results if r["config"] == "camera_only"]
    slow_cams = [r for r in cams if r["fps"] < args.target]
    if slow_cams and not args.fake:
        worst = min(slow_cams, key=lambda r: r["fps"])
        print(f"\n  NOTE: the camera itself only delivers {worst['fps']:.1f} FPS at "
              f"{worst['resolution']}, so no processing setting can beat that.")
        print("        Usual cause: a dim room (the camera slows down to expose longer).")
        print("        Re-test in bright light, and judge the processing by 'Compute FPS'.")


if __name__ == "__main__":
    main()
