"""Tables from the media bench results. Free: reads result files only.

    python -m evals.bench.media.summary --set synthetic            # prints the tables
    python -m evals.bench.media.summary --set synthetic --json     # the same numbers as JSON

Speech-to-text prices are LIST prices (Groq bills nothing on the free tier):
whisper-large-v3 $0.111 and whisper-large-v3-turbo $0.04 per hour of audio,
each request billed as at least 10 seconds (groq.com/pricing, Nov 2026).
"""

import argparse
import json
import statistics
import tomllib
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
RESULTS = HERE.parent / "results" / "media"
STT_USD_PER_HOUR = {"groq-v3": 0.111, "groq-turbo": 0.04, "groq-turbo-hint": 0.04, "local-base": 0.0}
STT_MIN_SECONDS = 10


def stt_cost(engine: str, seconds: float) -> float:
    return STT_USD_PER_HOUR[engine] * max(seconds, STT_MIN_SECONDS) / 3600


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def _share(flags) -> dict:
    flags = list(flags)
    return {"n": sum(bool(f) for f in flags), "of": len(flags)}


def build(set_: str) -> dict:
    res = RESULTS / set_
    clips = {c["id"]: c for c in _load(HERE / set_ / "voice.jsonl")}
    photos = {p["id"]: p for p in _load(HERE / set_ / "photo.jsonl")}
    out: dict = {"set": set_}

    # ── voice: transcription ────────────────────────────────────────────────
    stt = [r for r in _load(res / "stt.jsonl") if r["id"] in clips]
    landed = {(r["id"], r["variant"]): r for r in _load(res / "voice.jsonl")}
    groups = defaultdict(list)
    for r in stt:
        c = clips[r["id"]]
        groups[(r["engine"], r["lang"], c.get("condition", "real"))].append(r)
    table = []
    for (engine, lang, cond), rs in sorted(groups.items()):
        def rows_for(pred):
            return [r for r in rs if pred(clips[r["id"]])]

        def kept(rows):
            return _share(landed.get((r["id"], f"{engine}/{lang}"), {}).get("maths_kept") for r in rows)
        english, switched = rows_for(lambda c: c["cat"] != "code-switch"), rows_for(lambda c: c["cat"] == "code-switch")
        q = [r for r in rs if clips[r["id"]]["role"] == "question"]
        a = [r for r in rs if clips[r["id"]]["role"] == "answer"]

        def same(rows, field):
            return _share(landed.get((r["id"], f"{engine}/{lang}"), {}).get(field)
                          == landed.get((r["id"], "typed"), {}).get(field) for r in rows)
        table.append({
            "engine": engine, "lang": lang, "condition": cond,
            "maths_kept_english": kept(english), "maths_kept_code_switch": kept(switched),
            "by_category": {cat: kept(rows_for(lambda c, cat=cat: c["cat"] == cat))
                            for cat in dict.fromkeys(c["cat"] for c in clips.values())},
            "same_topic_as_typed": same(q, "topic"),
            "right_topic": _share(landed.get((r["id"], f"{engine}/{lang}"), {}).get("topic") == clips[r["id"]].get("topic")
                                  for r in q),
            # code works out the same answer from the transcript as from the typed question
            "code_solves_question": _share(
                landed.get((r["id"], "typed"), {}).get("code_sees") is not None
                and landed.get((r["id"], f"{engine}/{lang}"), {}).get(field) == landed[(r["id"], "typed")]["code_sees"]
                for r in q for field in ("code_sees",)),
            "code_solves_question_if_normalised": _share(
                landed.get((r["id"], "typed"), {}).get("code_sees") is not None
                and landed.get((r["id"], f"{engine}/{lang}"), {}).get("code_sees_if_normalised")
                == landed[(r["id"], "typed")]["code_sees"] for r in q),
            # the same two measures with the step that is now in the app (STT_SYMBOLS)
            "code_solves_question_with_symbols": _share(
                landed.get((r["id"], "typed"), {}).get("code_sees") is not None
                and landed.get((r["id"], f"{engine}/{lang}"), {}).get("code_sees_with_symbols")
                == landed[(r["id"], "typed")]["code_sees"] for r in q),
            "answer_code_checked_with_symbols": _share(
                landed.get((r["id"], f"{engine}/{lang}"), {}).get("code_check_with_symbols") == clips[r["id"]]["verdict"]
                for r in a),
            "code_sees_same_problem": same(q, "code_sees"),
            "code_sees_same_problem_if_normalised": _share(
                landed.get((r["id"], f"{engine}/{lang}"), {}).get("code_sees_if_normalised")
                == landed.get((r["id"], "typed"), {}).get("code_sees") for r in q),
            "answer_stays_on_problem": _share(landed.get((r["id"], f"{engine}/{lang}"), {}).get("continuing") for r in a),
            "answer_code_checked": _share(
                landed.get((r["id"], f"{engine}/{lang}"), {}).get("code_check") == clips[r["id"]]["verdict"] for r in a),
            "answer_code_checked_if_normalised": _share(
                landed.get((r["id"], f"{engine}/{lang}"), {}).get("code_check_if_normalised") == clips[r["id"]]["verdict"]
                for r in a),
            "median_latency_s": round(statistics.median(r["latency_s"] for r in rs), 2),
            "p95_latency_s": round(sorted(r["latency_s"] for r in rs)[int(len(rs) * 0.95) - 1], 2),
        })
    out["stt"] = table
    typed_a = [c for c in clips.values() if c["role"] == "answer" and c.get("condition", "clean") != "noisy"]
    typed_q = [c for c in clips.values() if c["role"] == "question" and c.get("condition", "clean") != "noisy"]
    out["typed"] = {
        "answer_code_checked": _share(landed.get((c["id"], "typed"), {}).get("code_check") == c["verdict"] for c in typed_a),
        "question_code_solvable": _share(landed.get((c["id"], "typed"), {}).get("code_sees") for c in typed_q),
        "right_topic": _share(landed.get((c["id"], "typed"), {}).get("topic") == c.get("topic") for c in typed_q),
    }
    secs = [c["seconds"] for c in clips.values() if c.get("seconds") and c.get("condition", "clean") != "noisy"]
    out["note_seconds"] = {"median": statistics.median(secs), "max": max(secs)} if secs else None

    # ── photos: per model ───────────────────────────────────────────────────
    rows = [r for r in _load(res / "photos.jsonl") if r["photo"] in photos and not r.get("error")]
    manual = json.loads((res / "manual_grades.json").read_text()) if (res / "manual_grades.json").exists() else {}
    models = []
    for model in dict.fromkeys(r["model"] for r in rows):
        reads = [r for r in rows if r["model"] == model and r["kind"] == "read"]
        today = [r for r in rows if r["model"] == model and r["kind"] == "today"]
        entry = {"model": model, "by_type": {}}
        for t in ("question", "working", "diagram"):
            rs = [r for r in reads if r["type"] == t]
            entry["by_type"][t] = {k: {"n": int(sum(r["score"][k] for r in rs if k in r["score"])),
                                       "of": sum(1 for r in rs if k in r["score"])}
                                   for k in ("problem", "working", "mistake", "values")
                                   if any(k in r["score"] for r in rs)}
        for name, rs in (("read", reads), ("today", today)):
            entry[name] = {"median_cost_usd": statistics.median(r["cost_usd"] for r in rs),
                           "median_input_tokens": statistics.median(r["input_tokens"] for r in rs),
                           "median_output_tokens": statistics.median(r["output_tokens"] for r in rs),
                           "median_latency_s": round(statistics.median(r["latency_s"] for r in rs), 1)}
        entry["manual"] = manual.get(model)
        models.append(entry)
    out["photos"] = models
    out["photo_spend_usd"] = round(sum(r["cost_usd"] for r in _load(res / "photos.jsonl")), 4)

    # ── chats: typed vs voice note; typed vs today's photo reply vs read-first ─
    # a chat that hit an error is run again on resume: keep the latest row of each
    chats = list({(c["flow"], c["arm"]): c for c in _load(res / "chats.jsonl")}.values())
    out["chat_spend_usd"] = round(sum(c["cost_usd"] for c in chats), 4)
    by = {(c["flow"], c["arm"]): c for c in chats}
    arms = {}
    for arm in ("typed", "single", "read"):
        cs = [c for c in chats if c["flow"].startswith("photo:") and c["arm"] == arm]
        if not cs:
            continue
        with_followups = [c for c in cs if c["check"]["followups"]]

        def topic_ok(c):
            ref = by.get((c["flow"], "typed"))
            want = ref["turns"][0]["topic"] if ref else None
            return bool(c["events"]) and all(e["topic"] == want for e in c["events"])
        first = [c["turns"][0] for c in cs]
        later = [t for c in cs for t in c["turns"][1:]]
        arms[arm] = {
            "chats": len(cs),
            "errors": sum(any(t.get("error") for t in c["turns"]) for c in cs),
            "opened_problem": _share(c["check"]["opened_problem"] for c in cs),
            "stayed_on_problem": _share(c["check"]["stayed_on_problem"] for c in with_followups),
            "followups_code_checked": {"n": sum(c["check"]["code_checked_followups"] for c in cs),
                                       "of": sum(c["check"]["followups"] for c in cs)},
            "working_code_checked": _share(c["check"]["code_checked_working"] for c in cs if c["type"] == "working"),
            "leaked_answer": _share(c["check"]["leaked_answer"] for c in cs if photos[c["flow"][6:]].get("answers")),
            "evidence_on_typed_topic": _share(topic_ok(c) for c in cs),
            # mastery evidence was written, and all of it on a topic that is right for the page
            "evidence_on_right_topic": _share(
                bool(c["events"]) and all(e["topic"] in photos[c["flow"][6:]].get("topics", []) for e in c["events"])
                for c in cs),
            "no_evidence": _share(not c["events"] for c in cs),
            # the learner's last message is the right answer: did Katlego accept it?
            "right_answer_accepted": _share(c["turns"][-1]["ev"] == "attempt_correct"
                                            for c in cs if len(c["turns"]) == 3),
            "by_type": {t: {
                "stayed_on_problem": _share(c["check"]["stayed_on_problem"] for c in with_followups if c["type"] == t),
                "right_answer_accepted": _share(c["turns"][-1]["ev"] == "attempt_correct"
                                                for c in cs if c["type"] == t and len(c["turns"]) == 3),
                "evidence_on_right_topic": _share(
                    bool(c["events"]) and all(e["topic"] in photos[c["flow"][6:]].get("topics", []) for e in c["events"])
                    for c in cs if c["type"] == t),
            } for t in ("question", "working", "diagram")},
            "evidence_rows": sum(len(c["events"]) for c in cs),
            "first_message_cost_usd": statistics.median(t["cost_usd"] for t in first),
            "first_message_latency_s": round(statistics.median(t["latency_s"] for t in first), 1),
            "followup_cost_usd": statistics.median(t["cost_usd"] for t in later) if later else None,
            "chat_cost_usd": statistics.mean(c["cost_usd"] for c in cs),
        }
    out["photo_chats"] = arms
    voice = {}
    for arm in ("typed", "voice"):
        cs = [c for c in chats if c["flow"].startswith("voice:") and c["arm"] == arm]
        if not cs:
            continue
        last = [c["turns"][-1] for c in cs]
        voice[arm] = {
            "chats": len(cs), "errors": sum(any(t.get("error") for t in c["turns"]) for c in cs),
            "message_cost_usd": statistics.median(t["cost_usd"] for t in last),
            "message_latency_s": round(statistics.median(t["latency_s"] for t in last), 1),
            "same_topic_as_typed": _share(
                c["turns"][-1]["topic"] == by[(c["flow"], "typed")]["turns"][-1]["topic"]
                for c in cs if (c["flow"], "typed") in by),
            "same_code_check_as_typed": _share(
                c["turns"][-1]["code_check"] == by[(c["flow"], "typed")]["turns"][-1]["code_check"]
                for c in cs if c["type"] == "answer" and (c["flow"], "typed") in by),
        }
    out["voice_chats"] = voice

    # ── cost per message and per learner per month ──────────────────────────
    text_turns = [t for c in chats if c["arm"] == "typed" for t in c["turns"] if not t.get("error")]
    if text_turns and "single" in arms and "read" in arms:
        mix = tomllib.loads((HERE.parent / "gates.toml").read_text())["mix"]
        msgs = mix["messages_per_learner_month"]
        text = statistics.mean(t["cost_usd"] for t in text_turns)
        # The vision call is priced from the `photos` run (first time each
        # image is sent). In `chats` the same image and prompt go out again
        # within minutes, so the provider's prompt cache makes it look ~5x cheaper.
        vision = next(m for m in models if m["model"] == "openai/gpt-6-luna")

        def tutor_part(turn):
            return sum(c["cost_usd"] or 0 for c in turn["calls"] if c["call"] not in ("photo_reply", "read_photo"))
        per = {"text": text,
               "photo_today": vision["today"]["median_cost_usd"],
               "photo_read_first": vision["read"]["median_cost_usd"] + statistics.mean(
                   tutor_part(c["turns"][0]) for c in chats if c["arm"] == "read")}
        for engine in ("groq-turbo", "groq-v3"):
            for secs_ in (10, 20, 45):
                per[f"voice_{engine}_{secs_}s"] = text + stt_cost(engine, secs_)
        months = {}
        for share in (0.0, 0.2, 0.5):
            months[f"{int(share * 100)}%"] = {
                "text_only": msgs * text,
                "voice_turbo_20s": msgs * ((1 - share) * text + share * per["voice_groq-turbo_20s"]),
                "voice_v3_20s": msgs * ((1 - share) * text + share * per["voice_groq-v3_20s"]),
                "photo_today": msgs * ((1 - share) * text + share * per["photo_today"]),
                "photo_read_first": msgs * ((1 - share) * text + share * per["photo_read_first"]),
            }
        out["cost"] = {"per_message_usd": per, "per_learner_month_usd": months, "messages_per_month": msgs,
                       "text_turns_measured": len(text_turns)}
    return out


