"""Admin commands for the access gate (closed pilot + investor demo).

On the server:
    sudo bash deploy/access.sh <command> [options]
which runs:  python -m app.access_admin <command> [options]  in the worker image.

Commands
  issue        --kind pilot|demo --days N [--count K] [--max-uses M]
               [--label "who"] [--valid-days V] [--code CUSTOM]
  codes        [--all]                list codes (active only unless --all)
  grants                              numbers with access, newest first
  waitlist                            numbers that replied JOIN
  grant        --phone 0781234567 --days 30   give a number access directly
  revoke-code  CODE                   stop a code from being redeemed
  revoke-phone --phone 0781234567     end a number's access now
  purge-demo                          erase data of ended demo numbers
  remind       --within-days 3 --template NAME [--lang en] [--dry-run]
               send the approved "access ending" template to numbers whose
               access ends within N days (once per grant)

Phone numbers are printed masked (last 4 digits) except in `waitlist`/`grants`
with --full, which the founder needs to contact people.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys

import httpx

from app.config import settings
from app.orchestrator import access, session
from app.db import get_pool


def mask(p: str) -> str:
    return "*" * max(0, len(p) - 4) + p[-4:]


def show(p: str, full: bool) -> str:
    return p if full else mask(p)


async def cmd_issue(a) -> None:
    if a.code and a.count != 1:
        sys.exit("--code makes one code; leave out --count")
    rows = []
    pool = await get_pool()
    async with pool.acquire() as conn:
        for _ in range(a.count):
            code = a.code or access.new_code("TB" if a.kind == "pilot" else "DEMO")
            norm = access.normalize(code)
            if len(norm) < 6:
                sys.exit("A code needs at least 6 letters/digits so it can't appear in normal chat.")
            valid_until = None
            if a.valid_days:
                valid_until = await conn.fetchval(
                    "SELECT now() + make_interval(days => $1)", a.valid_days
                )
            await conn.execute(
                """INSERT INTO access_codes (code_norm, code, kind, label, days, max_uses, valid_until)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                norm, code, a.kind, a.label or "", a.days, a.max_uses, valid_until,
            )
            rows.append(code)
    print(f"Issued {len(rows)} {a.kind} code(s): {a.days} day(s) access each, "
          f"max {a.max_uses} use(s) per code, label '{a.label or ''}'"
          + (f", redeem within {a.valid_days} days" if a.valid_days else ""))
    for c in rows:
        print("  ", c)


async def cmd_codes(a) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM access_codes" + ("" if a.all else " WHERE active")
            + " ORDER BY created_at DESC"
        )
    print(f"{'code':18} {'kind':6} {'days':>4} {'used':>9}  {'redeem by':12} label")
    for r in rows:
        by = access.fmt_date(r["valid_until"]) if r["valid_until"] else "-"
        state = "" if r["active"] else "  (revoked)"
        print(f"{r['code']:18} {r['kind']:6} {r['days']:>4} {r['uses']:>4}/{r['max_uses']:<4}  "
              f"{by:12} {r['label']}{state}")


async def cmd_grants(a) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT g.*, c.code, c.label, now() AS now FROM access_grants g
               LEFT JOIN access_codes c USING (code_norm) ORDER BY g.granted_at DESC"""
        )
    for r in rows:
        status = "open" if r["access_until"] > r["now"] else "ended"
        print(f"{show(r['phone'], a.full):14} {r['kind']:6} {status:5} until "
              f"{access.fmt_date(r['access_until']):12} code {r['code'] or '-':16} {r['label'] or ''}")
    print(f"{len(rows)} number(s)")


async def cmd_waitlist(a) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT r.* FROM access_requests r
               LEFT JOIN access_grants g USING (phone)
               WHERE r.joined_at IS NOT NULL AND (g.phone IS NULL OR g.access_until < now())
               ORDER BY r.joined_at"""
        )
    for r in rows:
        print(f"{show(r['phone'], a.full):14} joined {access.fmt_date(r['joined_at'])}")
    print(f"{len(rows)} waiting")


async def cmd_grant(a) -> None:
    phone = access.normalize_phone(a.phone)
    pool = await get_pool()
    async with pool.acquire() as conn:
        until = await conn.fetchval(
            """INSERT INTO access_grants (phone, kind, access_until)
               VALUES ($1, 'manual', now() + make_interval(days => $2))
               ON CONFLICT (phone) DO UPDATE SET kind = 'manual', code_norm = NULL,
                   granted_at = now(), reminded_at = NULL,
                   access_until = greatest(access_grants.access_until, now())
                                  + make_interval(days => $2)
               RETURNING access_until""",
            phone, a.days,
        )
    print(f"{mask(phone)} has access until {access.fmt_date(until)}. "
          "They can say hi to Katlego now (send them the welcome template once it's approved).")


