# Katlego server deploy (AWS Step B)

Learner WhatsApp -> Meta -> Lambda (signature check) -> SQS FIFO -> **bridge** -> Redis stream
`katlego:inbound` -> **worker** (existing Katlego pipeline) -> Graph API reply.

The server needs no open web ports: the bridge pulls from SQS. Firewall stays SSH-only.

| File | What it does |
|---|---|
| `sqs_bridge.py` + `Dockerfile.bridge` | Long-polls SQS, same dedupe + job shape as `app/main.py`, deletes only after the Redis hand-off. `ALLOW_FROM` limits testing to named numbers. |
| `check_bridge.py` | Offline test (stdlib only): `python deploy/check_bridge.py` |
| `docker-compose.server.yml` | db, redis, worker, bridge (+ seed). Memory caps 512 / 192 / 768 / 128 MB; Postgres shared_buffers 256 MB; Redis 128 MB noeviction + AOF. |
| `server.env` | Non-secret settings (phone number ID, real Graph API, models, queue URL). |
| `set-secrets.sh` | Run on the server. Hidden prompts for the WhatsApp token, OpenRouter key, optional Groq key and safeguarding number. Writes `/opt/katlego/secrets.env` + `db.env` (600). |
| `cloudshell-worker-key.sh` | Run in CloudShell. IAM user `katlego-worker` (queue-only) + key written to `/opt/katlego/aws.env` over SSH, never displayed. |
| `up.sh` | Build, seed once, start, show status and memory. |

## First deploy
1. CloudShell: `bash cloudshell-worker-key.sh`
2. Code on the server at `/opt/katlego/app`
3. Server (Lightsail browser SSH): `cd /opt/katlego/app && sudo bash deploy/set-secrets.sh`
4. Server: `sudo bash deploy/up.sh`
5. WhatsApp "hi" to +27 76 052 7446 from an `ALLOW_FROM` number, laptop off.

## Day to day
- Logs: `sudo docker compose -f deploy/docker-compose.server.yml logs -f --tail 50 bridge worker`
- Update code: refresh `/opt/katlego/app`, then `sudo bash deploy/up.sh`
- Launch to all learners: empty `ALLOW_FROM=` in `server.env`, then `up.sh`
