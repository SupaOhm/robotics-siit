"""Pick an OpenCV camera index by name, so the webcam is chosen by what it is.

macOS only. OpenCV's AVFoundation backend numbers cameras by sorting their
unique IDs, so the order shifts when an iPhone (Continuity Camera) or USB
camera comes and goes, and index 0 is often the phone. ``system_profiler``
gives each camera's name and unique ID, which is enough to rebuild OpenCV's
numbering. Elsewhere, and when no camera matches, the plain index is used.
"""

import json
import subprocess
import sys
from typing import Callable, List, Optional, Tuple

Camera = Tuple[str, str, str]  # (name, model id, unique id)


def parse_cameras(profiler_json: str) -> List[Camera]:
    """Cameras from ``system_profiler -json SPCameraDataType``, in OpenCV index order."""
    items = json.loads(profiler_json).get("SPCameraDataType", [])
    cams = [(c.get("_name", ""), c.get("spcamera_model-id", ""),
             c.get("spcamera_unique-id", "")) for c in items]
    return sorted(cams, key=lambda c: c[2])


def list_cameras() -> List[Camera]:
    out = subprocess.run(["system_profiler", "-json", "SPCameraDataType"],
                         capture_output=True, text=True, timeout=10, check=True)
    return parse_cameras(out.stdout)


def find_index(cameras: List[Camera], name: str) -> Optional[int]:
    """Index of the first camera whose name or model id contains ``name`` (any case)."""
    want = name.lower()
    for i, (cam_name, model, _uid) in enumerate(cameras):
        if want in cam_name.lower() or want in model.lower():
            return i
    return None


def resolve_camera(name: str, fallback: int, log: Callable[[str], None] = print,
                   lister: Callable[[], List[Camera]] = list_cameras,
                   platform: str = sys.platform) -> int:
    """OpenCV index for the camera called ``name``, else ``fallback``."""
    if not name or platform != "darwin":
        return fallback
    try:
        cameras = lister()
    except Exception as e:
        log("cannot list cameras (%r), using camera_index %d" % (e, fallback))
        return fallback
    index = find_index(cameras, name)
    if index is None:
        log("no camera matches %r (found: %s), using camera_index %d"
            % (name, ", ".join(c[0] for c in cameras) or "none", fallback))
        return fallback
    return index
