# Voice notes and photos (media bench)

How well Katlego handles a voice note or a photo compared with the same thing typed, and what each costs. Runs the real code: `app/adapters/stt.py`, `app/worker.py`, the tutor engine.

A **set** is a folder here with two manifests and the files they name:

| Set | What it is |
|---|---|
| `synthetic/` | 80 text-to-speech clips (40 messages, clean and with added noise) and 18 drawn "photos". Made by `make_synthetic.py`. A best case: no real accents, no real handwriting |
| `real/` | The 10 voice notes and 10 photos to record by hand. The manifests are already filled in; only the files are missing |

## Recording the real set

Voice notes: `real/voice.jsonl` lists 10 lines to say (`said`). The quickest way on a Mac is `python3 evals/bench/media/record_real.py`, which shows each line, records from the microphone and saves the file under the right name. Or record each as a WhatsApp voice note and save it as `real/voice/rv01.ogg` … `rv10.ogg` (`.opus`, `.m4a` and `.mp3` also work: change `file` in the manifest). For rv08–rv10 use your own words in isiZulu, Sesotho or Afrikaans around the maths, then edit `said` and `typed` to what you actually said.

Photos: `real/photo.jsonl` lists 10 pages (`lines` is what to write, one entry per line; `{2/3}` means a stacked fraction, `x^2` a raised power; `caption` is the message sent with it). Write each by hand in an exercise book, photograph it with a phone, **send it to yourself on WhatsApp** and save the received copy as `real/photo/rp01.jpg` … `rp10.jpg`, so it has WhatsApp's compression. For the three diagrams (rp08–rp10) draw the figure with the labels in `values`.

Then, from the repo root on a Mac with ffmpeg:

```bash
python3 evals/bench/media/make_synthetic.py --probe real     # fills in each note's length
alias media='docker compose run --rm evals python -m evals.bench.media.run'
media stt    --set real          # free
media voice  --set real          # free
media photos --set real          # prints the plan; add --yes to spend
media chats  --set real          # prints the plan; add --yes to spend
```

## Manifest fields

`voice.jsonl`: `id`, `file`, `grade`, `cat`, `lang`, `said` (the exact words), `typed` (how a learner would type it), `role` (`question` or `answer`); for an answer also `problem` (the open question) and `verdict` (what the code answer check gives the typed form).

`photo.jsonl`: `id`, `file`, `grade`, `type` (`question`, `working`, `diagram`), `caption`, `lines`, `problem` (what a perfect read returns), `keys` (must appear in the read), `wrong_line` (first wrong line of working, 1-based, or null), `values` (labels on a diagram), `answers` (final answers, for the leak check), `followups` (what the learner types next in the chat test).

## What each command measures

| Command | Cost | Output (`evals/bench/results/media/<set>/`) |
|---|---|---|
| `stt` | free (local container, Groq free tier) | `stt.jsonl`: transcript and seconds taken per clip, per engine, English forced and auto-detect |
| `voice` | free (stub model) | `voice.jsonl`: per transcript, was the maths kept, does it reach the same topic, does code see the same problem, does the code answer check still run |
| `photos` | paid | `photos.jsonl`: per vision model, today's single reply and a structured read, scored against the manifest, with billed cost |
| `chats` | paid (`--stub` is free) | `chats.jsonl`: whole conversations through `worker.process_job`: typed vs voice note; typed vs the old single photo reply (`PHOTO_PIPELINE=single`) vs read-first (`PHOTO_PIPELINE=read`, the default since 15 Nov 2026) |

`score.py` holds the scoring rules (`python -m evals.bench.media.score` checks them).

## Status (15 Nov 2026)

Both sets have been run: `synthetic/` on 10 Nov, `real/` (10 handwritten photos, 10 voice notes from one speaker) on 15 Nov. Results are under `evals/bench/results/media/`; the write-up is `pitch/katlego-voice-photo-review.html`. Changes that came out of it: `STT_SYMBOLS` (spoken maths to symbols, `app/tutor/spoken.py`), the misheard-note check (`spoken.unclear`), and `PHOTO_PIPELINE=read` as the default.
