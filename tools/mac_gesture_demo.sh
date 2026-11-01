#!/usr/bin/env bash
# Set up and run the gesture_control webcam demo on a Mac, without ROS.
#
#   bash tools/mac_gesture_demo.sh             # set up (first time) and run
#   bash tools/mac_gesture_demo.sh --camera 1  # options pass to webcam_demo
#   bash tools/mac_gesture_demo.sh --setup-only
#
# What it does:
#   1. finds Python 3.12, 3.11 or 3.10 (the versions MediaPipe ships Mac wheels for)
#   2. makes a venv in .venv-gesture/ at the repo root and installs mediapipe
#   3. downloads the hand model to ~/models/hand_landmarker.task (once)
#   4. runs gesture_control.webcam_demo (ESC or q quits)
#
# Re-running is safe: finished steps are skipped.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO/.venv-gesture"
MODEL_DIR="$HOME/models"
MODEL="$MODEL_DIR/hand_landmarker.task"
MODEL_URL="https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

SETUP_ONLY=0
if [[ "${1:-}" == "--setup-only" ]]; then SETUP_ONLY=1; shift; fi

[[ "$(uname -s)" == "Darwin" ]] || die "this script is for macOS. On Linux, follow src/gesture_control/README.md."

# 1. Python
if [[ ! -x "$VENV/bin/python" ]]; then
  say "Looking for Python 3.12, 3.11 or 3.10"
  PY=""
  for v in 3.12 3.11 3.10; do
    for cand in "python$v" "/opt/homebrew/bin/python$v" "/usr/local/bin/python$v"; do
      if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; break 2; fi
    done
  done
  if [[ -z "$PY" ]]; then
    die "no Python 3.10 to 3.12 found. Install one, then re-run:
       brew install python@3.12
   (MediaPipe has no wheels for newer Pythons yet, so the macOS system python3 may not work.)"
  fi
  say "Using $PY ($("$PY" --version))"

  # 2. venv
  say "Creating venv at $VENV"
  "$PY" -m venv "$VENV"
fi

PYV="$VENV/bin/python"
if ! "$PYV" -c "import mediapipe" >/dev/null 2>&1; then
  say "Installing mediapipe (brings OpenCV as opencv-contrib-python)"
  "$PYV" -m pip install --upgrade pip
  # Don't add opencv-python: it also provides cv2 and clashes with the contrib build.
  "$PYV" -m pip install mediapipe
fi

say "Checking the MediaPipe install"
"$PYV" - <<'EOF'
import cv2, mediapipe as mp
print("mediapipe", mp.__version__, "| opencv", cv2.__version__)
try:
    from mediapipe.tasks.python import vision  # noqa: F401
    print("Tasks API: available")
except Exception as e:
    print("Tasks API: NOT available (%s). The demo will try mp.solutions instead." % e)
EOF

# 3. model
if [[ ! -s "$MODEL" ]] || (( $(wc -c < "$MODEL") < 1000000 )); then
  say "Downloading the hand model to $MODEL"
  mkdir -p "$MODEL_DIR"
  curl -fL --retry 3 -o "$MODEL.part" "$MODEL_URL" || die "download failed: $MODEL_URL"
  # A real model is several MB. A tiny file is an error page, not the model.
  size=$(wc -c < "$MODEL.part")
  (( size > 1000000 )) || { rm -f "$MODEL.part"; die "downloaded file is only $size bytes, not a model"; }
  mv "$MODEL.part" "$MODEL"
fi
say "Model: $MODEL ($(( $(wc -c < "$MODEL") / 1024 )) KB)"

if (( SETUP_ONLY )); then
  say "Setup done. Run the demo with: bash tools/mac_gesture_demo.sh"
  exit 0
fi

# 4. demo
say "Starting the webcam demo (ESC or q quits)"
cat <<'EOF'
   fist                     -> stop
   open hand above centre   -> forward
   open hand below centre   -> back   (needs 6 frames)
   open hand left / right   -> left / right
   open hand in the circle  -> none
   no hand                  -> none   (after 0.3 s)

   First run: macOS asks to give your terminal camera access. If the window
   stays black, allow it in System Settings > Privacy & Security > Camera,
   then quit and reopen the terminal.
EOF
cd "$REPO/src/gesture_control"
exec "$PYV" -m gesture_control.webcam_demo --model "$MODEL" "$@"
