# Synthetic wake-phrase fixtures

These WAV files were synthesised on 2026-09-28 with
[Piper](https://github.com/OHF-Voice/piper1-gpl) 1.8.0 and the
`en_US-ljspeech-medium` voice from
[rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ljspeech/medium).
They are checked in so the default tests use no network, microphone, hosted
ASR, or robot.

## Licence

| Part | Licence | Bearing on these files |
|---|---|---|
| Training data: [LJ Speech](https://keithito.com/LJ-Speech-Dataset/) | Public domain | The voice carries no rights of a speaker or a dataset |
| Voice model `en_US-ljspeech-medium.onnx` | MIT (the piper-voices repository) | Used to generate the audio; not distributed here |
| Piper | GPL-3.0-or-later | Used as a tool; its licence does not cover the audio it produces |

The files are distributed under this repository's Apache-2.0 licence. The
previous fixtures were generated with macOS system voices, whose licence does
not extend to publishing the audio, and were replaced for that reason.

## How each file was made

Each phrase was synthesised at 22.05 kHz, the two parts of the paused phrase
were joined with the stated silence, and the result was converted with
`ffmpeg`: leading and trailing silence removed at -50 dB, 80 ms of silence
added at each end, then mono 16 kHz 16-bit PCM. The settings were chosen by
scoring candidates against the wake grammar, so that the wake phrases score
high and the ambient question scores low.

| File | Text | `length_scale` | `noise_scale` | `noise_w_scale` | Silence between parts | Acceptance role |
|---|---|---|---|---|---|---|
| `hey_misty_normal.wav` | "Hey Misty, hello there." | 1.0 | 0.333 | 0.8 | | Hey phrase, ordinary rate |
| `hey_misty_fast.wav` | "Hey Misty, hello there." | 0.75 | 0.333 | 0.5 | | Hey phrase, faster rate |
| `hey_misty_pause.wav` | "Hey." then "Misty, hello there." | 0.9 | 0.667 | 0.5 | 0.3 s | reasonable pause inside the phrase |
| `hi_misty_slow.wav` | "Hi Misty, hello there." | 1.2 | 0.333 | 0.8 | | Hi phrase, slower rate |
| `hey_misty_only.wav` | "Hey Misty!" | 1.1 | 0.667 | 0.5 | | wake followed only by trailing silence |
| `ambient_question.wav` | "What time is it?" | 1.1 | 0.5 | 0.8 | | false-trigger negative control |

Piper's noise settings are random, so running the same settings again gives
similar audio rather than identical files.

## Scores and the threshold

The local detector scores each file against the `(hey | hi) misty` grammar.
The wake phrases score between 0.727 (the paused phrase) and 0.802, and the
ambient question scores 0.539. `wake_minimum_confidence` is 0.68, chosen
between those two figures in the same way the earlier value of 0.78 was
chosen for the earlier voices (`PLAN.md` §16.68). The threshold therefore
describes these synthetic files and nothing more.

These are synthetic voices in quiet conditions. They are not evidence of
human-speaker accuracy, room-noise robustness, Misty II microphone behaviour,
or any hardware integration. The project has no Misty II and none of these
files came from one.
