"""Record the real voice notes on a Mac, one after another, straight into
real/voice/ as WhatsApp-style files (Ogg Opus, mono, 16 kHz). Needs ffmpeg.

    python3 evals/bench/media/record_real.py            # record the ones still missing
    python3 evals/bench/media/record_real.py rv03 rv08  # (re)record these
    python3 evals/bench/media/record_real.py --mic "NotyourIphone"   # another microphone

For each note it shows what to say. Press Enter to start, Enter to stop.
Then: Enter keeps it, p plays it back, r records it again.
The first run asks macOS for microphone access for your terminal app.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REAL = Path(__file__).parent / "real"
MANIFEST = REAL / "voice.jsonl"


def microphones() -> list[str]:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                         capture_output=True, text=True).stderr
    return re.findall(r"\[\d+\] (.+)", out.split("audio devices:")[-1])


def record(path: Path, mic: str) -> None:
    path.unlink(missing_ok=True)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-nostats", "-f", "avfoundation", "-i", f":{mic}",
         "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "16k", str(path)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    print("   opening the microphone…", end="", flush=True)
    # The mic takes a second or two to open; ffmpeg prints "Output #0" once it is live.
    for line in proc.stderr:
        if "Output #0" in line:
            break
    else:
        sys.exit("\n   ffmpeg could not open the microphone. Allow your terminal under "
                 "System Settings > Privacy & Security > Microphone, then run this again.")
    input("\r   ● RECORDING, speak now. Press Enter to stop ")
    proc.communicate("q")


def main() -> None:
    args = sys.argv[1:]
    mics = microphones()
    if "--mic" in args:
        want = args[args.index("--mic") + 1]
        del args[args.index("--mic"):args.index("--mic") + 2]
    else:
        want = "MacBook"
    mic = next((m for m in mics if want.lower() in m.lower()), None)
    if not mic:
        sys.exit(f"No microphone matching {want!r}. Found: {', '.join(mics) or 'none'}")
    rows = [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]
    todo = [r for r in rows if (r["id"] in args) or (not args and not (REAL / r["file"]).exists())]
    if not todo:
        sys.exit("All voice notes are recorded. Name one to redo it, e.g. rv03.")
    print(f"Microphone: {mic}. {len(todo)} note(s) to record. Speak as you would into WhatsApp.\n")
    (REAL / "voice").mkdir(exist_ok=True)
    for r in todo:
        path = REAL / r["file"]
        print(f"── {r['id']}  ({ {'en': 'English', 'zu': 'isiZulu + English', 'st': 'Sesotho + English', 'af': 'Afrikaans + English'}[r['lang']] })")
        if r["role"] == "answer":
            print(f"   (you are answering: {r['problem']})")
        print(f"   SAY:  {r['said']}")
        if r["lang"] != "en":
            print("   Use your own words around the maths if this is not how you would say it.")
        while True:
            input("   press Enter to start ")
            record(path, mic)
            while (choice := input("   Enter = keep, p = play back, r = record again: ").strip().lower()) == "p":
                subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)])
            if choice != "r":
                break
        if r["lang"] != "en":
            said = input("   If you said something different, type exactly what you said (Enter = as shown): ").strip()
            if said:
                r["said"] = said
                r["typed"] = ""  # filled in by hand before the run: how a learner would type it
        print()
    MANIFEST.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"Saved in {REAL / 'voice'}. Next: python3 evals/bench/media/make_synthetic.py --probe real")


if __name__ == "__main__":
    main()
