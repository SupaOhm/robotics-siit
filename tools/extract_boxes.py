"""Run the robot's detector on photos or robot recordings, on a laptop.

YOLO runs once here and the boxes go to a JSON file in
src/object_detection/test/. The tests then check them against the thresholds
in config/detector.yaml, so tuning a threshold needs no robot and no rerun.

Usage:
    python tools/extract_boxes.py <session folder> <json file> [--model PATH]

A session folder can have any name and holds one of:
    originals/     photos, any format (HEIC, JPG...)
    recordings/    one ros2 bag folder per recording
Keep sessions in local/photos/ and local/bags/, which git ignores.

Name each photo or recording <expected>_<note>, e.g. chair_close,
person_side, obstacle_desk. The expected answer is the part before the first
"_": a spoken label, "person", or "obstacle" for things the robot can't name.
Entries already in the JSON keep their "expect" and "known_miss"; only their
boxes are replaced. Files whose name has no expected answer, such as
IMG_5017, are skipped unless the JSON already has them.

Recordings: the robot asks the detector the moment it stops, so frames are
taken from the last time /cmd_vel goes to zero, then one every 0.5 s.

Needs: pip install "ultralytics" ncnn rosbags pillow pillow-heif
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "object_detection"
sys.path.insert(0, str(PACKAGE))
from object_detection.classifier import (  # noqa: E402
    Detection, classify, parse_name_table)
from object_detection.yolo_backend import YoloDetector  # noqa: E402

BOX_CONFIDENCE = 0.10      # keep weak boxes too, so thresholds can go lower
FRAME_STEP = 0.5           # seconds between sampled frames (2 per second)
RESIZED_SIZE = 1280        # longest side of the photos YOLO runs on
PHOTO_TYPES = (".heic", ".jpg", ".jpeg", ".png")
IMAGE_TYPES = ("sensor_msgs/msg/Image", "sensor_msgs/msg/CompressedImage")


def read_settings():
    """The robot's own thresholds and name table, from config/detector.yaml."""
    text = (PACKAGE / "config" / "detector.yaml").read_text()
    return {
        "image_size": int(re.search(r"image_size:\s*(\d+)", text)[1]),
        "person": float(re.search(r"person_threshold:\s*([\d.]+)", text)[1]),
        "object": float(re.search(r"object_threshold:\s*([\d.]+)", text)[1]),
        "names": parse_name_table(
            re.findall(r'^\s*-\s*"([^"]+=[^"]+)"', text, re.M)),
    }


def expected_from_name(name):
    """"chair_close" -> "chair"; "obstacle_desk" -> "unknown"; IMG_5017 -> None."""
    match = re.match(r"([a-z]+)_", name)
    if not match:
        return None
    return "unknown" if match[1] == "obstacle" else match[1]


def answer(boxes, settings):
    """What the robot would say for one frame's boxes."""
    detections = [Detection(n, c, a) for n, c, a in boxes]
    result = classify("x", detections, settings["names"],
                      settings["person"], settings["object"])
    return result["label"] or result["kind"]


class Boxes:
    """The robot's YoloDetector, plus a copy of the frame with boxes drawn."""

    def __init__(self, model_path, image_size):
        self.detector = YoloDetector(model_path, image_size, BOX_CONFIDENCE)
        self.image_size = image_size

    def run(self, bgr, annotated_path):
        boxes = [[d.name, round(d.confidence, 2), int(d.area)]
                 for d in self.detector.detect(bgr)]
        # YoloDetector returns no coordinates, so ask the model for the plot.
        plot = self.detector._model.predict(
            bgr, imgsz=self.image_size, conf=BOX_CONFIDENCE,
            verbose=False)[0].plot()
        annotated_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(annotated_path), plot)
        return boxes


# ---- photos -------------------------------------------------------------

def resized_photo(original, resized_dir):
    """The 1280 px JPG of one photo, made from the original if missing."""
    path = resized_dir / (original.stem + ".jpg")
    if not path.exists():
        from PIL import Image, ImageOps
        if original.suffix.lower() == ".heic":
            import pillow_heif
            pillow_heif.register_heif_opener()
        image = ImageOps.exif_transpose(Image.open(original)).convert("RGB")
        image.thumbnail((RESIZED_SIZE, RESIZED_SIZE))
        resized_dir.mkdir(exist_ok=True)
        image.save(path, quality=90)
    return path


def photo_entries(session, boxes):
    for original in sorted((session / "originals").iterdir()):
        if original.suffix.lower() not in PHOTO_TYPES:
            continue
        resized = resized_photo(original, session / "resized")
        found = boxes.run(cv2.imread(str(resized)),
                          session / "annotated" / resized.name)
        yield original.stem, {"boxes": found}


# ---- recordings ---------------------------------------------------------

