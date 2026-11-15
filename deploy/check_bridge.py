"""Offline check of sqs_bridge.py with fake SQS and fake Redis (stdlib only).
Run: python deploy/check_bridge.py"""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from sqs_bridge import Bridge, to_meta_message, STREAM

class FakeRedis:
    def __init__(self, fail_xadd=False): self.kv, self.stream, self.fail = {}, [], fail_xadd
    def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv: return None
        self.kv[k] = v; return True
    def delete(self, k): self.kv.pop(k, None)
    def xadd(self, s, f):
        if self.fail: raise ConnectionError("redis down")
        self.stream.append((s, json.loads(f["payload"])))

class FakeSQS:
    def __init__(self, bodies): self.msgs = [{"Body": b, "ReceiptHandle": f"rh{i}"} for i, b in enumerate(bodies)]; self.deleted = []
    def receive_message(self, **kw): return {"Messages": list(self.msgs)}
    def delete_message(self, QueueUrl, ReceiptHandle): self.deleted.append(ReceiptHandle)

ok = fail = 0
def check(name, cond):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(("PASS " if cond else "FAIL ") + name)

raw = {"from": "27787738580", "id": "wamid.1", "timestamp": "1", "type": "image", "image": {"id": "M1", "caption": "Q3?"}}
new_item = json.dumps({"message_id": "wamid.1", "from": "27787738580", "profile_name": "Moeketsi", "type": "image", "media_id": "M1", "message": raw})
old_text = json.dumps({"message_id": "wamid.2", "from": "27787738580", "type": "text", "text": "hi"})
old_audio = json.dumps({"message_id": "wamid.3", "from": "27787738580", "type": "audio", "media_id": "A1"})
fake_sender = json.dumps({"message_id": "wamid.4", "from": "16315551181", "type": "text", "text": "this is a text message"})

r, s = FakeRedis(), FakeSQS([new_item, old_text, old_audio, new_item, fake_sender, "not json"])
b = Bridge(s, r, "q", ["+27787738580"])
n = b.poll_once(0)
check("all 6 deleted from SQS (queued, dup, filtered, bad JSON)", n == 6 and len(s.deleted) == 6)
check("3 jobs on the stream", len(r.stream) == 3 and all(x[0] == STREAM for x in r.stream))
j0 = r.stream[0][1]
check("raw Meta message passed through (image caption kept)", j0["message"] == raw and j0["name"] == "Moeketsi" and j0["from"] == "27787738580")
check("old text item rebuilt as Meta text", r.stream[1][1]["message"]["text"]["body"] == "hi")
check("old audio item rebuilt with media id", r.stream[2][1]["message"]["audio"]["id"] == "A1")
check("duplicate wamid dropped", sum(1 for x in r.stream if x[1]["message"]["id"] == "wamid.1") == 1)
check("fake dashboard sender filtered by ALLOW_FROM", not any(x[1]["from"] == "16315551181" for x in r.stream))

r2, s2 = FakeRedis(fail_xadd=True), FakeSQS([old_text])
n2 = Bridge(s2, r2, "q").poll_once(0)
check("redis down: message NOT deleted from SQS", n2 == 0 and s2.deleted == [])
check("redis down: dedupe key released for redelivery", "dedupe:wamid.2" not in r2.kv)
r2.fail = False
check("redelivery after redis recovers is queued", Bridge(s2, r2, "q").poll_once(0) == 1 and len(r2.stream) == 1)

r3 = FakeRedis(); Bridge(FakeSQS([]), r3, "q").handle(fake_sender)
class HalfRedis(FakeRedis):
    def xadd(self, s, f):
        if json.loads(f["payload"])["message"]["id"] == "wamid.2": raise ConnectionError("blip")
        super().xadd(s, f)
s4 = FakeSQS([old_text, old_audio]); [m.update(Attributes={"MessageGroupId": "27787738580"}) for m in s4.msgs]
r4 = HalfRedis(); Bridge(s4, r4, "q").poll_once(0)
check("FIFO: later message of the same learner held when an earlier one fails", s4.deleted == [] and r4.stream == [])
check("no ALLOW_FROM = everyone allowed", len(r3.stream) == 1)
print(f"\n{ok} passed, {fail} failed"); sys.exit(1 if fail else 0)
