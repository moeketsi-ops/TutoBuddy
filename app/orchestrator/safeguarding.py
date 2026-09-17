"""Safeguarding -- child-safety architecture layer 4 (technical-blueprint-
reconciliation.md's 4-layer model): the AI is never the final authority on
a risk-flagged case. Every flag from app.orchestrator.safety is persisted
here (survives a POPIA deletion request -- see the comment on
safeguarding_flags in app/db.py) and pushed to a real human over WhatsApp.

This is intentionally the simplest thing that gets a flagged case in front
of a person today: one alert number (settings.safeguarding_alert_phone),
no review dashboard, no assignment/escalation workflow, no SLA tracking.
That's a real gap once there's more than one person handling this or more
than a handful of flags a week -- worth revisiting before this is anything
but a solo-founder POC.
"""

import logging

from app.adapters.whatsapp import WhatsAppClient
from app.config import settings
from app.db import get_pool

log = logging.getLogger("katlego.safeguarding")

_EXCERPT_MAX = 500

ALERT_TEMPLATE = (
    "🚨 *Safeguarding flag* — category: {category}\n"
    "Learner: {phone}\n"
    "Message: \"{excerpt}\"\n\n"
    "This was already shown the referral message (Childline 116 / SADAG / "
    "10111). Please follow up as needed."
)


async def record_and_notify(
    wa: WhatsAppClient, phone: str, category: str, message: str
) -> int:
    """Persists the flag (status='open') and, if an alert number is
    configured, sends it a WhatsApp alert immediately. Returns the new
    safeguarding_flags row id. Never raises on the notify step -- a failed
    alert must not crash message processing or hide the fact that a
    referral message was already sent to the learner; it's logged at
    CRITICAL instead so it's impossible to miss in the logs."""
    excerpt = message.strip()[:_EXCERPT_MAX]

    pool = await get_pool()
    async with pool.acquire() as conn:
        flag_id = await conn.fetchval(
            """
            INSERT INTO safeguarding_flags (phone, category, message_excerpt)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            phone,
            category,
            excerpt,
        )

    if not settings.is_set(settings.safeguarding_alert_phone):
        log.critical(
            "safeguarding flag #%s (%s) from %s -- NO safeguarding_alert_phone "
            "configured, nobody was notified. Set SAFEGUARDING_ALERT_PHONE in "
            ".env.",
            flag_id,
            category,
            phone,
        )
        return flag_id

    alert = ALERT_TEMPLATE.format(category=category, phone=phone, excerpt=excerpt)
    try:
        await wa.send_text(settings.safeguarding_alert_phone, alert)
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE safeguarding_flags SET notified_at = now() WHERE id = $1",
                flag_id,
            )
    except Exception:
        log.critical(
            "safeguarding flag #%s (%s) from %s -- ALERT FAILED TO SEND. "
            "Check safeguarding_flags directly.",
            flag_id,
            category,
            phone,
            exc_info=True,
        )

    return flag_id
