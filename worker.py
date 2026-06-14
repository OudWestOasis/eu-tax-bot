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

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

HERE = os.path.dirname(os.path.abspath(__file__))
SCAN_LOCK = threading.Lock()


def log(msg):
    print(f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}  {msg}", flush=True)


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


def job_email():
    try:
        email_overview.main()
        log("overzicht (e-mail) verstuurd")
    except SystemExit:
        log("e-mail: SystemExit (SMTP secrets?)")
    except Exception as e:  # noqa: BLE001
        log(f"e-mail fout: {e}")


def start_scheduler():
    sched = BackgroundScheduler(timezone="UTC")
    # NB: timezone moet PER trigger mee — een losse CronTrigger erft de
    # scheduler-tz niet, en zou anders op lokale tijd draaien.
    UTC = "UTC"
    # Dagelijkse nieuws-scan — 06:00 UTC (= 07:00/08:00 NL).
    sched.add_job(lambda: do_scan("schedule"), CronTrigger(hour=6, minute=0, timezone=UTC),
                  id="scan", misfire_grace_time=3600)
    # Overzicht naar Telegram — maandag 06:30 en vrijdag 06:00 UTC.
    sched.add_job(job_overview, CronTrigger(day_of_week="mon", hour=6, minute=30, timezone=UTC),
                  id="overview_mon", misfire_grace_time=3600)
    sched.add_job(job_overview, CronTrigger(day_of_week="fri", hour=6, minute=0, timezone=UTC),
                  id="overview_fri", misfire_grace_time=3600)
    # Overzicht per e-mail — vrijdag 06:00 UTC.
    sched.add_job(job_email, CronTrigger(day_of_week="fri", hour=6, minute=0, timezone=UTC),
                  id="email_fri", misfire_grace_time=3600)
    sched.start()
    log("scheduler gestart (UTC): scan 06:00 dagelijks · overzicht ma 06:30 + vr 06:00 · mail vr 06:00")
    return sched


# ----------------------------------------------------------- command loop -----

def handle_message(token, chat_id, text):
    cmd = text.strip().partition(" ")[0].lower().lstrip("/").split("@")[0]
    if cmd == "scan":
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
                    handle_message(token, chat_id, text)
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
                        "✅ <b>Bot draait nu volledig op Railway</b>\n"
                        "Commando's worden direct beantwoord. Typ <b>Tax</b> of /help.")
        except Exception:  # noqa: BLE001
            pass

    command_loop(token)        # blokkeert (long-poll) — houdt het proces in leven


if __name__ == "__main__":
    main()
