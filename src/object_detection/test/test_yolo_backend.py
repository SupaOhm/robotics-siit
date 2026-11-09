import pytest

from object_detection.yolo_backend import YoloDetector, resolve_model_path


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))         # Linux, macOS
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
    (tmp_path / "models" / "yolo").mkdir(parents=True)
    return tmp_path


def test_expands_home_folder(home):
    assert resolve_model_path("~/models/yolo") == str(home / "models" / "yolo")


def test_result_does_not_depend_on_launch_folder(home, monkeypatch):
    (home / "elsewhere").mkdir()
    monkeypatch.chdir(home / "elsewhere")
    assert resolve_model_path("~/models/yolo") == str(home / "models" / "yolo")


def test_missing_model_names_the_path_and_the_fix(tmp_path):
    missing = str(tmp_path / "nope")
    with pytest.raises(FileNotFoundError) as error:
        resolve_model_path(missing)
    assert missing in str(error.value)
    assert "README" in str(error.value)


def test_error_for_a_relative_path_gives_the_full_location(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError) as error:
        resolve_model_path("nope")
    assert str(tmp_path.resolve() / "nope") in str(error.value)


def test_error_shows_a_windows_path_as_typed(monkeypatch):
    # %r would double every backslash, so the user couldn't copy the path.
    windows = r"C:\Users\robot\models\yolo.onnx"
    monkeypatch.setattr("os.path.abspath", lambda path: windows)
    with pytest.raises(FileNotFoundError) as error:
        resolve_model_path("nope")
    assert windows in str(error.value)


def test_detector_checks_the_model_before_loading_ultralytics(tmp_path):
    with pytest.raises(FileNotFoundError, match="README"):
        YoloDetector(str(tmp_path / "nope"), 320, 0.25)


class Row(list):
    """One row of an Ultralytics tensor: indexable, with tolist()."""

    def tolist(self):
        return list(self)


class FakeBox:
    def __init__(self, cls, conf, xyxy, xyxyn):
        self.cls, self.conf = [cls], [conf]
        self.xyxy, self.xyxyn = [Row(xyxy)], [Row(xyxyn)]


class FakeModel:
    """Answers predict() like Ultralytics, for a 640 x 480 frame."""

    def predict(self, image, **settings):
        result = type("Result", (), {})()
        result.names = {0: "person", 39: "bottle"}
        result.boxes = [FakeBox(39, 0.9, [320, 240, 384, 480],
                                [0.5, 0.5, 0.6, 1.0])]
        return [result]


def test_detection_has_the_box_as_fractions_of_the_frame():
    detector = YoloDetector.__new__(YoloDetector)  # skip loading a model
    detector._model, detector._image_size, detector._confidence = (
        FakeModel(), 320, 0.25)
    [bottle] = detector.detect(None)
    assert (bottle.name, bottle.confidence) == ("bottle", 0.9)
    assert bottle.area == 64 * 240
    assert bottle.box == (0.5, 0.5, 0.6, 1.0)