def to_bgr(msg, msgtype):
    """Same conversion as cv_bridge's imgmsg_to_cv2(desired_encoding="bgr8")."""
    if msgtype.endswith("CompressedImage"):
        return cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
    rows = np.frombuffer(msg.data, np.uint8).reshape(msg.height, msg.step)
    if msg.encoding in ("bgr8", "rgb8"):
        image = rows[:, :msg.width * 3].reshape(msg.height, msg.width, 3)
        return image if msg.encoding == "bgr8" else image[:, :, ::-1].copy()
    if msg.encoding == "mono8":
        return cv2.cvtColor(rows[:, :msg.width], cv2.COLOR_GRAY2BGR)
    pairs = rows[:, :msg.width * 2].reshape(msg.height, msg.width, 2)
    if msg.encoding in ("yuv422_yuy2", "yuyv"):
        return cv2.cvtColor(pairs, cv2.COLOR_YUV2BGR_YUYV)
    if msg.encoding in ("yuv422", "uyvy"):
        return cv2.cvtColor(pairs, cv2.COLOR_YUV2BGR_UYVY)
    raise ValueError("unsupported image encoding %r" % msg.encoding)


def stop_time(commands):
    """Time of the last change from moving to stopped, or None."""
    stopped_at, moving = None, False
    for t, msg in commands:
        now_moving = any(abs(v) > 1e-3 for v in (
            msg.linear.x, msg.linear.y, msg.angular.z))
        if moving and not now_moving:
            stopped_at = t
        moving = now_moving
    return None if moving else stopped_at


def recording_entries(session, boxes):
    from rosbags.highlevel import AnyReader
    from rosbags.typesys import Stores, get_typestore
    typestore = get_typestore(Stores.ROS2_HUMBLE)

    for bag in sorted(p for p in (session / "recordings").iterdir()
                      if p.is_dir()):
        with AnyReader([bag], default_typestore=typestore) as reader:
            cameras = [c for c in reader.connections
                       if c.msgtype in IMAGE_TYPES]
            if len({c.topic for c in cameras}) != 1:
                print("%s: skipped, expected one camera topic, found %s"
                      % (bag.name, sorted({c.topic for c in cameras})))
                continue
            drive = [c for c in reader.connections if c.topic == "/cmd_vel"]
            # An empty connection list would read every topic, not none.
            commands = [(t, reader.deserialize(raw, c.msgtype))
                        for c, t, raw in reader.messages(connections=drive)
                        ] if drive else []
            start = stop_time(commands)
            note = None
            if start is None:
                note = "no stop in /cmd_vel, sampled from the first frame"

            frames, next_t = [], start or 0
            for c, t, raw in reader.messages(connections=cameras):
                if t < next_t:
                    continue
                if start is None:
                    start = t
                name = "%02d_%+.1fs.jpg" % (len(frames), (t - start) / 1e9)
                frames.append(boxes.run(
                    to_bgr(reader.deserialize(raw, c.msgtype), c.msgtype),
                    session / "annotated" / bag.name / name))
                next_t = t + int(FRAME_STEP * 1e9)
        if note:
            print("%s: %s" % (bag.name, note))
        if not frames:
            print("%s: skipped, no camera frames after the stop" % bag.name)
            continue
        yield bag.name, {"frames": frames}


# ---- main ---------------------------------------------------------------

def merge(json_path, key, found):
    """Update boxes of known entries, add new ones that have an expected answer."""
    entries = json.loads(json_path.read_text()) if json_path.exists() else []
    by_name = {e[key]: e for e in entries}
    for name, data in found:
        if name in by_name:
            by_name[name].update(data)
            continue
        expect = expected_from_name(name)
        if expect is None:
            print("%s: skipped, rename it <expected>_<note>" % name)
            continue
        entry = {key: name, "expect": expect}
        entry.update(data)
        entries.append(entry)
        by_name[name] = entry
    json_path.write_text(
        "[\n" + ",\n".join(json.dumps(e) for e in entries) + "\n]\n")
    return [by_name[name] for name, _ in found if name in by_name]


def report(entries, key, settings):
    for e in entries:
        miss = "  (known miss)" if "known_miss" in e else ""
        if key == "photo":
            said = answer(e["boxes"], settings)
            verdict = "ok" if said == e["expect"] else "MISS"
            print("%-16s expect %-8s said %-8s %s%s"
                  % (e[key], e["expect"], said, verdict, miss))
        else:
            right = sum(answer(f, settings) == e["expect"] for f in e["frames"])
            share = right / len(e["frames"])
            needed = 1.0 if e["expect"] == "person" else 0.8
            verdict = "pass" if share >= needed else "FAIL"
            print("%-16s expect %-8s right %2d/%-2d (%3.0f%%)  %s%s"
                  % (e[key], e["expect"], right, len(e["frames"]),
                     share * 100, verdict, miss))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("session", type=Path)
    parser.add_argument("json", type=Path)
    parser.add_argument("--model", default="~/models/yolo11n_ncnn_model")
    args = parser.parse_args()

    settings = read_settings()
    boxes = Boxes(os.path.expanduser(args.model), settings["image_size"])
    if (args.session / "originals").is_dir():
        key, found = "photo", photo_entries(args.session, boxes)
    elif (args.session / "recordings").is_dir():
        key, found = "bag", recording_entries(args.session, boxes)
    else:
        sys.exit("%s has no originals/ or recordings/ folder" % args.session)
    report(merge(args.json, key, list(found)), key, settings)


if __name__ == "__main__":
    main()
