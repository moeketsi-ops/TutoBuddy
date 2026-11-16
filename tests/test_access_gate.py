"""Access gate (closed pilot codes + investor demo code) against a real Postgres.

Runs with the app's DATABASE_URL:  pytest -q tests/test_access_gate.py
No WhatsApp, Redis or LLM needed. Uses its own phone numbers (2799900xxxx)
and codes (TEST-...) and removes them afterwards.
"""
import asyncio
import os

import pytest

from app.orchestrator import access

P = "27999000"  # test phone prefix


def run(coro_factory):
    import app.db as db

    async def go():
        db._pool = None
        access._schema_ready = False
        try:
            await access.ensure_schema()
            return await coro_factory()
        finally:
            if db._pool is not None:
                await db._pool.close()
            db._pool = None
    return asyncio.run(go())


async def sql(q, *args):
    from app.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as c:
        return await c.fetch(q, *args)


async def cleanup():
    await sql("DELETE FROM access_grants WHERE phone LIKE $1", P + "%")
    await sql("DELETE FROM access_requests WHERE phone LIKE $1", P + "%")
    await sql("DELETE FROM access_codes WHERE code LIKE 'TEST-%'")


async def add_code(code, kind="pilot", days=30, max_uses=1, valid_until_sql="NULL"):
    await sql(
        f"""INSERT INTO access_codes (code_norm, code, kind, days, max_uses, valid_until)
            VALUES ($1, $2, $3, $4, $5, {valid_until_sql})""",
        access.normalize(code), code, kind, days, max_uses,
    )


@pytest.fixture(autouse=True)
def gate_on(monkeypatch):
    monkeypatch.setenv("ACCESS_GATE", "on")
    monkeypatch.setenv("ACCESS_ADMIN_PHONES", "0787738580")
    run(cleanup)
    yield
    run(cleanup)


def test_unit_helpers():
    assert access.normalize("tb-7kq4 m2xp") == "TB7KQ4M2XP"
    assert access.normalize_phone("078 773 8580") == "27787738580"
    assert access.normalize_phone("+27 78 773 8580") == "27787738580"
    assert access.looks_like_code("TB-7KQ4-M2XP")
    assert access.looks_like_code("tb 7kq4 m2xp")
    assert not access.looks_like_code("2x+5=13")
    assert not access.looks_like_code("hello")
    assert not access.looks_like_code("how do I solve 2x plus 5 equals 13")
    c = access.new_code()
    assert c.startswith("TB-") and len(access.normalize(c)) == 10
    assert not set(access.normalize(c)[2:]) & set("01OIL")


def test_gate_off_lets_everyone_through(monkeypatch):
    monkeypatch.setenv("ACCESS_GATE", "off")
    g = run(lambda: access.check(P + "0001", "hi"))
    assert g.allowed and g.reply is None


def test_admin_number_always_passes():
    g = run(lambda: access.check("27787738580", "hi"))
    assert g.allowed and g.kind == "admin"


def test_stranger_gets_welcome_and_join_works():
    g = run(lambda: access.check(P + "0002", "hi"))
    assert not g.allowed and "access code" in g.reply and "JOIN" in g.reply
    g = run(lambda: access.check(P + "0002", "join"))
    assert not g.allowed and "waiting list" in g.reply
    rows = run(lambda: sql("SELECT joined_at FROM access_requests WHERE phone=$1", P + "0002"))
    assert rows[0]["joined_at"] is not None


def test_pilot_code_in_a_sentence_grants_access_once():
    async def flow():
        await add_code("TEST-PIL1-AAAA", days=30)
        g1 = await access.check(P + "0003", "Hi Katlego, my code is test pil1 aaaa")
        g2 = await access.check(P + "0003", "how do I solve 2x+5=13?")
        g3 = await access.check(P + "0004", "TEST-PIL1-AAAA")   # single use: someone else
        return g1, g2, g3
    g1, g2, g3 = run(flow)
    assert g1.allowed and g1.just_granted and g1.kind == "pilot" and "Code accepted" in g1.reply
    assert g2.allowed and not g2.just_granted and g2.reply is None
    assert not g3.allowed and "used" in g3.reply


