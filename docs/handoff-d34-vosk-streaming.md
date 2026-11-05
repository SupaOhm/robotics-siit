# Handoff: password_node listens with Vosk streaming (D34)

For @Tinpatpun (Lane 4). Decided by Lane 1 on Nov 5 from robot data, not
built yet. Builds on #37 (`lane1/password-recording`).

## Goal

`password_node` stops using SpeechRecognition's `listen()`, which waits for
sound louder than `energy_threshold`. Instead it feeds every mic chunk to
Vosk from the moment the beep ends, and the first phrase Vosk recognises is
the answer. No loudness threshold to tune per room or mic gain.

## Why (measured on the robot, Nov 5)

`tools/mic_check.py` runs both logics on the same recording:

| Run | Threshold `listen()` (today) | Vosk streaming |
|---|---|---|
| `--digits`, 10 tries, gain 40% | 6/10 | **10/10** |
| the robot's 2-digit test password, 3 tries | 3/3 | 3/3 |

All 4 misses were speech quieter than `energy_threshold` 4000 (loudest
1915 to 3228; room noise 110 to 210). Earlier the threshold calibrated to
21431 at start-up, and no speech ever passed it.

## What to change

Only `listen_once` in `src/password_system/password_system/speech.py`, for
`engine == "vosk"`. Keep `listen()` for `engine == "google"`.

```text
listen_once()
  open the mic (48 kHz, mic_sample_rate)
  rec = KaldiRecognizer(model, 16000, digit grammar)   # the check, as now
  for each chunk until listen_window (10 s):
    pcm16k = resample(chunk)        # audioop.ratecv with state, as mic_check
    keep chunk for the WAV          # D32 recordings
    if rec.AcceptWaveform(pcm16k) and Result() has words:
      return speech(candidates, wav, free_text)
    if no words started by listen_timeout (6 s):
      return no_speech
  FinalResult() -> speech if words, else no_speech
```

Reference code that already runs on the robot: `VoskStream` and `Mic` in
`tools/mic_check.py` (Logic 2).

**Reference test:** [mic-check-results-nov5.md](mic-check-results-nov5.md)
has the exact commands and today's raw output. The build should match or beat
Logic 2 there.

## Must stay the same

- **`ListenResult`:** `kind` is `speech`, `no_speech` or `error`;
  `candidates` come from the digits-only grammar; `wav` holds the answer
  for D32; `free_text` comes from a free-speech pass for the caption only
  (D24).
- **The countdown sync (D33):** the mic opens on `/audio/done password_beep`.
- **`match_mode: first`** and the verifier: no change.
- **Settings:** `mic_sample_rate: 48000` (at 44.1 kHz the robot's mic
  delivers ~24,300 samples/s), `mic_device_index: 0`, mic gain 40%.
- **Silence** still costs an attempt (`no_speech`).

## Watch out for

- **Opening the mic:** re-opening it per try hung once in `mic_check` (at
  44.1 kHz, before the rate fix). `mic_check` now opens it once and reads in
  a thread. Opening per attempt may be fine at 48 kHz; if it hangs, keep one
  stream open for the node's life.
- **A cancel during a listen:** a new session can start while the old
  listen is still running, and both open the mic (`PortAudio not
  initialized`, seen on the robot). The streaming loop should check the
  session's cancel event between chunks and stop.
- **`energy_threshold` and `calibrate()`** have no job with Vosk streaming.
  Skip calibration for `engine: vosk`, so start-up noise can't break
  anything.
- **CPU:** two recognisers (grammar + free speech) on the Pi 5. Real time
  in `mic_check`; check `top` during a session.

## Done when

1. **Tests (no ROS, no mic):** a fake recogniser fed chunks returns
   `speech` at its first phrase, `no_speech` after 6 s without words, and
   stops on cancel. Free-speech text only reaches `free_text`.
2. **On the robot:** `mic_check --digits` is still at least 9/10, and a real
   session with `password_test.py` grants the robot's test password and
   denies a wrong digit with the voice reply on Telegram.
3. **Docs:** D34 says built, and the README's `energy_threshold` row says
   it applies to `engine: google` only.

## Until it's built

On the robot, start `password_node` with `-p energy_threshold:=1000.0`
(about 5x the room noise; every miss above was louder than 1915).
