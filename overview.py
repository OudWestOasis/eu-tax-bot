# -*- coding: utf-8 -*-
"""
High-level status overview for the EU Tax Developments bot.

Builds a compact snapshot:
  - CIT-rate per land (prioriteitslanden eerst, dan rest van Europa)
  - status-markering:  ✅ ongewijzigd  ·  🟡 voorstel  ·  🔴 recent gewijzigd
  - EU-ontwikkelingen (non-coöperatieve lijst, Pillar Two, ViDA, + live nieuws)

Used by:
  - python overview.py        -> stuurt het volledige overzicht naar Telegram
  - bot_listener.py           -> /overview, /cit, /eu commando's
"""

import os
import sys
import json
import html

import feedparser

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE_PATH = os.path.join(HERE, "cit_baseline.json")

TG_LIMIT = 3800  # keep messages under Telegram's 4096 limit

from settings import load_config  # noqa: E402  (secrets via env, config fallback)


def load_baseline():
    with open(BASELINE_PATH, encoding="utf-8") as f:
        return json.load(f)


def fmt_rate(r):
    # 25.8 -> "25,8%", 22.0 -> "22%"
    if float(r).is_integer():
        return f"{int(r)}%"
    return f"{r:.1f}".replace(".", ",") + "%"


def country_line(name, c):
    flag = c.get("flag", "")
    code = c.get("code", name[:2].upper())
    rate = fmt_rate(c["rate"])
    prop = c.get("proposal")
    if prop:
        status = f"🟡 → {fmt_rate(prop['new_rate'])} per {prop['effective'][:7]} (voorstel)"
    elif c.get("recent"):
        status = f"🔴 {c['recent']}"
    else:
        status = "✅ ongewijzigd"
    line = f"{flag} <b>{code}</b> {rate}  {status}"
    if c.get("note"):
        line += f"\n    <i>{html.escape(c['note'])}</i>"
    return line


def build_cit_section(baseline):
    countries = baseline["countries"]
    prio = [(n, c) for n, c in countries.items() if c.get("priority")]
    rest = sorted(((n, c) for n, c in countries.items() if not c.get("priority")),
                  key=lambda x: x[0])

    lines = [f"📋 <b>CIT-overzicht Europa</b> — {baseline['as_of']}",
             f"<i>{html.escape(baseline['source'])}</i>",
             "",
             "<b>Prioriteitslanden</b>"]
    lines += [country_line(n, c) for n, c in prio]
    lines += ["", "<b>Overig Europa</b>"]
    lines += [country_line(n, c) for n, c in rest]
    lines += ["",
              "Legenda: ✅ ongewijzigd · 🟡 voorstel (nog niet enacted) · 🔴 recent gewijzigd"]
    return "\n".join(lines)


def fetch_live_eu_news(max_items=4):
    """Quick scan of EU-directive queries for fresh headlines (best-effort)."""
    from sources import _gnews
    from classifier import is_relevant
    queries = [
        "EU tax directive adopted",
        '"VAT in the Digital Age" ViDA',
        "EU Pillar Two minimum tax directive",
        "EU non-cooperative jurisdictions list",
    ]
    seen, out = set(), []
    for q in queries:
        try:
            d = feedparser.parse(_gnews(q))
        except Exception:  # noqa: BLE001
            continue
        for e in d.entries[:6]:
            title = e.get("title", "").strip()
            link = e.get("link", "")
            if not title or title in seen:
                continue
            if not is_relevant(title, e.get("summary", "")):
                continue
            seen.add(title)
            out.append((title, link))
            break  # one per query keeps it high-level
    return out[:max_items]


def build_eu_section(baseline, with_live=True):
    lines = ["🇪🇺 <b>EU-ontwikkelingen</b>", ""]
    for dev in baseline.get("eu_developments", []):
        icon = "🔴" if dev["status"] == "ENACTED" else "🟡"
        lines.append(f"{icon} <b>{html.escape(dev['title'])}</b> ({dev['date']})")
        lines.append(f"    <i>{html.escape(dev['detail'])}</i>")
    if with_live:
        live = fetch_live_eu_news()
        if live:
            lines += ["", "<b>Recent in het nieuws</b>"]
            for title, link in live:
                t = html.escape(title)
                lines.append(f'• <a href="{html.escape(link, quote=True)}">{t}</a>')
    return "\n".join(lines)


def split_for_telegram(text):
    """Split a long message into <TG_LIMIT chunks on line boundaries."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > TG_LIMIT:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur)
    return chunks


def tg_send(token, chat_id, text):
    import requests
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": "true"},
        timeout=30,
    )
    return r.ok


def build_full_overview(with_live=True):
    baseline = load_baseline()
    return build_cit_section(baseline) + "\n\n" + build_eu_section(baseline, with_live)


def send_overview(token, chat_id, which="full"):
    baseline = load_baseline()
    if which == "cit":
        text = build_cit_section(baseline)
    elif which == "eu":
        text = build_eu_section(baseline)
    else:
        text = build_cit_section(baseline) + "\n\n" + build_eu_section(baseline)
    for chunk in split_for_telegram(text):
        tg_send(token, chat_id, chunk)


def main():
    cfg = load_config()
    token = cfg.get("telegram_token", "").strip()
    chat_id = str(cfg.get("chat_id", "")).strip()
    if not token or not chat_id:
        print("Missing token or chat_id in config.json (run get_chat_id.py).")
        sys.exit(1)
    send_overview(token, chat_id, "full")
    print("Overview sent.")


if __name__ == "__main__":
    main()