def _fmt(v) -> str:
    if isinstance(v, dict) and set(v) == {"n", "of"}:
        return f"{v['n']}/{v['of']}"
    if isinstance(v, float):
        return f"{v:.5f}" if v < 0.1 else f"{v:.2f}"
    return str(v)


def _table(rows: list[dict], cols: list[str]) -> None:
    print("| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    for r in rows:
        print("| " + " | ".join(_fmt(r.get(c, "")) for c in cols) + " |")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", default="synthetic")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    s = build(args.set)
    if args.json:
        print(json.dumps(s, indent=1, ensure_ascii=False))
        return
    print(f"## Transcription ({args.set})\n")
    _table(s["stt"], ["engine", "lang", "condition", "maths_kept_english", "maths_kept_code_switch",
                      "right_topic", "code_solves_question", "code_solves_question_with_symbols",
                      "answer_code_checked_with_symbols",
                      "answer_stays_on_problem",
                      "answer_code_checked", "answer_code_checked_if_normalised", "median_latency_s"])
    print("Typed baseline:", {k: _fmt(v) for k, v in s["typed"].items()}, "\n")
    print("## Photo reads per model\n")
    for m in s["photos"]:
        print(m["model"], {t: {k: _fmt(v) for k, v in d.items()} for t, d in m["by_type"].items()},
              "| read $%.5f, today $%.5f" % (m["read"]["median_cost_usd"], m["today"]["median_cost_usd"]),
              "| manual:", m["manual"])
    print("\n## Photo chats\n")
    _table([{"arm": a, **d} for a, d in s["photo_chats"].items()],
           ["arm", "chats", "errors", "opened_problem", "stayed_on_problem", "followups_code_checked",
            "working_code_checked", "leaked_answer", "evidence_on_right_topic", "no_evidence",
            "right_answer_accepted", "first_message_cost_usd",
            "followup_cost_usd", "first_message_latency_s"])
    print("## Voice chats\n")
    _table([{"arm": a, **d} for a, d in s["voice_chats"].items()],
           ["arm", "chats", "errors", "message_cost_usd", "message_latency_s", "same_topic_as_typed",
            "same_code_check_as_typed"])
    if "cost" in s:
        print("## Cost per message (USD)\n")
        for k, v in s["cost"]["per_message_usd"].items():
            print(f"  {k:26} ${v:.5f}")
        print(f"\n## Cost per learner per month ({s['cost']['messages_per_month']} messages), by share sent as voice or photo\n")
        _table([{"share": k, **v} for k, v in s["cost"]["per_learner_month_usd"].items()],
               ["share", "text_only", "voice_turbo_20s", "voice_v3_20s", "photo_today", "photo_read_first"])
    print(f"Spend: photos ${s['photo_spend_usd']}, chats ${s['chat_spend_usd']}")


if __name__ == "__main__":
    main()
