# -*- coding: utf-8 -*-
"""
Railway worker — één doorlopend proces dat de hele bot draait.

Anders dan GitHub Actions (losse cron-runs) draait dit als één altijd-aan
service:
  - MAIN THREAD: long-polling op Telegram -> commando's worden DIRECT beantwoord
    (geen poll-interval meer). Trefwoord 'Tax'/'Belasting' en /overview, /cit,
    /eu, /scan, /help.
  - ACHTERGROND-SCHEDULER (APScheduler, UTC): de geplande taken
      * dagelijkse nieuws-scan        06:00 UTC
      * overzicht naar Telegram       ma 06:30 + vr 06:00 UTC
      * overzicht per e-mail          vr 06:00 UTC

Eén proces = geen coördinatie nodig en NOOIT dubbele berichten.
State (dedup) staat op een persistente volume via DATA_DIR (zie Dockerfile).
Secrets komen uit environment-variabelen (Railway Variables) via settings.py.
"""

import os
import sys
import time
import shutil
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from datetime import datetime, timezone

from settings import load_config
import overview as ov
import poller
import tax_monitor
import email_overview
import claude_research as cr

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

HERE = os.path.dirname(os.path.abspath(__file__))
SCAN_LOCK = threading.Lock()


def log(msg):
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}  {msg}"
    print(line, flush=True)
    try:
        with open(os.path.join(HERE, "worker.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# --------------------------------------------------------------- state seed --

def ensure_state_seed():
    """Copy the bundled state.json onto the volume on first boot, so the dedup
    history carries over and we don't re-send old items."""
    target = tax_monitor.STATE_PATH
    bundled = os.path.join(HERE, "state.json")
    if os.path.exists(target):
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.abspath(bundled) != os.path.abspath(target) and os.path.exists(bundled):
        try:
            shutil.copyfile(bundled, target)
            log(f"state seeded -> {target}")
        except OSError as e:
            log(f"state seed failed: {e}")


# ------------------------------------------------------------------- jobs -----

def do_scan(reason=""):
    if not SCAN_LOCK.acquire(blocking=False):
        log(f"scan al bezig — overgeslagen ({reason})")
        return
    try:
        log(f"scan start ({reason})")
        tax_monitor.main()
        log("scan klaar")
    except SystemExit:
        log("scan: SystemExit (config?)")
    except Exception as e:  # noqa: BLE001
        log(f"scan fout: {e}")
    finally:
        SCAN_LOCK.release()


def job_overview():
    cfg = load_config()
    try:
        ov.send_overview(cfg["telegram_token"], cfg["chat_id"], "full")
        log("overzicht (Telegram) verstuurd")
    except Exception as e:  # noqa: BLE001
        log(f"overzicht fout: {e}")


def send_plain(token, chat_id, text):
    """Stuur platte tekst (geen HTML) — Claude-output kan < > & bevatten."""
    for chunk in ov.split_for_telegram(text):
        poller.api(token, "sendMessage", data={
            "chat_id": chat_id, "text": chunk, "disable_web_page_preview": "true"})


def deep_research_to(token, chat_id):
    """Claude Deep Research op aanvraag ('API'). Lokaal als Claude er is; anders
    een verzoek loggen voor de laptop-bridge (Railway-modus)."""
    if cr.available():
        poller.send(token, chat_id, "🔎 Claude doet nu deep research… (kan ~1–3 min duren)")
        ok, text = cr.research()
        if ok:
            send_plain(token, chat_id, "🧠 Deep research (Claude) — tax-ontwikkelingen:\n\n" + text)
        elif text == "LOGIN":
            poller.send(token, chat_id, "⚠️ Claude is niet ingelogd op de laptop. "
                                        "Draai eenmalig <code>claude</code> en /login.")
        else:
            poller.send(token, chat_id, f"⚠️ Deep research mislukt: {text}")
    else:
        log(f"RESEARCH_REQUEST id=0 chat={chat_id}")
        poller.send(token, chat_id, "🔎 Deep research aangevraagd; je laptop met Claude pakt het op "
                                    "zodra die aan staat.")


def combined_update(reason=""):
    """De '2x per week'-update. Op de laptop: Claude Deep Research + CIT/EU-overzicht.
    Zonder Claude (Railway): nieuws-scan + overzicht."""
    log(f"combined update start ({reason})")
    cfg = load_config()
    token, chat_id = cfg["telegram_token"], cfg["chat_id"]
    used_claude = False
    if cr.available():
        ok, text = cr.research()
        if ok:
            send_plain(token, chat_id, "🧠 Wekelijkse deep research (Claude) — tax-ontwikkelingen:\n\n" + text)
            used_claude = True
        else:
            log(f"claude research niet gelukt ({text[:40]}) — val terug op scan")
    if not used_claude:
        do_scan(reason)        # fallback: nieuwe ontwikkelingen via de scan
    job_overview()             # CIT/EU-overzicht
    log(f"combined update klaar (claude={used_claude})")


def start_scheduler():
    sched = BackgroundScheduler(timezone="UTC")
    # NB: timezone moet PER trigger mee — een losse CronTrigger erft de
    # scheduler-tz niet, en zou anders op lokale tijd draaien.
    UTC = "UTC"
    # Gecombineerde update — 2x per week: maandag + vrijdag 06:00 UTC
    # (= 08:00 NL zomer / 07:00 NL winter).
    sched.add_job(lambda: combined_update("schedule-mon"),
                  CronTrigger(day_of_week="mon", hour=6, minute=0, timezone=UTC),
                  id="update_mon", misfire_grace_time=3600)
    sched.add_job(lambda: combined_update("schedule-fri"),
                  CronTrigger(day_of_week="fri", hour=6, minute=0, timezone=UTC),
                  id="update_fri", misfire_grace_time=3600)
    sched.start()
    log("scheduler gestart (UTC): gecombineerde update ma 06:00 + vr 06:00")
    return sched


# ----------------------------------------------------------- command loop -----

def handle_message(token, chat_id, text, update_id=0):
    cmd = text.strip().partition(" ")[0].lower().lstrip("/").split("@")[0]
    if cmd == "api":
        deep_research_to(token, chat_id)          # Claude Deep Research (lokaal)
    elif cmd == "fastlane":
        # On-demand: dezelfde gecombineerde update als de 2x/week-planning.
        poller.send(token, chat_id, "⏳ Fastlane-update gestart… (nieuws + overzicht)")
        combined_update("fastlane")
        poller.send(token, chat_id, "✅ Update klaar.")
    elif cmd == "scan":
        # /scan via de gedeelde, gelockte scan (geen dubbele scan-threads).
        poller.send(token, chat_id, "⏳ Verse nieuws-scan gestart…")
        do_scan("command")
        poller.send(token, chat_id, "✅ Scan klaar.")
    else:
        poller.handle(token, chat_id, text)


def command_loop(token):
    poller.set_commands(token)
    log("command-loop gestart (long-polling) — commando's worden direct beantwoord")
    offset = None
    while True:
        try:
            # Long-poll timeout must stay BELOW poller.api's HTTP timeout (40s),
            # anders breekt de HTTP-read voordat de long-poll terugkeert.
            params = {"timeout": 25}
            if offset is not None:
                params["offset"] = offset
            r = poller.api(token, "getUpdates", params=params)
            data = r.json()
            if not data.get("ok"):
                time.sleep(5)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue
                text = msg.get("text", "")
                chat_id = str(msg["chat"]["id"])
                if not text:
                    continue
                log(f"cmd from {chat_id}: {text[:40]}")
                try:
                    handle_message(token, chat_id, text, upd["update_id"])
                except Exception as e:  # noqa: BLE001
                    log(f"handle fout: {e}")
        except Exception as e:  # noqa: BLE001
            log(f"loop fout: {e}; 10s wachten")
            time.sleep(10)


# ------------------------------------------------------------------- main -----

def main():
    cfg = load_config()
    token = cfg.get("telegram_token", "").strip()
    chat_id = str(cfg.get("chat_id", "")).strip()
    if not token or not chat_id:
        log("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID ontbreken — afbreken.")
        sys.exit(1)

    log("=== EU Tax bot (Railway worker) start ===")
    ensure_state_seed()
    start_scheduler()

    if os.environ.get("ANNOUNCE_STARTUP", "1") == "1":
        try:
            poller.send(token, chat_id,
                        "✅ <b>Bot bijgewerkt</b>\n"
                        "Je krijgt nu automatisch <b>2× per week</b> een update "
                        "(maandag & vrijdag ochtend).\n"
                        "Typ <b>fastlane</b> voor een directe update, of /help.")
        except Exception:  # noqa: BLE001
            pass

    command_loop(token)        # blokkeert (long-poll) — houdt het proces in leven


if __name__ == "__main__":
    main()
