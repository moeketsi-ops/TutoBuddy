"""Voice notes and homework photos through the real Katlego code.

    alias media='docker compose run --rm evals python -m evals.bench.media.run'
    media stt    --set synthetic            # transcribe every clip (local + Groq)   free
    media voice  --set synthetic            # typed vs transcribed, stub tutor       free
    media photos --set synthetic            # per model: today's reply + a read      paid: quote, then --yes
    media chats  --set synthetic            # whole chats on the worker path         paid: quote, then --yes
    media chats  --set synthetic --stub     # the same on the stub, perfect reader   free

A set is a folder under evals/bench/media/ with voice.jsonl and photo.jsonl
(see README.md there). Results: evals/bench/results/media/<set>/*.jsonl, one
row per item, appended as each finishes; a rerun resumes.
"""

import argparse
import asyncio
import contextlib
import json
import random
import sys
import time
from pathlib import Path

import httpx

from app import worker
from app.adapters import ledger, llm, stt
from app.config import settings
from app.db import ensure_schema, get_pool
from app.orchestrator import session
from app.tutor import answer_check, engine, memory, spoken
from evals.bench import graders
from evals.bench.media import score

HERE = Path(__file__).parent
RESULTS = HERE.parent / "results" / "media"

ENGINES = {
    "local-base": {"stt_provider": "local"},
    "groq-v3": {"stt_provider": "groq", "groq_stt_model": "whisper-large-v3"},
    "groq-turbo": {"stt_provider": "groq", "groq_stt_model": "whisper-large-v3-turbo"},
    # the same engine, told to write maths in symbols (STT_PROMPT)
    "groq-turbo-hint": {"stt_provider": "groq", "groq_stt_model": "whisper-large-v3-turbo",
                        "stt_prompt": "A learner asks a maths question. Write the maths in symbols: "
                                      "3x + 4 = 19, x^2 - 5x + 6 = 0, 2/3 + 1/4, -8 + 3, 2(x - 1) = 10, x = -5."},
}
MIME = {".ogg": "audio/ogg", ".opus": "audio/ogg", ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
        ".wav": "audio/wav", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
# Production defaults (.env.example): GLM-5.3 Flash routes, GPT-6 Luna tutors
# at each call's own default reasoning effort.
LIVE = {"llm_provider": "openrouter", "reasoner_provider": "", "router_provider": "",
        "openrouter_router_model": "z-ai/glm-5.3-flash", "openrouter_reasoner_model": "openai/gpt-6-luna",
        # GLM-5.3 Flash cannot switch reasoning off: live, the app retries it at
        # "low" and remembers; under capture_calls that retry is disabled (the
        # bake-off must see refusals), so the router is set to "low" up front.
        "router_effort": "low", "reasoner_effort": "", "openrouter_provider": ""}
STUB = {"llm_provider": "stub", "reasoner_provider": "", "router_provider": ""}


@contextlib.contextmanager
def use(**values):
    """Point the app's settings at one configuration for a block."""
    saved = {k: getattr(settings, k) for k in values}
    try:
        for k, v in values.items():
            setattr(settings, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(settings, k, v)


def manifest(set_: str, kind: str) -> list[dict]:
    path = HERE / set_ / f"{kind}.jsonl"
    if not path.exists():
        sys.exit(f"{path} not found. See evals/bench/media/README.md.")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def rows(set_: str, name: str) -> list[dict]:
    path = RESULTS / set_ / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def append(set_: str, name: str, row: dict) -> None:
    path = RESULTS / set_ / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", buffering=1 << 20) as f:  # one write per row: parallel runs share the file
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _cost(calls: list[dict]) -> dict:
    app_calls = [c for c in calls if c.get("call")]
    return {
        "cost_usd": round(sum(c.get("cost_usd") or 0 for c in app_calls), 6),
        "input_tokens": sum(c.get("input_tokens", 0) for c in app_calls),
        "output_tokens": sum(c.get("output_tokens", 0) for c in app_calls),
        "reasoning_tokens": sum(c.get("reasoning_tokens", 0) for c in app_calls),
        "calls": [{k: c.get(k) for k in ("call", "served_model", "input_tokens", "output_tokens",
                                         "reasoning_tokens", "cached_tokens", "cost_usd", "latency_s",
                                         "finish_reason", "effort")} for c in app_calls],
    }


# ── stt: every clip through every wired engine, English forced and auto ──────

async def cmd_stt(args) -> None:
    clips = manifest(args.set, "voice")
    done = {(r["id"], r["engine"], r["lang"]) for r in rows(args.set, "stt")}
    for name in args.engines.split(","):
        for lang in args.langs.split(","):
            todo = [c for c in clips if (c["id"], name, lang) not in done]
            print(f"{name} / {lang}: {len(todo)} clips to do")
            for clip in todo:
                path = HERE / args.set / clip["file"]
                audio = path.read_bytes()
                with use(**{"stt_prompt": "", **ENGINES[name]}, stt_language=lang):
                    for attempt in range(6):
                        started = time.perf_counter()
                        try:
                            text, error = await stt.transcribe(audio, MIME[path.suffix.lower()]), None
                            break
                        except httpx.HTTPStatusError as exc:
                            text, error = "", f"{exc.response.status_code}: {exc.response.text[:200]}"
                            if exc.response.status_code != 429:
                                break
                            await asyncio.sleep(float(exc.response.headers.get("retry-after", 20)) + 1)
                append(args.set, "stt", {"id": clip["id"], "engine": name, "lang": lang, "transcript": text,
                                         "latency_s": round(time.perf_counter() - started, 3),
                                         "seconds": clip.get("seconds"), **({"error": error} if error else {})})
                if name.startswith("groq"):
                    await asyncio.sleep(3.1)  # free tier: 20 requests a minute


# ── voice: does a transcript land where the typed message lands? (stub) ──────

async def _learner(grade: int) -> tuple[int, int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        account = await conn.fetchval("INSERT INTO accounts DEFAULT VALUES RETURNING id")
        learner = await conn.fetchval(
            "INSERT INTO learners (account_id, nickname, grade) VALUES ($1, 'Bench', $2) RETURNING id",
            account, grade)
    return account, learner


async def _drop(account: int, learner: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM llm_calls WHERE learner_id = $1", learner)
        await conn.execute("DELETE FROM accounts WHERE id = $1", account)
    await memory.forget(learner)
    ledger.current_learner.set(None)


def _solved(text: str) -> str | None:
    s = answer_check.solve_problem(text)
    return f"{s['kind']}: {s.get('answer') or ', '.join(s['solutions'])}" if s else None


async def _land(clip: dict, text: str) -> dict:
    """Where one message lands in the tutor engine (stub model: the topic,
    the working problem and the code answer check never depend on the model)."""
    account, learner = await _learner(clip["grade"])
    try:
        if clip["role"] == "question":
            await engine.tutor_reply(text, clip["grade"], learner, "Bench")
            info = engine.last_turn.get() or {}
            return {"topic": (info.get("topic") or {}).get("name"), "code_sees": _solved(text),
                    "code_sees_if_normalised": _solved(score.spoken_to_maths(text)),
                    "code_sees_with_symbols": _solved(spoken.to_symbols(text))}
        await engine.tutor_reply(clip["problem"], clip["grade"], learner, "Bench")
        await engine.tutor_reply(text, clip["grade"], learner, "Bench")
        info = engine.last_turn.get() or {}
        norm = answer_check.check(clip["problem"], score.spoken_to_maths(text))
        wired = answer_check.check(clip["problem"], spoken.to_symbols(text))
        return {"continuing": bool(info.get("continuing")), "code_check": info.get("code_check"),
                "code_check_if_normalised": norm["verdict"] if norm else None,
                "code_check_with_symbols": wired["verdict"] if wired else None}
    finally:
        await _drop(account, learner)


async def cmd_voice(args) -> None:
    clips = {c["id"]: c for c in manifest(args.set, "voice")}
    done = {(r["id"], r["variant"]) for r in rows(args.set, "voice")}
    cache: dict = {}
    with use(**STUB):
        todo = [(c, "typed", c["typed"]) for c in clips.values()]
        todo += [(clips[r["id"]], f"{r['engine']}/{r['lang']}", r["transcript"])
                 for r in rows(args.set, "stt") if r["id"] in clips and not r.get("error")]
        for clip, variant, text in todo:
            if (clip["id"], variant) in done:
                continue
            key = (clip["role"], clip.get("problem"), clip["grade"], text)
            if key not in cache:
                cache[key] = await _land(clip, text)
            append(args.set, "voice", {"id": clip["id"], "variant": variant, "text": text,
                                       "maths_kept": score.maths_kept(clip["said"], text), **cache[key]})
    print(f"voice: {len(todo)} rows in {RESULTS / args.set / 'voice.jsonl'}")


# ── photos: per vision model, today's single reply and a read ────────────────

async def cmd_photos(args) -> None:
    photos = manifest(args.set, "photo")
    models = args.models.split(",")
    done = {(r["photo"], r["model"], r["kind"]) for r in rows(args.set, "photos") if not r.get("error")}
    todo = [(m, p, k) for m in models for p in photos for k in ("today", "read")
            if (p["id"], m, k) not in done and (not args.only or p["id"] in args.only.split(","))]
    print(f"photos: {len(todo)} vision calls over {len(models)} models (cap ${args.cap:.2f}).")
    if not args.yes:
        print("Not run. Re-run with --yes once this spend is approved.")
        return
    spent, sem, stop = 0.0, asyncio.Semaphore(args.concurrency), asyncio.Event()

    async def one(model, photo, kind):
        nonlocal spent
        async with sem:
            if stop.is_set():
                return
            path = HERE / args.set / photo["file"]
            image, mime = path.read_bytes(), MIME[path.suffix.lower()]
            row = {"photo": photo["id"], "type": photo["type"], "model": model, "kind": kind}
            started = time.perf_counter()
            with llm.capture_calls() as calls:
                try:
                    if kind == "today":
                        row["output"] = await llm.photo_reply(image, mime, photo.get("caption", ""), photo["grade"])
                        if photo.get("answers"):
                            row["leak"] = graders.leaks_answer(row["output"], photo["answers"])
                    else:
                        llm.last_photo_raw.set(None)
                        row["read"] = await llm.read_photo(image, mime, photo.get("caption", ""))
                        row["output"] = llm.last_photo_raw.get()
                        row["score"] = score.score_read(photo, row["read"])
                except Exception as exc:  # noqa: BLE001 -- a model that refuses is a result
                    row["error"] = repr(exc)[:400]
            row.update(_cost(calls), latency_s=round(time.perf_counter() - started, 3))
            append(args.set, "photos", row)
            spent += row["cost_usd"]
            if spent > args.cap:
                stop.set()

    for model in models:  # one model at a time: settings are process-wide
        with use(**LIVE, openrouter_vision_model=model):
            await asyncio.gather(*(one(m, p, k) for m, p, k in todo if m == model))
    print(f"photos: spent ${spent:.4f}{' (stopped at the cap)' if stop.is_set() else ''}")


# ── chats: whole conversations on the worker path ────────────────────────────

class Phone:
    """Stands in for WhatsApp: holds media, collects what Katlego sends."""

    def __init__(self):
        self.number = "2779" + "".join(random.choices("0123456789", k=7))
        self.sent: list[str] = []
        self.media: dict[str, tuple[bytes, str]] = {}

    async def send_text(self, to: str, body: str) -> dict:
        self.sent.append(body)
        return {}

    async def get_media(self, media_id: str) -> tuple[bytes, str]:
        return self.media[media_id]

    def attach(self, path: Path) -> str:
        self.media[path.name] = (path.read_bytes(), MIME[path.suffix.lower()])
        return path.name

    async def send(self, message: dict) -> dict:
        """One learner message through worker.process_job; what came back,
        what it cost and where the tutor engine thinks it is."""
        engine.last_turn.set(None)
        n, started = len(self.sent), time.perf_counter()
        out = {}
        with llm.capture_calls() as calls:
            try:
                await worker.process_job(self, {"from": self.number, "name": "Bench", "message": message})
            except Exception as exc:  # noqa: BLE001 -- the live worker would send "something went wrong"
                out["error"] = repr(exc)[:400]
        info = engine.last_turn.get() or {}
        return {**out, "reply": "\n".join(self.sent[n:]), "latency_s": round(time.perf_counter() - started, 3),
                "topic": (info.get("topic") or {}).get("name"), "problem": info.get("problem"),
                "continuing": info.get("continuing"), "code_check": info.get("code_check"),
                "ev": (info.get("state") or {}).get("ev"), "guard": info.get("leak_guard"), **_cost(calls)}

    async def text(self, body: str) -> dict:
        return {"sent": body, **await self.send({"type": "text", "text": {"body": body}})}

    async def onboard(self, grade: int) -> None:
        for body in ("hi", "AGREE", "Bench", str(grade), "PAUSE"):  # PAUSE: the sign-up check-in
            await self.text(body)

    async def finish(self) -> list[dict]:
        """Mastery evidence this chat wrote, then erase the household."""
        sess = await session.load(self.number)
        learner = sess.active_learner_id
        pool = await get_pool()
        async with pool.acquire() as conn:
            events = [dict(r) for r in await conn.fetch(
                "SELECT t.name AS topic, e.evidence, e.source FROM learner_events e "
                "JOIN topics t ON t.id = e.topic_id WHERE e.learner_id = $1 ORDER BY e.id", learner)]
            await conn.execute("DELETE FROM llm_calls WHERE learner_id = $1", learner)
        await memory.forget(learner)
        await session.delete_household(sess.account_id, self.number)
        ledger.current_learner.set(None)
        return events


# Voice notes sent through the whole worker in the paid run (the rest are
# covered for free by `voice`): one or two per category.
VOICE_CHATS = ("v01", "v05", "v08", "v12", "v14", "v16", "v19", "v20", "v33", "v35", "v37",
               "v23", "v24", "v27", "v29", "v31", "v39")


def _typed_photo(photo: dict) -> str:
    """The same page typed out by the learner (the text baseline)."""
    if photo["type"] == "working":
        return worker.photo_message({"problem": photo["problem"], "working": photo["lines"][1:]},
                                    photo.get("caption", "")).replace("{", "").replace("}", "")
    return "\n".join(filter(None, [photo["problem"], photo.get("caption", "")]))


async def _photo_chat(args, photo: dict, arm: str) -> dict:
    phone = Phone()
    path = HERE / args.set / photo["file"]
    turns = []
    await phone.onboard(photo["grade"])
    if arm == "typed":
        turns.append(await phone.text(_typed_photo(photo)))
    else:
        oracle = {"problem": photo["problem"],
                  "working": [x.replace("{", "").replace("}", "") for x in photo["lines"][1:]]
                  if photo["type"] == "working" else [], "values": photo.get("values", [])}
        real_read = llm.read_photo
        if args.stub:  # a perfect reader, so the engine can be checked without a model
            async def read_photo(*_a, **_k):
                return oracle
            llm.read_photo = read_photo
        try:
            with use(photo_pipeline=arm):
                msg = {"type": "image", "image": {"id": phone.attach(path), "mime_type": MIME[path.suffix.lower()],
                                                  "caption": photo.get("caption", "")}}
                turns.append({"sent": f"[photo {photo['id']}] {photo.get('caption', '')}".strip(),
                              **await phone.send(msg)})
        finally:
            llm.read_photo = real_read
    for body in photo.get("followups", []):
        turns.append(await phone.text(body))
    opened = turns[0]["problem"]
    answers = photo.get("answers") or []
    return {"flow": f"photo:{photo['id']}", "type": photo["type"], "arm": arm, "turns": turns,
            "events": await phone.finish(), "cost_usd": round(sum(t["cost_usd"] for t in turns), 6),
            "check": {
                "opened_problem": bool(opened),
                "stayed_on_problem": bool(opened) and all(t["problem"] in (opened, None) and t["continuing"]
                                                          for t in turns[1:]),
                "code_checked_followups": sum(bool(t["code_check"]) for t in turns[1:]),
                "followups": len(turns) - 1,
                "code_checked_working": bool(turns[0]["code_check"]),
                "leaked_answer": bool(answers) and any(graders.leaks_answer(t["reply"], answers)
                                                       for t in turns[:-1] or turns),
            }}


async def _voice_chat(args, clip: dict, arm: str) -> dict:
    phone = Phone()
    path = HERE / args.set / clip["file"]
    turns = []
    await phone.onboard(clip["grade"])
    if clip["role"] == "answer":
        turns.append(await phone.text(clip["problem"]))
    if arm == "typed":
        turns.append(await phone.text(clip["typed"]))
    else:
        msg = {"type": "audio", "audio": {"id": phone.attach(path), "mime_type": MIME[path.suffix.lower()],
                                          "voice": True}}
        turns.append({"sent": f"[voice {clip['id']}] {clip['said']}", **await phone.send(msg)})
    return {"flow": f"voice:{clip['id']}", "type": clip["role"], "arm": arm, "turns": turns,
            "events": await phone.finish(), "cost_usd": round(sum(t["cost_usd"] for t in turns), 6)}


async def cmd_chats(args) -> None:
    photos = manifest(args.set, "photo")
    clips = [c for c in manifest(args.set, "voice") if c["id"] in VOICE_CHATS or args.set != "synthetic"]
    name = ("chats_stub" if args.stub else "chats") + (f"_{args.tag}" if args.tag else "")
    done = {(r["flow"], r["arm"]) for r in rows(args.set, name) if not any(t.get("error") for t in r["turns"])}
    only = set(args.only.split(",")) if args.only else None
    todo = [("photo", p, arm) for p in photos for arm in ("typed", "single", "read")]
    todo += [("voice", c, arm) for c in clips for arm in ("typed", "voice")]
    todo = [(k, item, arm) for k, item, arm in todo
            if (f"{k}:{item['id']}", arm) not in done and (not only or item["id"] in only)]
    print(f"chats: {len(todo)} conversations ({'stub, free' if args.stub else f'paid, cap ${args.cap:.2f}'}).")
    if not args.stub and not args.yes:
        print("Not run. Re-run with --yes once this spend is approved.")
        return
    base = STUB if args.stub else {**LIVE, "openrouter_vision_model": args.vision}
    spent = 0.0
    with use(**base, **ENGINES[args.stt], stt_language=args.stt_lang):
        for kind, item, arm in todo:
            row = await (_photo_chat if kind == "photo" else _voice_chat)(args, item, arm)
            append(args.set, name, row)
            spent += row["cost_usd"]
            if spent > args.cap:
                print("Stopped at the cap.")
                break
    print(f"chats: spent ${spent:.4f}")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("stt", "voice", "photos", "chats"))
    ap.add_argument("--set", default="synthetic", help="folder under evals/bench/media (synthetic | real)")
    ap.add_argument("--engines", default="local-base,groq-turbo,groq-v3")
    ap.add_argument("--langs", default="en,auto")
    ap.add_argument("--models", default="openai/gpt-6-luna,anthropic/claude-haiku-5.5,"
                                        "openai/gpt-5.4-mini,z-ai/glm-5.3-flash")
    ap.add_argument("--vision", default="openai/gpt-6-luna", help="chats: the model that sees the photo")
    ap.add_argument("--stt", default="groq-turbo", choices=list(ENGINES), help="chats: the engine for voice notes")
    ap.add_argument("--stt-lang", default="en")
    ap.add_argument("--only", help="comma list of item ids")
    ap.add_argument("--tag", help="chats: write to chats_<tag>.jsonl (a repeat run)")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--cap", type=float, default=0.50, help="stop once this many dollars are spent in this run")
    ap.add_argument("--stub", action="store_true", help="chats: stub model and a perfect photo reader (free)")
    ap.add_argument("--yes", action="store_true", help="approve spending")
    args = ap.parse_args()
    await ensure_schema()
    await {"stt": cmd_stt, "voice": cmd_voice, "photos": cmd_photos, "chats": cmd_chats}[args.cmd](args)


if __name__ == "__main__":
    asyncio.run(main())
