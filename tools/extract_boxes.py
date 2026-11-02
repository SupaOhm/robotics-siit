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
from object_detection.recorded import (  # noqa: E402
    answer, needed_share, read_settings)
from object_detection.yolo_backend import YoloDetector  # noqa: E402

BOX_CONFIDENCE = 0.10      # keep weak boxes too, so thresholds can go lower
FRAME_STEP = 0.5           # seconds between sampled frames (2 per second)
RESIZED_SIZE = 1280        # longest side of the photos YOLO runs on
PHOTO_TYPES = (".heic", ".jpg", ".jpeg", ".png")
IMAGE_TYPES = ("sensor_msgs/msg/Image", "sensor_msgs/msg/CompressedImage")


def expected_from_name(name):
    """"chair_close" -> "chair"; "obstacle_desk" -> "unknown"; IMG_5017 -> None."""
    match = re.match(r"([a-z]+)_", name)
    if not match:
        return None
    return "unknown" if match[1] == "obstacle" else match[1]


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
        try:
            resized = resized_photo(original, session / "resized")
            image = cv2.imread(str(resized))
            if image is None:
                raise ValueError("can't read %s" % resized)
            found = boxes.run(image, session / "annotated" / resized.name)
        except Exception as error:  # skip one bad photo, keep the rest
            print("%s: skipped, %s" % (original.stem, error))
            continue
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
    """Time of the last change from moving to stopped.

    None if the robot never moved, so any frame shows the stop position.
    """
    stopped_at, moving = None, False
    for t, msg in commands:
        now_moving = any(abs(v) > 1e-3 for v in (
            msg.linear.x, msg.linear.y, msg.angular.z))
        if moving and not now_moving:
            stopped_at = t
        moving = now_moving
    if moving:
        raise ValueError("still moving when /cmd_vel ends: stop with the "
                         "teleop stop key, not by letting go of the keys")
    return stopped_at


def recording_entries(session, boxes):
    from rosbags.typesys import Stores, get_typestore
    typestore = get_typestore(Stores.ROS2_HUMBLE)

    for bag in sorted(p for p in (session / "recordings").iterdir()
                      if p.is_dir()):
        try:  # skip one bad recording, keep the rest
            frames = read_recording(bag, typestore, session, boxes)
        except Exception as error:
            print("%s: skipped, %s" % (bag.name, error))
            continue
        yield bag.name, {"frames": frames}


def read_recording(bag, typestore, session, boxes):
    """Boxes for frames from the stop, one every FRAME_STEP seconds."""
    from rosbags.highlevel import AnyReader
    with AnyReader([bag], default_typestore=typestore) as reader:
        cameras = [c for c in reader.connections if c.msgtype in IMAGE_TYPES]
        topics = sorted({c.topic for c in cameras})
        if len(topics) != 1:
            raise ValueError("expected one camera topic, found %s" % topics)
        drive = [c for c in reader.connections if c.topic == "/cmd_vel"]
        # An empty connection list would read every topic, not none.
        commands = [(t, reader.deserialize(raw, c.msgtype))
                    for c, t, raw in reader.messages(connections=drive)
                    ] if drive else []
        start = stop_time(commands)
        if start is None:
            print("%s: robot never moved, sampled from the first frame"
                  % bag.name)

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
    if not frames:
        raise ValueError("no camera frames after the stop")
    return frames


# ---- main ---------------------------------------------------------------

def merge(json_path, entries, key, found):
    """Update boxes of known entries, add new ones that have an expected answer."""
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
            verdict = "pass" if share >= needed_share(e["expect"]) else "FAIL"
            print("%-16s expect %-8s right %2d/%-2d (%3.0f%%)  %s%s"
                  % (e[key], e["expect"], right, len(e["frames"]),
                     share * 100, verdict, miss))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("session", type=Path)
    parser.add_argument("json", type=Path)
    parser.add_argument("--model", default="~/models/yolo11n_ncnn_model")
    args = parser.parse_args()

    if (args.session / "originals").is_dir():
        key, read = "photo", photo_entries
    elif (args.session / "recordings").is_dir():
        key, read = "bag", recording_entries
    else:
        sys.exit("%s has no originals/ or recordings/ folder" % args.session)
    # Check the JSON before YOLO runs, so a wrong file loses no work.
    entries = json.loads(args.json.read_text()) if args.json.exists() else []
    if any(key not in e for e in entries):
        sys.exit("%s isn't a %s file: photos go in floor_photos.json, "
                 "recordings in robot_frames.json" % (args.json, key))

    settings = read_settings(PACKAGE / "config" / "detector.yaml")
    boxes = Boxes(os.path.expanduser(args.model), settings["image_size"])
    found = list(read(args.session, boxes))
    report(merge(args.json, entries, key, found), key, settings)


if __name__ == "__main__":
    main()
