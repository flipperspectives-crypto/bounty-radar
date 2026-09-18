import argparse
import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import db


def _load_env() -> None:
    """Load key-value pairs from .env.local or .env if present in current directory."""
    for filename in (".env.local", ".env"):
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("\"'")
                        if k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass


_load_env()

import pumpfun
import market_sentinel

SOURCES = {
    "superteam-earn": "https://superteam.fun/api/listings?type=bounty&filter=agents",
    "pumpfun-go": "https://go.pump.fun",
}

SHUTDOWN = False


def _signal_handler(signum, frame):
    global SHUTDOWN
    SHUTDOWN = True
    print(f"{datetime.now(timezone.utc).isoformat()} | Received shutdown signal ({signum}), stopping gracefully...")


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def fetch_superteam(timeout: int = 30) -> List[Dict[str, Any]]:
    """Fetch bounties from Superteam Earn API and filter/validate records."""
    req = urllib.request.Request(
        SOURCES["superteam-earn"],
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw_data = r.read().decode("utf-8")
        data = json.loads(raw_data)

    if not isinstance(data, list):
        raise ValueError("Superteam response is not a list")

    out: List[Dict[str, Any]] = []
    for j in data:
        if not isinstance(j, dict):
            continue
        lid = j.get("id")
        slug = j.get("slug")
        if not db.validate_listing_id(lid) or not db.validate_slug(slug):
            continue

        lid = str(lid).strip()
        slug = str(slug).strip()
        reward_str = f"{j.get('rewardAmount')} {j.get('token')}" if j.get("rewardAmount") is not None else None
        deadline_str = (j.get("deadline") or "")[:10]

        item = {
            "id": lid,
            "slug": slug,
            "source": "superteam-earn",
            "title": j.get("title") or "",
            "reward": reward_str,
            "deadline": deadline_str,
            "agent_access": j.get("agentAccess"),
            "url": f"https://earn.superteam.fun/listing/{slug}",
        }
        out.append(item)
    return out


def deliver_telegram(item: Dict[str, Any], token: str, chat: str, timeout: int = 15) -> None:
    """Deliver a single notification to Telegram."""
    msg = f"🤑 NEW bounty: {item['title']}\n💰 {item['reward']} | ⏳ {item['deadline']}\n🔗 {item['url']}"
    payload = json.dumps({"chat_id": chat, "text": msg}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise urllib.error.HTTPError(
                req.full_url, resp.status, f"Telegram delivery returned status {resp.status}", resp.headers, None
            )


def deliver_discord(item: Dict[str, Any], webhook_url: str, timeout: int = 15) -> None:
    """Deliver a single notification to Discord webhook with required User-Agent header."""
    msg = f"🤑 NEW bounty: {item['title']}\n💰 {item['reward']} | ⏳ {item['deadline']}\n🔗 {item['url']}"
    payload = json.dumps({"content": msg}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "bounty-radar/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        # Discord returns 200 or 204 No Content on success
        if resp.status not in (200, 204):
            raise urllib.error.HTTPError(
                req.full_url, resp.status, f"Discord delivery returned status {resp.status}", resp.headers, None
            )


def deliver_pending(channel: str, max_items: Optional[int] = None) -> Tuple[int, int, int]:
    """Process pending and due retry items without dropping or slicing notifications."""
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    dc_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

    if channel == "discord" and not dc_url:
        print(f"{datetime.now(timezone.utc).isoformat()} | Discord delivery skipped: DISCORD_WEBHOOK_URL not configured")
        return 0, 0, 0
    elif channel != "discord" and (not tg_token or not tg_chat):
        print(f"{datetime.now(timezone.utc).isoformat()} | Telegram delivery skipped: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not configured")
        return 0, 0, 0

    pending = db.get_pending_deliveries(limit=max_items)
    delivered_count = 0
    transient_failures = 0
    permanent_failures = 0

    for item in pending:
        lid = item["id"]
        # Atomically claim to prevent duplicate delivery across concurrent workers
        if not db.claim_delivery(lid):
            continue

        try:
            if channel == "discord":
                deliver_discord(item, dc_url)
            else:
                deliver_telegram(item, tg_token, tg_chat)

            db.mark_delivered(lid)
            delivered_count += 1
            # Micro-pause between notifications to avoid hitting webhook rate limits
            time.sleep(0.2)

        except urllib.error.HTTPError as err:
            err_str = f"HTTP {err.code}: {err.reason}"
            if err.code in (400, 401, 403, 404):
                db.mark_permanent_failure(lid, err_str)
                permanent_failures += 1
            else:
                # 429, 500, 502, 503, 504 -> transient retry
                db.mark_transient_failure(lid, err_str)
                transient_failures += 1
            print(f"{datetime.now(timezone.utc).isoformat()} | delivery error for {lid}: {db.sanitize_error(err_str)}")

        except Exception as exc:
            err_str = f"{type(exc).__name__}: {str(exc)}"
            db.mark_transient_failure(lid, err_str)
            transient_failures += 1
            print(f"{datetime.now(timezone.utc).isoformat()} | delivery exception for {lid}: {db.sanitize_error(err_str)}")

    return delivered_count, transient_failures, permanent_failures


def main() -> None:
    db.init_db()

    # Recover any crashed workers from previous runs
    recovered = db.recover_stale_delivering()
    if recovered > 0:
        print(f"{datetime.now(timezone.utc).isoformat()} | recovered {recovered} stale delivering records")

    all_items: List[Dict[str, Any]] = []

    # 1. Fetch Superteam Earn
    try:
        superteam_items = fetch_superteam()
        all_items.extend(superteam_items)
    except Exception as e:
        print(f"{datetime.now(timezone.utc).isoformat()} | Superteam fetch warning: {db.sanitize_error(e)}")

    # 2. Fetch Pump.fun GO
    try:
        pumpfun_items = pumpfun.fetch_pumpfun_bounties()
        all_items.extend(pumpfun_items)
    except Exception as e:
        print(f"{datetime.now(timezone.utc).isoformat()} | Pump.fun fetch warning: {db.sanitize_error(e)}")

    truly_agent = [i for i in all_items if i.get("agent_access") == "AGENT_ALLOWED"]
    new_items = db.store_listings(all_items)
    agent_new = [i for i in new_items if i.get("agent_access") == "AGENT_ALLOWED"]

    # Also record opportunity objects for cross-agent discovery
    for item in truly_agent:
        src = item.get("source", "superteam-earn")
        provenance = "go.pump.fun" if src == "pumpfun" else "superteam.fun/api/listings?type=bounty&filter=agents"
        opp = {
            "source": src,
            "id": item["id"],
            "title": item.get("title"),
            "reward": item.get("reward"),
            "deadline": item.get("deadline"),
            "url": item.get("url"),
            "agent_access": item.get("agent_access"),
            "observed_at": db.utcnow(),
            "provenance": provenance,
            "skills": [],
            "eligibility": [],
            "region": None,
            "requirements": None,
            "description_text": item.get("description", ""),
        }
        db.record_opportunity(opp, enriched=False)

    print(
        f"{datetime.now(timezone.utc).isoformat()} | total={len(all_items)} agent_allowed={len(truly_agent)} new={len(new_items)} agent_new={len(agent_new)}"
    )
    for i in new_items[:5]:
        print(f"  NEW [{i.get('agent_access')}] {i.get('title')} | {i.get('reward')} | {i.get('deadline')}")

    channel = os.environ.get("RADAR_CHANNEL", "telegram").lower()
    delivered, transient_errs, permanent_errs = deliver_pending(channel=channel)
    if delivered > 0 or transient_errs > 0 or permanent_errs > 0:
        print(
            f"{datetime.now(timezone.utc).isoformat()} | delivery batch completed: delivered={delivered} transient_retries={transient_errs} permanent_failed={permanent_errs}"
        )

    # Check live Solana market conditions & dispatch entry zone alerts
    try:
        sentinel_msg = market_sentinel.check_market_triggers()
        if sentinel_msg:
            print(f"{datetime.now(timezone.utc).isoformat()} | market_sentinel: {sentinel_msg}")
    except Exception as e:
        print(f"{datetime.now(timezone.utc).isoformat()} | market_sentinel warning: {db.sanitize_error(e)}")

    # Separate DLMM / Mr Bands research lane (does not replace sentinel logic;
    # never signs transactions or deploys live positions).
    try:
        from bands_compare.comparator import check_dlmm_lane

        dlmm_msg = check_dlmm_lane()
        if dlmm_msg:
            print(f"{datetime.now(timezone.utc).isoformat()} | bands_compare: {dlmm_msg}")
    except Exception as e:
        print(f"{datetime.now(timezone.utc).isoformat()} | bands_compare warning: {db.sanitize_error(e)}")


def run_cycle() -> None:
    """Execute a single fetch, store, and deliver cycle safely."""
    try:
        main()
    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)}"
        print(f"{datetime.now(timezone.utc).isoformat()} | cycle error (continuing): {db.sanitize_error(err_msg)}")


def poll_loop(stop_event: Optional[threading.Event] = None, interval: Optional[int] = None) -> None:
    """Run continuous polling until SHUTDOWN or stop_event is set."""
    if interval is None:
        interval = int(os.environ.get("RADAR_INTERVAL_SEC", "3600"))
    while not SHUTDOWN and (stop_event is None or not stop_event.is_set()):
        run_cycle()
        for _ in range(interval):
            if SHUTDOWN or (stop_event and stop_event.is_set()):
                break
            time.sleep(1)


def start_background_poller(interval: Optional[int] = None) -> Tuple[threading.Thread, threading.Event]:
    """Start the poller loop in a background daemon thread."""
    stop_event = threading.Event()
    thread = threading.Thread(
        target=poll_loop,
        kwargs={"stop_event": stop_event, "interval": interval},
        daemon=True,
        name="RadarPollerThread",
    )
    thread.start()
    return thread, stop_event


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bounty Radar discovery and alert poller")
    parser.add_argument("--once", action="store_true", help="Run a single poll cycle and exit")
    args = parser.parse_args()

    if args.once:
        run_cycle()
    else:
        poll_loop()