async def cmd_revoke_code(a) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        n = await conn.execute(
            "UPDATE access_codes SET active = false WHERE code_norm = $1", access.normalize(a.code)
        )
    print("Revoked." if n.endswith("1") else "No such code.")


async def cmd_revoke_phone(a) -> None:
    phone = access.normalize_phone(a.phone)
    pool = await get_pool()
    async with pool.acquire() as conn:
        n = await conn.execute(
            "UPDATE access_grants SET access_until = now() WHERE phone = $1", phone
        )
    print("Access ended." if n.endswith("1") else "That number has no access.")


async def cmd_purge_demo(a) -> None:
    """Erase everything for demo numbers whose demo period has ended (the
    promise in the demo consent message). Admin numbers are never touched."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT phone FROM access_grants WHERE kind = 'demo' AND access_until < now()"
        )
    admins = access.admin_phones()
    done = 0
    for r in rows:
        phone = r["phone"]
        if phone in admins:
            continue
        account_id = await session.account_for_phone(phone)
        await session.delete_household(account_id, phone)  # chats, account, learners, session
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM access_grants WHERE phone = $1", phone)
            await conn.execute("DELETE FROM access_requests WHERE phone = $1", phone)
        done += 1
    print(f"Erased {done} ended demo number(s).")


async def cmd_remind(a) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT phone, access_until FROM access_grants
               WHERE kind IN ('pilot', 'manual') AND reminded_at IS NULL
                 AND access_until > now()
                 AND access_until < now() + make_interval(days => $1)""",
            a.within_days,
        )
    url = f"{settings.graph_api_base_url}/v25.0/{settings.whatsapp_phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    sent = 0
    async with httpx.AsyncClient(timeout=30) as client:
        for r in rows:
            body = {
                "messaging_product": "whatsapp",
                "to": r["phone"],
                "type": "template",
                "template": {
                    "name": a.template,
                    "language": {"code": a.lang},
                    "components": [{
                        "type": "body",
                        "parameters": [{"type": "text", "text": access.fmt_date(r["access_until"])}],
                    }],
                },
            }
            if a.dry_run:
                print(f"would remind {mask(r['phone'])} (ends {access.fmt_date(r['access_until'])})")
                continue
            resp = await client.post(url, json=body, headers=headers)
            if resp.status_code >= 400:
                print(f"FAILED {mask(r['phone'])}: {resp.text[:200]}")
                continue
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE access_grants SET reminded_at = now() WHERE phone = $1", r["phone"]
                )
            sent += 1
    print(f"{len(rows)} due, {sent} sent" + (" (dry run)" if a.dry_run else ""))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="access_admin", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("issue")
    s.add_argument("--kind", choices=["pilot", "demo"], required=True)
    s.add_argument("--days", type=int, required=True, help="access length after redeeming")
    s.add_argument("--count", type=int, default=1)
    s.add_argument("--max-uses", type=int, default=1)
    s.add_argument("--label", default="")
    s.add_argument("--valid-days", type=int, help="code must be redeemed within N days")
    s.add_argument("--code", help="custom code text, e.g. KATLEGO-DEMO-26")
    s = sub.add_parser("codes"); s.add_argument("--all", action="store_true")
    s = sub.add_parser("grants"); s.add_argument("--full", action="store_true")
    s = sub.add_parser("waitlist"); s.add_argument("--full", action="store_true")
    s = sub.add_parser("grant"); s.add_argument("--phone", required=True); s.add_argument("--days", type=int, required=True)
    s = sub.add_parser("revoke-code"); s.add_argument("code")
    s = sub.add_parser("revoke-phone"); s.add_argument("--phone", required=True)
    sub.add_parser("purge-demo")
    s = sub.add_parser("remind")
    s.add_argument("--within-days", type=int, default=3)
    s.add_argument("--template", required=True)
    s.add_argument("--lang", default="en")
    s.add_argument("--dry-run", action="store_true")
    return p


COMMANDS = {
    "issue": cmd_issue, "codes": cmd_codes, "grants": cmd_grants, "waitlist": cmd_waitlist,
    "grant": cmd_grant, "revoke-code": cmd_revoke_code, "revoke-phone": cmd_revoke_phone,
    "purge-demo": cmd_purge_demo, "remind": cmd_remind,
}


async def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    await access.ensure_schema()
    try:
        await COMMANDS[a.cmd](a)
    finally:
        import app.db as db
        if db._pool is not None:
            await db._pool.close()
            db._pool = None


if __name__ == "__main__":
    asyncio.run(main())
