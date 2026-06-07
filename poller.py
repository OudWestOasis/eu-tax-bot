# -*- coding: utf-8 -*-
"""
One-shot Telegram command poller (cloud version of the local listener).

A 24/7 listener isn't possible on free GitHub Actions, so instead a workflow
runs this every X minutes. Each run:
  1. getUpdates (no long-poll) -> all messages not yet confirmed
  2. handle each command (/overview, /cit, /eu, /scan, /help)
  3. confirm them server-side by calling getUpdates with offset = max_id + 1
     so the next run won't see them again (no local offset file needed)

/scan runs the full news scan, which writes state.json; the workflow commits it.
"""

import os
import sys
import html

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from settings import load_config
import overview as ov

API = "https://api.telegram.org/bot{token}/{method}"

HELP = (
    "🤖 <b>Tax Developments bot (cloud)</b>\n\n"
    "💬 Tip: typ gewoon <b>Tax</b> of <b>Belasting</b> (hoofdletters maakt niet uit) "
    "voor het volledige overzicht.\n\n"
    "/overview — volledig overzicht (CIT + EU)\n"
    "/cit — CIT-tarieven per land\n"
    "/cit NL — detail voor één land (bv. NL, FI, DE)\n"
    "/eu — EU-ontwikkelingen\n"
    "/scan — draai nu een verse nieuws-scan\n"
    "/help — deze hulp\n\n"
    "ℹ️ Draait in de cloud: antwoorden komen meestal binnen ~5 min.\n"
    "Elke ochtend krijg je nieuwe ontwikkelingen; elke maandag én vrijdag het volledige overzicht."
)


def api(token, method, **kwargs):
    return requests.post(API.format(token=token, method=method), timeout=40, **kwargs)


def send(token, chat_id, text):
    for chunk in ov.split_for_telegram(text):
        api(token, "sendMessage", data={
            "chat_id": chat_id, "text": chunk, "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        })


def country_detail(arg):
    baseline = ov.load_baseline()
    arg_l = arg.strip().lower()
    for name, c in baseline["countries"].items():
        if arg_l in (name.lower(), c.get("code", "").lower()):
            txt = [f"{c.get('flag','')} <b>{name}</b>",
                   f"CIT: <b>{ov.fmt_rate(c['rate'])}</b> ({baseline['as_of']})"]
            if c.get("proposal"):
                p = c["proposal"]
                txt.append(f"🟡 Voorstel: → {ov.fmt_rate(p['new_rate'])} per "
                           f"{p['effective']} — {html.escape(p['detail'])}")
            elif c.get("recent"):
                txt.append(f"🔴 Recent: {html.escape(c['recent'])}")
            else:
                txt.append("✅ Ongewijzigd")
            if c.get("note"):
                txt.append(f"<i>{html.escape(c['note'])}</i>")
            return "\n".join(txt)
    return f"Land '{html.escape(arg)}' niet gevonden. Probeer een code zoals NL, FI, DE."


def handle(token, chat_id, text):
    cmd, _, arg = text.strip().partition(" ")
    cmd = cmd.lower().lstrip("/").split("@")[0]

    if cmd in ("start", "help"):
        send(token, chat_id, HELP)
    elif cmd in ("overview", "tax", "belasting"):
        # Plain keyword "tax"/"belasting" (any case) also gives the overview.
        send(token, chat_id, ov.build_full_overview(with_live=True))
    elif cmd == "cit":
        if arg.strip():
            send(token, chat_id, country_detail(arg))
        else:
            send(token, chat_id, ov.build_cit_section(ov.load_baseline()))
    elif cmd == "eu":
        send(token, chat_id, ov.build_eu_section(ov.load_baseline(), with_live=True))
    elif cmd == "scan":
        send(token, chat_id, "⏳ Verse nieuws-scan gestart…")
        try:
            import tax_monitor as tm
            tm.main()
            send(token, chat_id, "✅ Scan klaar.")
        except SystemExit:
            send(token, chat_id, "⚠️ Scan kon niet draaien (config/secrets?).")
        except Exception:  # noqa: BLE001
            send(token, chat_id, "⚠️ Er ging iets mis bij de scan.")
    else:
        send(token, chat_id, "Onbekend commando. /help voor de opties.")


def set_commands(token):
    cmds = [
        {"command": "overview", "description": "Volledig overzicht (CIT + EU)"},
        {"command": "cit", "description": "CIT-tarieven per land (of /cit NL)"},
        {"command": "eu", "description": "EU-ontwikkelingen"},
        {"command": "scan", "description": "Draai nu een verse nieuws-scan"},
        {"command": "help", "description": "Hulp"},
    ]
    try:
        api(token, "setMyCommands", json={"commands": cmds})
    except Exception:  # noqa: BLE001
        pass


def main():
    cfg = load_config()
    token = cfg.get("telegram_token", "").strip()
    if not token:
        print("No TELEGRAM_TOKEN; abort.")
        sys.exit(1)

    set_commands(token)

    # 1. Fetch pending updates (short timeout = one-shot, not long-poll).
    r = api(token, "getUpdates", data={"timeout": 0})
    data = r.json()
    if not data.get("ok"):
        print("getUpdates failed:", data)
        sys.exit(1)

    updates = data.get("result", [])
    if not updates:
        print("No pending messages.")
        return

    max_id = 0
    handled = 0
    for upd in updates:
        max_id = max(max_id, upd["update_id"])
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            continue
        text = msg.get("text", "")
        chat_id = str(msg["chat"]["id"])
        if not text:
            continue
        print(f"cmd from {chat_id}: {text[:50]}")
        try:
            handle(token, chat_id, text)
            handled += 1
        except Exception as e:  # noqa: BLE001
            print("handle error:", e)

    # 3. Confirm server-side: offset = max_id + 1 clears them for next run.
    api(token, "getUpdates", data={"offset": max_id + 1, "timeout": 0})
    print(f"Handled {handled} message(s); confirmed up to update_id {max_id}.")


if __name__ == "__main__":
    main()
