# -*- coding: utf-8 -*-
"""
EU Tax Developments Telegram bot — main script.

Run once (e.g. daily via Windows Task Scheduler). It:
  1. Loads config + source list.
  2. Fetches every RSS feed (Google News searches + specialist feeds).
  3. Filters for relevant tax-rate / directive news.
  4. Classifies each item as ENACTED / PROPOSAL / UPDATE (keyword-based).
  5. De-duplicates against state.json (only new items are sent).
  6. Sends a batched digest to Telegram, ENACTED items first.

First run seeds the state silently (no flood) and sends a short "I'm live"
message plus any currently-detected ENACTED items.
"""

import json
import os
import sys
import html
import time
import hashlib
from datetime import datetime, timezone, timedelta

import feedparser
import requests

# Make console output emoji-safe on Windows (cp1252 consoles otherwise crash).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from sources import build_sources
from classifier import is_relevant, classify_status, mentions_europe, STATUS_ICON
from settings import load_config
import coordinator

HERE = os.path.dirname(os.path.abspath(__file__))
# DATA_DIR lets the state live on a persistent volume (Railway) instead of the
# ephemeral container filesystem. Defaults to the script dir for local/CI use.
DATA_DIR = os.environ.get("DATA_DIR", HERE)
STATE_PATH = os.path.join(DATA_DIR, "state.json")
LOG_PATH = os.path.join(DATA_DIR, "monitor.log")

STATUS_ORDER = {"ENACTED": 0, "PROPOSAL": 1, "UPDATE": 2}


# ---------------------------------------------------------------- utilities ---

def log(msg):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_state():
    if not os.path.exists(STATE_PATH):
        return {"seen": {}, "first_run": True}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("seen", {})
        data["first_run"] = False
        return data
    except (OSError, json.JSONDecodeError):
        return {"seen": {}, "first_run": True}


def save_state(state):
    # Prune entries older than 90 days to keep the file small.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).timestamp()
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"seen": state["seen"]}, f)


def item_id(link, title):
    raw = (link or "") + "|" + (title or "")
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:16]


