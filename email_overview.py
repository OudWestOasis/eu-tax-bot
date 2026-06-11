# -*- coding: utf-8 -*-
"""
Bouwt het wekelijkse CIT + EU overzicht als HTML-mail en verstuurt het.

Hergebruikt dezelfde data als de Telegram-overview (cit_baseline.json), maar
rendert een nette HTML-tabel i.p.v. Telegram-opmaak. Wordt vrijdagochtend door
de workflow email.yml gedraaid.
"""

import sys
import html
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from settings import load_config
import overview as ov
import emailer

STATUS_CELL = {
    "proposal": ("🟡", "#b8860b", "voorstel"),
    "recent": ("🔴", "#c0392b", "recent gewijzigd"),
    "stable": ("✅", "#1e8449", "ongewijzigd"),
}


def _status(c):
    if c.get("proposal"):
        p = c["proposal"]
        return STATUS_CELL["proposal"], (
            f"→ {ov.fmt_rate(p['new_rate'])} per {p['effective'][:7]} "
            f"({html.escape(p['detail'])})"
        )
    if c.get("recent"):
        return STATUS_CELL["recent"], html.escape(c["recent"])
    return STATUS_CELL["stable"], ""


def _rows(items):
    out = []
    for name, c in items:
        (icon, color, label), detail = _status(c)
        note = c.get("note", "")
        extra = "<br>".join(x for x in [detail, f"<i>{html.escape(note)}</i>" if note else ""] if x)
        out.append(
            f'<tr>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #eee;white-space:nowrap;">'
            f'{c.get("flag","")} <b>{c.get("code","")}</b> '
            f'<span style="color:#666;">{html.escape(name)}</span></td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;font-weight:bold;">'
            f'{ov.fmt_rate(c["rate"])}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #eee;color:{color};">'
            f'{icon} {label}{("<br>" + extra) if extra else ""}</td>'
            f'</tr>'
        )
    return "\n".join(out)


def build_html(baseline):
    countries = baseline["countries"]
    prio = [(n, c) for n, c in countries.items() if c.get("priority")]
    rest = sorted(((n, c) for n, c in countries.items() if not c.get("priority")),
                  key=lambda x: x[0])

    eu = []
    for dev in baseline.get("eu_developments", []):
        icon = "🔴" if dev["status"] == "ENACTED" else "🟡"
        eu.append(
            f'<li style="margin-bottom:8px;">{icon} <b>{html.escape(dev["title"])}</b> '
            f'<span style="color:#888;">({dev["date"]})</span><br>'
            f'<span style="color:#444;">{html.escape(dev["detail"])}</span></li>'
        )

    table_style = 'style="border-collapse:collapse;width:100%;font-size:14px;"'
    th = 'style="padding:6px 10px;text-align:left;border-bottom:2px solid #ccc;background:#f5f5f5;"'
    return f"""<!DOCTYPE html>
<html><body style="font-family:Arial,Helvetica,sans-serif;color:#222;max-width:760px;margin:auto;">
  <h2 style="margin-bottom:0;">📋 Tax Developments Europa</h2>
  <p style="color:#888;margin-top:4px;">CIT-tarieven {baseline['as_of']} · {html.escape(baseline['source'])}</p>

  <h3>Prioriteitslanden</h3>
  <table {table_style}>
    <tr><th {th}>Land</th><th {th}>CIT</th><th {th}>Status</th></tr>
    {_rows(prio)}
  </table>

  <h3 style="margin-top:24px;">Overig Europa</h3>
  <table {table_style}>
    <tr><th {th}>Land</th><th {th}>CIT</th><th {th}>Status</th></tr>
    {_rows(rest)}
  </table>
  <p style="font-size:12px;color:#888;">Legenda: ✅ ongewijzigd · 🟡 voorstel (nog niet enacted) · 🔴 recent gewijzigd</p>

  <h3 style="margin-top:24px;">🇪🇺 EU-ontwikkelingen</h3>
  <ul style="padding-left:18px;">{''.join(eu)}</ul>

  <hr style="border:none;border-top:1px solid #eee;margin-top:24px;">
  <p style="font-size:12px;color:#aaa;">
    Automatisch verstuurd door je EU Tax Developments bot (GitHub Actions).
    Tarieven uit cit_baseline.json — voor de officiële tekst, raadpleeg de bron.
  </p>
</body></html>"""


def main():
    cfg = load_config()
    to_addr = cfg.get("email_to", "").strip()
    baseline = ov.load_baseline()
    today = datetime.now(timezone.utc).strftime("%d-%m-%Y")
    subject = f"📋 Tax Developments Europa — {today}"
    html_body = build_html(baseline)

    emailer.send_email(to_addr, subject, html_body)
    print(f"E-mail verstuurd naar {to_addr}.")


if __name__ == "__main__":
    main()
