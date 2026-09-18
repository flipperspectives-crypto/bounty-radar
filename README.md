# Bounty Radar

Discovers new agent-eligible bounties on Superteam Earn, deduplicates them,
enriches them with listing details, and delivers structured alerts — plus an
A2A (Agent-to-Agent) v0.3 server that serves the same data to other agents.

Standard library only. No third-party dependencies.

## Components

| File | Purpose |
|---|---|
| `db.py` | Shared persistence, safe migrations, durable 6-state delivery engine, crash recovery, and secret redaction |
| `radar.py` | Poller: fetch → filter AGENT_ALLOWED → dedup → Discord/Telegram alert with backoff and delivery tracking |
| `a2a_server.py` | A2A v0.3 JSON-RPC server (Agent Card + 3 skills) on port 8080 |
| `enrich.py` | Listing detail enrichment with SSRF defense and honest evidence handling |
| `AGENT_INTEGRATION.md` | How another agent consumes the feed |
| `.well-known/agent-card.json` | A2A Agent Card specification |
| `pumpfun.py` | Pump.fun GO parser: SSR hydration stream extraction, criteria tagging, and escrow validation |
| `market_sentinel.py` | Market Sentinel: Real-time SOL spot price & RSI entry zone alerts dispatched to Discord |
| `bands_compare/` | Separate DLMM/pool-analysis lane: opportunity score, HOLD-first action policy, hard guards, Mr Bands comparator. Research-only (no signing, no live funds). Weights are an independent baseline, not private coefficients. |
| `test_pumpfun.py` | Offline unit tests for Pump.fun GO parsing, validation, and classification |
| `test_market_sentinel.py` | Offline unit tests for Market Sentinel price polling and entry zone detection |
| `tests/test_*bands*` | Offline tests for the DLMM comparator lane |
| `test_radar.py` | Offline tests for delivery lifecycle, migration, and poller |
| `test_a2a_server.py` | Offline tests for A2A routing, JSON-RPC errors, skills, and SSRF defense |
| `test_integration_pipeline.py` | End-to-end integration flow test |
| `DEPLOYMENT.md` | Production Google Cloud Run HTTPS deployment guide |

## Environment variables

| Variable | Used by | Required | Default |
|---|---|---|---|
| `RADAR_CHANNEL` | radar.py | no | `telegram` (`discord` or `telegram`) |
| `DISCORD_WEBHOOK_URL` | radar.py | if discord | — |
| `TELEGRAM_BOT_TOKEN` | radar.py | if telegram | — |
| `TELEGRAM_CHAT_ID` | radar.py | if telegram | — |
| `RADAR_DB` | both | no | `radar.db` |
| `RADAR_INTERVAL_SEC` | radar.py | no | `3600` |
| `A2A_PORT` | a2a_server.py | no | `8080` |
| `A2A_PUBLIC_URL` | a2a_server.py | no | `http://localhost:8080/a2a` |

Copy `.env.example` and fill in real values. Never commit `.env.local`.

## Run the poller (one-shot)

WINDOWS POWERSHELL
```powershell
python .\radar.py --once
```

LINUX
```bash
python3 ./radar.py --once
```

## Run unified server (A2A JSON-RPC + Background Discovery Poller)

WINDOWS POWERSHELL
```powershell
.\start-radar.ps1
# or: python .\a2a_server.py
```

LINUX
```bash
python3 ./a2a_server.py
```
*(By default, `a2a_server.py` runs both the A2A HTTP JSON-RPC server on port 8080 and an embedded background poller thread that checks Superteam Earn every hour and delivers notifications to Discord/Telegram. Set `RADAR_AUTO_POLL=0` to disable the embedded poller).*

### Run poller standalone (optional)

```powershell
python .\radar.py
```


Verify:
```powershell
curl.exe http://localhost:8080/health
curl.exe http://localhost:8080/.well-known/agent-card.json
curl.exe http://localhost:8080/a2a
```

Example A2A call (feed subscription):
```powershell
$body = '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","parts":[{"kind":"text","text":"show new opportunities from the feed"}],"kind":"message","messageId":"m1"}}}'
Invoke-RestMethod -Uri http://localhost:8080/a2a -Method Post -Body $body -ContentType "application/json"
```

## Run tests

Run the complete offline test suite (no live network calls):
```powershell
python -m unittest discover -v
```

DLMM / Mr Bands comparator simulation (no real funds, no signatures):
```bash
python3 -m bands_compare --baseline --sensitivity
# or: node battle_test_real_money.mjs
```
Reports land in `reports/bands_comparison_baseline.md`, `reports/bands_comparison_baseline.json`, and `reports/weight_sensitivity.csv`.

## Docker

```bash
docker build -t bounty-radar .
docker run --rm -p 8080:8080 \
  -e RADAR_CHANNEL=discord \
  -e DISCORD_WEBHOOK_URL="<webhook>" \
  -v bounty_radar_data:/data \
  bounty-radar
```

## Production HTTPS Deployment (Google Cloud Run)

See [DEPLOYMENT.md](DEPLOYMENT.md) for full instructions on Artifact Registry, Secret Manager, Cloud Storage FUSE persistent mounts, and Cloud Run deployment.

## Safety model

The service is read-only with respect to bounty sources. It never performs,
submits, funds, signs, or accepts bounties. All remote content (Superteam API,
listing pages, evaluator responses) is treated as untrusted external data.
Tokens, webhook URLs, and credentials are automatically redacted from error logs.
