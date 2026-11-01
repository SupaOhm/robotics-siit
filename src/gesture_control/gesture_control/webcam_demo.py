"""Try the gestures on a laptop webcam, no ROS needed.

    pip install mediapipe
    python -m gesture_control.webcam_demo --model ~/models/hand_landmarker.task

Shows the camera with the hand skeleton, the centre deadzone and the word
the node would publish. Word changes are printed. ESC or q quits.
"""

import argparse
import threading

from .classifier import ClassifierParams, GestureClassifier
from .command_source import GesturePipeline
from .smoother import WordSmoother


def main(argv=None):
    d = ClassifierParams()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--camera", type=int, default=0, help="camera index")
    parser.add_argument("--model", default="~/models/hand_landmarker.task",
                        help="hand_landmarker.task path")
    parser.add_argument("--deadzone", type=float, default=d.deadzone_radius)
    parser.add_argument("--extend-ratio", type=float, default=d.extend_ratio)
    parser.add_argument("--confirm-frames", type=int, default=3)
    parser.add_argument("--back-confirm-frames", type=int, default=6)
    args = parser.parse_args(argv)

    params = ClassifierParams(deadzone_radius=args.deadzone, extend_ratio=args.extend_ratio)
    pipeline = GesturePipeline(GestureClassifier(params),
                               WordSmoother(args.confirm_frames, args.back_confirm_frames))
    last = [None]

    def on_word(word, _stamp):
        if word != last[0]:
            print(word)
            last[0] = word

    from .camera_loop import run_camera

    stop = threading.Event()
    try:
        run_camera(pipeline, on_word, stop, camera_index=args.camera,
                   model_path=args.model, show_window=True, esc_quits=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
