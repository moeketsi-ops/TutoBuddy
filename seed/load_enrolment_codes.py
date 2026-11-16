"""School route: one sign-up code per returned consent slip.

The school sends home the slip (seed/school/consent_slip.md), collects the
signed copies and keeps them. This loader reads the class list and issues a
code for every learner whose slip came back; the learner sends that code to
Katlego in place of a typed AGREE (app/orchestrator/consent.py). See
docs/guardian-consent-findings.md.

    docker compose run --rm -T seed python -m seed.load_enrolment_codes \
        --school "Example High" --slip seed/school/approved_slip.md \
        < class_list.csv > codes.csv

--slip is the exact wording the parents signed. It is stored as the record of
what they agreed to, so the draft slip is refused.

class_list.csv has a header and two columns: learner_ref (the school's own
reference, such as a class-list number; not a name) and signed_on (the date
on the slip, YYYY-MM-DD; blank when the slip has not come back, and then no
code is issued). Safe to run again: a learner who already has a code keeps it.
"""

import argparse
import asyncio
import csv
import hashlib
import sys
from datetime import date
from pathlib import Path

from app.db import get_pool
from app.tutor.papers import new_code


async def load(rows: list[dict], school: str, slip_text: str) -> list[tuple[str, str]]:
    """Returns (learner_ref, code) for every learner with a signed slip."""
    version = hashlib.sha256(slip_text.encode()).hexdigest()[:12]
    out = []
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO consent_notices (version, body) VALUES ($1, $2) "
            "ON CONFLICT DO NOTHING", version, slip_text)
        for row in rows:
            ref, signed = row["learner_ref"].strip(), (row.get("signed_on") or "").strip()
            if not ref or not signed:
                continue
            code = await conn.fetchval(
                "SELECT code FROM enrolment_codes WHERE school = $1 AND learner_ref = $2",
                school, ref)
            while code is None:  # retry only on the rare code collision
                code = await conn.fetchval(
                    "INSERT INTO enrolment_codes (code, school, learner_ref, slip_version, signed_on) "
                    "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (code) DO NOTHING RETURNING code",
                    f"SCH-{new_code()}", school, ref, version, date.fromisoformat(signed))
            out.append((ref, code))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--school", required=True)
    ap.add_argument("--slip", type=Path, required=True, help="the slip wording parents signed")
    args = ap.parse_args()
    slip_text = args.slip.read_text()
    if "DRAFT" in slip_text:
        sys.exit(f"{args.slip} is still marked DRAFT: load the wording parents actually signed.")
    rows = list(csv.DictReader(sys.stdin))
    issued = asyncio.run(load(rows, args.school, slip_text))
    writer = csv.writer(sys.stdout)
    writer.writerow(["learner_ref", "code"])
    writer.writerows(issued)
    print(f"{len(issued)} codes for {args.school} ({len(rows) - len(issued)} learners "
          "without a signed slip got none)", file=sys.stderr)


if __name__ == "__main__":
    main()