def test_same_code_again_is_not_a_second_use():
    async def flow():
        await add_code("TEST-DEM1-AAAA", kind="demo", days=7, max_uses=5)
        await access.check(P + "0005", "TEST-DEM1-AAAA")
        g = await access.check(P + "0005", "TEST-DEM1-AAAA")
        uses = (await sql("SELECT uses FROM access_codes WHERE code='TEST-DEM1-AAAA'"))[0]["uses"]
        return g, uses
    g, uses = run(flow)
    assert g.allowed and "already open" in g.reply and uses == 1


def test_demo_code_is_multi_use_and_marked_demo():
    async def flow():
        await add_code("TEST-DEM2-AAAA", kind="demo", days=7, max_uses=2)
        a = await access.check(P + "0006", "TEST DEM2 AAAA")
        b = await access.check(P + "0007", "test-dem2-aaaa")
        c = await access.check(P + "0008", "TEST-DEM2-AAAA")
        return a, b, c
    a, b, c = run(flow)
    assert a.allowed and a.kind == "demo" and "Demo code accepted" in a.reply
    assert b.allowed and b.kind == "demo"
    assert not c.allowed


def test_expired_code_and_ended_access():
    async def flow():
        await add_code("TEST-OLD1-AAAA", valid_until_sql="now() - interval '1 day'")
        e = await access.check(P + "0009", "TEST-OLD1-AAAA")
        await sql("""INSERT INTO access_grants (phone, kind, access_until)
                     VALUES ($1, 'pilot', now() - interval '2 days')""", P + "0010")
        ended = await access.check(P + "0010", "hello again")
        await add_code("TEST-NEW1-AAAA", days=10)
        renewed = await access.check(P + "0010", "TEST-NEW1-AAAA")
        after = await access.check(P + "0010", "hi")
        return e, ended, renewed, after
    e, ended, renewed, after = run(flow)
    assert not e.allowed and "expired" in e.reply
    assert not ended.allowed and "ended" in ended.reply and "progress is saved" in ended.reply
    assert renewed.allowed and renewed.just_granted
    assert after.allowed


def test_renewal_extends_from_current_end():
    async def flow():
        await add_code("TEST-EXT1-AAAA", days=30)
        await add_code("TEST-EXT2-AAAA", days=30)
        await access.check(P + "0011", "TEST-EXT1-AAAA")
        await access.check(P + "0011", "TEST-EXT2-AAAA")
        return await sql("SELECT access_until - now() AS left FROM access_grants WHERE phone=$1", P + "0011")
    left = run(flow)[0]["left"]
    assert left.days >= 59


def test_wrong_codes_are_throttled():
    async def flow():
        await add_code("TEST-GOOD-AAAA")
        replies = [await access.check(P + "0012", f"ZZ{i}9-QQQQ") for i in range(access.MAX_FAILED_PER_DAY)]
        blocked = await access.check(P + "0012", "TEST-GOOD-AAAA")  # even a good code waits
        return replies, blocked
    replies, blocked = run(flow)
    assert all("don't recognise" in r.reply for r in replies)
    assert not blocked.allowed and "tomorrow" in blocked.reply


def test_delete_removes_waitlist_entry():
    async def flow():
        await access.check(P + "0013", "JOIN")
        g = await access.check(P + "0013", "delete")
        rows = await sql("SELECT 1 FROM access_requests WHERE phone=$1", P + "0013")
        return g, rows
    g, rows = run(flow)
    assert not g.allowed and "off the TutoBuddy waiting list" in g.reply and rows == []


def test_maths_message_from_stranger_is_not_treated_as_a_code():
    g = run(lambda: access.check(P + "0014", "Solve x^2 - 5x + 6 = 0"))
    assert not g.allowed and g.reply == access.GATE_MESSAGE
