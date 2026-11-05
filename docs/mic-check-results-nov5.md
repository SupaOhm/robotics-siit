# mic_check results on the robot, Nov 5 (reference for D34)

Raw output of `tools/mic_check.py` in the robot container (Yahboom ROSMASTER M1, Pi 5, USB mic on card 2, 48 kHz, mic gain 40%, Vosk `vosk-model-small-en-us-0.15`). Logic 2 (Vosk streaming) is the logic D34 builds into `password_node`. Use these numbers as the baseline: the build should match or beat Logic 2.

## How to rerun

Stop `password_node` first: only one program can open the mic.

```bash
# in the container, repo at /root/share/robotics-siit
amixer -c 2 sset Mic capture 40%
python3 -W ignore tools/mic_check.py --env-file .env --digits          # "Say zero" ... "Say nine", summary table
eval "$(grep "^export ROBOT_PASSWORD_HASH=" /root/.bashrc | sed "s/  #.*//")"
python3 -W ignore tools/mic_check.py --env-file .env                   # 3 tries against the robot's password
python3 -W ignore tools/mic_check.py --env-file .env --gain 30,40,50 --tries 2   # gain sweep
```

Each try sends the clip and a caption to the operator chat on Telegram. `--no-telegram` prints only.

## 1. Digits 0 to 9 (`--digits`), after the 48 kHz fix, Samantha voice and beep

```text
📊 Digit check: asked → heard (Logic 1 = password_node, Logic 2 = Vosk streaming)
0 zero → 0 ✅ · L2 0 ✅ · said "seal"
1 one → 1 ✅ · L2 1 ✅ · said "one"
2 two → - ❌ · L2 2 ✅ · said "two"
3 three → 3 ✅ · L2 3 ✅ · said "three"
4 four → - ❌ · L2 4 ✅ · said "for"
5 five → 5 ✅ · L2 5 ✅ · said "five"
6 six → - ❌ · L2 6 ✅ · said "six"
7 seven → - ❌ · L2 7 ✅ · said "so and"
8 eight → 8 ✅ · L2 8 ✅ · said "act"
9 nine → 9 ✅ · L2 9 ✅ · said "nine"
Right: Logic 1 6/10, Logic 2 10/10

```

Logic 1 misses were all "no speech above 4000" (loudest 1915, 3049, 3228, 2461). Room noise 110 to 210.

## 2. The robot's 2-digit test password, 3 tries (transcripts removed: the repo is public)

```text
🎙 Mic check 1 (gain 40%)
Logic 1 · threshold listen (password_node now)
  speech 1.17–2.01 s
  free "…" ✅ · grammar "…" ✅
Logic 2 · Vosk streaming (proposed)
  free "…" ✅ at 2.54 s · grammar "…" ✅ at 2.33 s
Levels: peak -7.3 dBFS, RMS -28.5 dBFS, clipped 0.00%, noise 138, loudest 6271
Gap countdown end → listening: 12 ms
🎙 Mic check 2 (gain 40%)
Logic 1 · threshold listen (password_node now)
  speech 0.79–2.01 s
  free "…" ✅ · grammar "…" ✅
Logic 2 · Vosk streaming (proposed)
  free "…" ✅ at 2.33 s · grammar "…" ✅ at 2.07 s
Levels: peak -0.2 dBFS, RMS -24.1 dBFS, clipped 0.00%, noise 140, loudest 9673
Gap countdown end → listening: 0 ms
🎙 Mic check 3 (gain 40%)
Logic 1 · threshold listen (password_node now)
  speech 1.15–2.07 s
  free "…" ❌ · grammar "…" ✅
Logic 2 · Vosk streaming (proposed)
  free "…" ✅ at 2.56 s · grammar "…" ✅ at 2.33 s
Levels: peak -5.5 dBFS, RMS -27.3 dBFS, clipped 0.00%, noise 112, loudest 4811
Gap countdown end → listening: 0 ms
```

## 3. Earlier runs: what was wrong and fixed

| Run | Result | Cause, fix |
|---|---|---|
| Mic opened at 44.1 kHz | "hello" heard as "oh", "huh", "how how"; voice sped up and high | The mic delivers ~24,300 samples/s at 44.1 kHz. Fixed: `mic_sample_rate: 48000` |
| Free speech for the check | "hello" 0/3 | Accent. Fixed: digits-only grammar for the check, free speech for the caption only (D24) |
| `--digits`, Thai default voice, 0.6 s gap after "one" | Logic 1 7/10, Logic 2 9/10 | Clips now Samantha (en_US); countdown ends at "one", then `password_beep` opens the mic (D33) |
| Re-opening the mic for each try | Hung on try 2 | `mic_check` opens it once and reads in a thread |