def entry_datetime(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
    return None


def clean(text):
    # feedparser summaries can contain HTML; strip tags crudely.
    import re
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# ------------------------------------------------------------------- fetch ---

def fetch_all(sources, max_age_days):
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    items = []
    seen_in_run = set()

    for i, src in enumerate(sources, 1):
        try:
            d = feedparser.parse(src["url"])
        except Exception as e:  # noqa: BLE001 - never let one feed kill the run
            log(f"  [warn] feed {i}/{len(sources)} failed: {e}")
            continue

        for entry in d.entries:
            title = clean(entry.get("title", ""))
            summary = clean(entry.get("summary", ""))
            link = entry.get("link", "")
            if not title or not link:
                continue

            dt = entry_datetime(entry)
            if dt and dt < cutoff:
                continue
            # Targeted query sources are already topical; broad feeds need the
            # stricter check.
            strict = src["topic"] in ("GENERAL",)
            if not is_relevant(title, summary, strict=strict):
                continue
            # The broad feed isn't country-tagged; keep only European items.
            if src["topic"] == "GENERAL" and not mentions_europe(title, summary):
                continue

            iid = item_id(link, title)
            if iid in seen_in_run:
                continue
            seen_in_run.add(iid)

            status, evidence = classify_status(title, summary)
            items.append({
                "id": iid,
                "title": title,
                "summary": summary,
                "link": link,
                "source": (entry.get("source", {}) or {}).get("title", "")
                          or (d.feed.get("title", "") if hasattr(d, "feed") else ""),
                "country": src["country"],
                "topic": src["topic"],
                "priority": src["priority"],
                "status": status,
                "evidence": evidence,
                "dt": dt.isoformat() if dt else "",
                "ts": dt.timestamp() if dt else 0,
            })

        log(f"  feed {i}/{len(sources)} [{src['country']}/{src['topic']}] -> {len(d.entries)} raw")

    return items


def sort_items(items):
    return sorted(
        items,
        key=lambda x: (
            STATUS_ORDER.get(x["status"], 9),
            0 if x["priority"] else 1,
            -x["ts"],
        ),
    )


# ---------------------------------------------------------------- telegram ---

def tg_send(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, data={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }, timeout=30)
    if not r.ok:
        log(f"  [error] telegram send failed: {r.status_code} {r.text[:200]}")
    return r.ok


def format_item(it):
    icon = STATUS_ICON.get(it["status"], it["status"])
    title = html.escape(it["title"])
    parts = [f"{icon}", f"<b>{title}</b>"]
    meta = []
    if it["country"] and it["country"] != "EU":
        meta.append(it["country"])
    elif it["country"] == "EU":
        meta.append("🇪🇺 EU")
    if it["topic"] and it["topic"] not in ("GENERAL",):
        meta.append(it["topic"])
    if it["source"]:
        meta.append(html.escape(it["source"]))
    if it["dt"]:
        meta.append(it["dt"][:10])
    if meta:
        parts.append("· ".join(meta))
    parts.append(f'<a href="{html.escape(it["link"], quote=True)}">Lees verder</a>')
    return "\n".join(parts)


def send_digest(token, chat_id, items, per_message, header):
    if header:
        tg_send(token, chat_id, header)
        time.sleep(0.5)
    batch = []
    for it in items:
        batch.append(format_item(it))
        if len(batch) >= per_message:
            tg_send(token, chat_id, "\n\n".join(batch))
            batch = []
            time.sleep(0.6)
    if batch:
        tg_send(token, chat_id, "\n\n".join(batch))


# ------------------------------------------------------------------- main ----

def main():
    cfg = load_config()
    token = cfg.get("telegram_token", "").strip()
    chat_id = str(cfg.get("chat_id", "")).strip()

    if not token:
        log("No telegram_token in config.json — abort.")
        sys.exit(1)
    if not chat_id:
        log("No chat_id in config.json yet. Run get_chat_id.py first (send /start to the bot).")
        sys.exit(1)

    # Hand over to the laptop when it's active (only the cloud stands by).
    if coordinator.should_cloud_standby():
        log("laptop actief — cloud staat stand-by (scan overgeslagen)")
        return

    state = load_state()
    first_run = state.get("first_run", False)

    log(f"=== Run start (first_run={first_run}) ===")
    sources = build_sources(cfg)
    log(f"Built {len(sources)} sources.")

    items = fetch_all(sources, cfg.get("max_age_days", 21))
    log(f"Collected {len(items)} relevant items before dedup.")

    # De-duplicate against state.
    new_items = [it for it in items if it["id"] not in state["seen"]]
    now_ts = datetime.now(timezone.utc).timestamp()
    for it in items:
        state["seen"][it["id"]] = it["ts"] or now_ts

    new_items = sort_items(new_items)
    log(f"{len(new_items)} new items after dedup.")

    if first_run:
        enacted = [it for it in new_items if it["status"] == "ENACTED"][:10]
        header = (
            "✅ <b>Tax Developments bot is live</b>\n"
            f"Monitoring {len(sources)} bronnen voor "
            "EU + NL, LU, DK, FI, NO, SE.\n"
            "Je krijgt vanaf nu dagelijks meldingen over CIT-/BTW-tarieven en EU-richtlijnen, "
            "met 🔴 ENACTED gemarkeerd.\n\n"
            f"Huidige reeds-aangenomen items ({len(enacted)} getoond):"
        )
        if enacted:
            send_digest(token, chat_id, enacted, cfg.get("items_per_message", 6), header)
        else:
            tg_send(token, chat_id, header + "\n(geen enacted items op dit moment)")
        save_state(state)
        log("First run complete: state seeded.")
        return

    if not new_items:
        log("No new items; nothing to send.")
        save_state(state)
        return

    cap = cfg.get("max_items_per_run", 50)
    truncated = len(new_items) > cap
    to_send = new_items[:cap]

    n_enacted = sum(1 for it in to_send if it["status"] == "ENACTED")
    today = datetime.now().strftime("%d-%m-%Y")
    header = (
        f"📊 <b>Tax Developments — {today}</b>\n"
        f"{len(to_send)} nieuwe items"
        + (f", waarvan 🔴 {n_enacted} ENACTED" if n_enacted else "")
        + ("\n⚠️ (lijst afgekapt — meer items beschikbaar)" if truncated else "")
    )
    send_digest(token, chat_id, to_send, cfg.get("items_per_message", 6), header)

    save_state(state)
    log(f"Sent {len(to_send)} items. Run complete.")


if __name__ == "__main__":
    main()
