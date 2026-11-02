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


def test_detector_checks_the_model_before_loading_ultralytics(tmp_path):
    with pytest.raises(FileNotFoundError, match="README"):
        YoloDetector(str(tmp_path / "nope"), 320, 0.25)
