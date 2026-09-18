"""ONE-OFF, DESTRUCTIVE migration: old phone-keyed `learners` -> the new
household account model (accounts / account_channels / guardians / learners
/ guardian_learner -- see tutobuddy-household-account-model-phase1-plan.md).

Run exactly once, after pulling the code that redesigns app/db.py's SCHEMA:

    docker compose run --rm seed python -m seed.migrate_to_household_accounts

WHY THIS IS A SEPARATE SCRIPT, NOT PART OF ensure_schema(): the new
`learners` table has a different shape (id-keyed, no `phone` column) than
the old one (phone text PRIMARY KEY). `CREATE TABLE IF NOT EXISTS` is a
no-op against an existing table regardless of column mismatch -- putting a
DROP TABLE inside app/db.py's SCHEMA string (which ensure_schema() runs on
EVERY service boot) would silently wipe learners/mastery/attempts on every
single restart, forever. That must never happen, so the drop lives here,
in a script a human runs deliberately, once.

THIS WIPES existing learner/mastery/attempt data. Fine for a pre-launch
POC's local dev database (which is all this has run against so far) --
NOT a pattern to repeat once there's real user data anywhere. There is no
data-preserving path here on purpose: there was nothing worth preserving
(everything so far is test data from this session's own manual testing),
and building a real backfill (mapping each old phone-keyed learner row to
a new account+guardian+learner triple) for data that doesn't need it would
be wasted effort. If that's ever wrong for a given environment, STOP and
write a real backfill instead of running this.
"""

import asyncio

import asyncpg

from app.config import settings
from app.db import ensure_schema


async def main() -> None:
    # Deliberately NOT get_pool(): get_pool() calls ensure_schema() before
    # handing back a connection, and ensure_schema() runs the FULL new
    # schema -- including statements like
    # `CREATE INDEX IF NOT EXISTS idx_learners_account ON learners(account_id)`
    # -- against whatever `learners` currently is. Against the OLD
    # phone-keyed table (no `account_id` column) that blows up with
    # `UndefinedColumnError: column "account_id" does not exist` before
    # this script ever reaches its own DROP TABLE lines below. Connect
    # directly instead, so the drop happens BEFORE any schema check.
    conn = await asyncpg.connect(settings.database_url)
    try:
        async with conn.transaction():
            await conn.execute("DROP TABLE IF EXISTS learner_assessment_attempts CASCADE")
            await conn.execute("DROP TABLE IF EXISTS learner_topic_mastery CASCADE")
            await conn.execute("DROP TABLE IF EXISTS learners CASCADE")
    finally:
        await conn.close()
    print(
        "Dropped the old phone-keyed learners/learner_topic_mastery/"
        "learner_assessment_attempts tables. Recreating in the new "
        "household-account shape..."
    )
    await ensure_schema()
    print(
        "Done. accounts / account_channels / guardians / learners / "
        "guardian_learner / learner_topic_mastery / learner_assessment_attempts "
        "now exist in the new shape. All previous learner/mastery/consent "
        "test data is gone -- expected for this migration."
    )


if __name__ == "__main__":
    asyncio.run(main())
