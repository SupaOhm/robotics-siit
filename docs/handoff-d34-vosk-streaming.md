# Handoff: password_node listens with Vosk streaming (D34)

For @Tinpatpun (Lane 4). Decided by Lane 1 on Nov 5 from robot data, not
built yet. Builds on #37 (`lane1/password-recording`). Build it in a new PR
from a `lane4/` branch based on this one.

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
| password 67, 3 tries | 3/3 | 3/3 |

All 4 misses were speech quieter than `energy_threshold` 4000 (loudest
1915 to 3228; room noise 110 to 210). Earlier the threshold calibrated to
21431 at start-up, and no speech ever passed it.

## What to change

Only `listen_once` in `src/password_system/password_system/speech.py`, for
`engine == "vosk"`. Keep `listen()` for `engine == "google"`.

```text
listen_once(cancel)                 # run_session passes the session's cancel event
  open the mic (48 kHz, mic_sample_rate)
  rec = KaldiRecognizer(model, 16000, digit grammar)   # the check, as now
  for each chunk until listen_timeout + phrase_time_limit (11 s):
    if cancel is set: return no_speech   # run_session drops it anyway
    pcm16k = resample(chunk)        # audioop.ratecv with state, as mic_check
    keep pcm16k for the WAV         # D32 recordings, 16 kHz 16-bit as today
    if rec.AcceptWaveform(pcm16k):
      if Result() has digits: return speech(candidates, wav, free_text)
      if Result() has only [unk]: words started, keep listening
    if no words (digits or [unk]) by listen_timeout (6 s):
      return no_speech
  FinalResult() -> speech if digits
                -> speech with no candidates (unclear) + wav if only [unk]
                -> no_speech if nothing was heard
free_text: one free-speech pass over the kept audio once the answer is in,
           as free_text() does today (not a second streaming recogniser)
```

Put the loop in a plain function that takes the chunks, the recogniser and
the cancel event, and keep only the PyAudio wiring in `listen_once`, so the
tests need no mic. Count time by the audio fed (samples / rate), not the
wall clock, so the tests need no sleeps.

Reference code that already runs on the robot: `VoskStream` and `Mic` in
`tools/mic_check.py` (Logic 2).

## Must stay the same

- **`ListenResult`:** `kind` is `speech`, `no_speech` or `error`;
  `candidates` come from the digits-only grammar; `wav` holds the answer
  for D32; `free_text` comes from a free-speech pass for the caption only
  (D24).
- **Non-digit words are unclear, not silence:** "hello" or "um" with no
  digit is `speech` with no candidates, so the operator still gets the
  clip and its caption (D32: silence has no recording).
- **The countdown sync (D33):** the mic opens on `/audio/done password_beep`.
- **`match_mode: first`** and the verifier: no change.
- **Settings:** `mic_sample_rate: 48000` (at 44.1 kHz the robot's mic
  delivers ~24,300 samples/s), mic gain 40%. `mic_device_index: 0` is the
  robot's launch argument; `password.yaml` keeps `-1`.
- **Silence** still costs an attempt (`no_speech`).

## Watch out for

- **Opening the mic:** re-opening it per try hung once in `mic_check` (at
  44.1 kHz, before the rate fix). `mic_check` now opens it once and reads in
  a thread. Opening per attempt may be fine at 48 kHz; if it hangs, keep one
  stream open for the node's life. Then drop the chunks from before the
  beep's `/audio/done` (as `mic_check` does with `at < ended`), and flush or
  cap the queue between attempts so it can't grow while nobody listens.
- **A cancel during a listen:** a new session can start while the old
  listen is still running, and both open the mic (`PortAudio not
  initialized`, seen on the robot). Checking `cancel` between chunks lets
  the old worker free the mic within one chunk.
- **`energy_threshold` and `calibrate()`** have no job with Vosk streaming.
  Skip calibration for `engine: vosk`, so start-up noise can't break
  anything. `calibrate()` was also the only start-up mic check, so open and
  close the mic once instead, to keep the "microphone not available" log.
  Drop the "speech energy threshold" log line for vosk.
- **CPU:** only the grammar recogniser streams; free speech runs once per
  answer. Check `top` during a session on the Pi 5.

## Done when

1. **Tests (no ROS, no mic):** a fake recogniser fed chunks returns
   `speech` at its first digit phrase, `speech` with no candidates (and the
   wav) when it heard only `[unk]`, `no_speech` after 6 s without words,
   and stops on cancel. Free-speech text only reaches `free_text`.
2. **On the robot:** `mic_check --digits` is still at least 9/10, and a real
   session with `password_test.py` grants "six seven" (password 67) and
   denies a wrong digit with the voice reply on Telegram.
3. **Docs:** D34 says built, and the README's `energy_threshold` and
   `phrase_time_limit` rows say they apply to `engine: google` only.

## Until it's built

On the robot, start `password_node` with `-p energy_threshold:=1000.0`
(about 5x the room noise; every miss above was louder than 1915).
