import json

from gesture_control.camera_select import find_index, parse_cameras, resolve_camera

# system_profiler -json SPCameraDataType on a MacBook with an iPhone nearby.
PROFILER = json.dumps({"SPCameraDataType": [
    {"_name": "FaceTime HD Camera", "spcamera_model-id": "FaceTime HD Camera",
     "spcamera_unique-id": "EAB7A68F-EC2B-4487-AADF-D8A91C1CB782"},
    {"_name": "Pu Camera", "spcamera_model-id": "iPhone18,4",
     "spcamera_unique-id": "6B622FD3-8530-44AB-9BC9-050F00000001"},
]})


def cams():
    return parse_cameras(PROFILER)


def test_parse_sorts_by_unique_id_like_opencv():
    # OpenCV opened the iPhone at index 0 and the FaceTime camera at 1.
    assert [c[0] for c in cams()] == ["Pu Camera", "FaceTime HD Camera"]


def test_parse_empty():
    assert parse_cameras("{}") == []


def test_find_by_name_or_model_any_case():
    assert find_index(cams(), "facetime") == 1
    assert find_index(cams(), "iPhone") == 0
    assert find_index(cams(), "logitech") is None


def test_resolve_picks_named_camera_on_macos():
    assert resolve_camera("FaceTime", 0, lister=cams, platform="darwin") == 1


def test_resolve_follows_index_shift_when_phone_leaves():
    only_mac = lambda: [c for c in cams() if c[0].startswith("FaceTime")]
    assert resolve_camera("FaceTime", 5, lister=only_mac, platform="darwin") == 0


def test_resolve_falls_back_when_no_match():
    logs = []
    assert resolve_camera("Logitech", 3, log=logs.append, lister=cams,
                          platform="darwin") == 3
    assert "FaceTime HD Camera" in logs[0]


def test_resolve_falls_back_when_listing_fails():
    def boom():
        raise OSError("no system_profiler")
    logs = []
    assert resolve_camera("FaceTime", 2, log=logs.append, lister=boom,
                          platform="darwin") == 2
    assert logs


def test_resolve_ignores_name_off_macos_and_when_empty():
    def never():
        raise AssertionError("must not list cameras")
    assert resolve_camera("FaceTime", 4, lister=never, platform="linux") == 4
    assert resolve_camera("", 4, lister=never, platform="darwin") == 4
