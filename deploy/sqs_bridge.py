"""SQS -> Redis bridge for the Katlego server (AWS Step B).

The Lambda webhook checks Meta's signature and puts each learner message on
the SQS FIFO queue katlego-inbound.fifo. This bridge long-polls that queue and
hands every message to the Katlego worker the same way the gateway does
(app/main.py): Redis dedupe on the WhatsApp message id, then XADD a job
{"from", "name", "message"} to the stream katlego:inbound. Only then is the
message deleted from SQS. If Redis is down nothing is deleted, so SQS
redelivers after the visibility timeout (120 s) and no learner message is lost.

Env:
  SQS_QUEUE_URL   https://sqs.eu-west-1.amazonaws.com/<account>/katlego-inbound.fifo
  AWS_REGION      eu-west-1
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY  (IAM user katlego-worker, queue-only)
  REDIS_URL       redis://redis:6379/0
  ALLOW_FROM      optional, comma-separated wa_ids (e.g. 27787738580). While set,
                  messages from any other number are logged (masked) and dropped.
                  Use it during testing; leave it empty at launch.
"""

import json
import logging
import os
import signal
import time

STREAM = "katlego:inbound"            # same as app/queue.py
DEDUPE_TTL_SECONDS = 7 * 24 * 3600    # same as app/main.py

log = logging.getLogger("sqs-bridge")


def mask(n) -> str:
    """Learners are minors: never log full phone numbers (POPIA)."""
    s = str(n or "")
    return "****" if len(s) <= 4 else "*" * (len(s) - 4) + s[-4:]


def to_meta_message(item: dict) -> dict:
    """Return the raw Meta message object the worker expects.

    New Lambda versions send it as item["message"]. Older items only carry the
    flattened fields, so rebuild the parts the worker reads (text body, media id).
    """
    if isinstance(item.get("message"), dict):
        return item["message"]
    kind = item.get("type") or "text"
    msg = {
        "from": item.get("from", ""),
        "id": item.get("message_id", ""),
        "timestamp": item.get("timestamp"),
        "type": kind,
    }
    if kind == "text":
        msg["text"] = {"body": item.get("text") or ""}
    elif kind == "interactive":
        msg["interactive"] = item.get("interactive") or {}
    elif item.get("media_id"):
        msg[kind] = {"id": item["media_id"]}
    return msg


class Bridge:
    def __init__(self, sqs, redis, queue_url: str, allow_from=None):
        self.sqs = sqs
        self.r = redis
        self.queue_url = queue_url
        self.allow = {a.strip().lstrip("+") for a in (allow_from or []) if a.strip()}

    def handle(self, body: str) -> str:
        """Process one SQS body. Returns what happened. Raises if Redis fails
        (the caller then leaves the message on the queue for redelivery)."""
        try:
            item = json.loads(body)
        except (TypeError, ValueError):
            log.warning("dropping message that is not JSON")
            return "bad-json"
        msg = to_meta_message(item)
        sender = msg.get("from") or item.get("from") or ""
        msg_id = msg.get("id") or item.get("message_id") or ""
        if not sender:
            log.warning("dropping message %s with no sender", msg_id)
            return "no-sender"
        if self.allow and sender not in self.allow:
            log.info("not on ALLOW_FROM, dropped: %s from %s", msg_id, mask(sender))
            return "not-allowed"
        key = f"dedupe:{msg_id}"
        if msg_id and not self.r.set(key, 1, nx=True, ex=DEDUPE_TTL_SECONDS):
            log.info("duplicate dropped: %s", msg_id)
            return "duplicate"
        job = {"from": sender, "name": item.get("profile_name") or "", "message": msg}
        try:
            self.r.xadd(STREAM, {"payload": json.dumps(job)})
        except Exception:
            if msg_id:
                try:
                    self.r.delete(key)  # let the redelivery through
                except Exception:
                    pass
            raise
        log.info("queued for worker: %s from %s (%s)", msg_id, mask(sender), msg.get("type"))
        return "queued"

    def poll_once(self, wait_seconds: int = 20) -> int:
        resp = self.sqs.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=wait_seconds,
            MessageSystemAttributeNames=["MessageGroupId"],
        )
        done = 0
        held = set()  # learners whose earlier message failed: keep their order
        for m in resp.get("Messages", []):
            group = (m.get("Attributes") or {}).get("MessageGroupId")
            if group and group in held:
                continue
            try:
                self.handle(m.get("Body", ""))
            except Exception:
                # FIFO: leave it (and the rest of this learner's group) for redelivery.
                log.exception("redis hand-off failed; message stays on SQS")
                if group:
                    held.add(group)
                continue
            self.sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=m["ReceiptHandle"])
            done += 1
        return done


def main() -> None:
    import boto3
    import redis

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    queue_url = os.environ["SQS_QUEUE_URL"]
    sqs = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    allow = os.environ.get("ALLOW_FROM", "").split(",")
    bridge = Bridge(sqs, r, queue_url, allow)
    log.info("bridge up: %s -> %s%s", queue_url.rsplit("/", 1)[-1], STREAM,
             f" (ALLOW_FROM: {len(bridge.allow)} number(s))" if bridge.allow else "")

    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    while not stop["now"]:
        try:
            bridge.poll_once()
        except Exception:
            log.exception("SQS poll failed; retrying in 5 s")
            time.sleep(5)
    log.info("bridge stopped")


if __name__ == "__main__":
    main()
