# -*- coding: utf-8 -*-
"""
Laptop-runner voor de 'API' deep-research (GRATIS via Claude Code).

Draait ~elke minuut via Windows Taakplanner. Per ronde:
  1. Lees de Railway-logs (de laptop is al bij Railway ingelogd) en zoek het
     laatste 'RESEARCH_REQUEST id=.. chat=..' dat de cloud-worker logde toen jij
     'API' typte.
  2. Is het een NIEUW verzoek -> draai Claude Code headless (jouw abonnement =
     gratis) met websearch, en laat het diepgaand tax-onderzoek doen.
  3. Stuur de samenvatting naar je Telegram-chat.
  4. Onthoud het verwerkte id lokaal (research_last.txt).

Werkt alleen als de laptop aan is met een ingelogde Claude CLI. Staat de laptop
uit, dan blijft het verzoek in de Railway-logs staan en wordt het opgepakt zodra
de laptop weer draait. Bridge = Railway-logs, dus GEEN extra token/secret nodig.
"""

import os
import re
import sys
import time
import shutil
import subprocess

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import requests
from settings import load_config

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK_PATH = os.path.join(HERE, "research.lock")
LAST_PATH = os.path.join(HERE, "research_last.txt")
LOG_PATH = os.path.join(HERE, "research_runner.log")

def find_exe(name):
    """Resolve a CLI installed via npm, robust to Task Scheduler's stripped env."""
    p = shutil.which(name) or shutil.which(name + ".cmd")
    if p:
        return p
    bases = [
        os.environ.get("APPDATA"),
        os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Roaming"),
        r"C:\Users\joris\AppData\Roaming",          # laatste vangnet (deze laptop)
    ]
    for base in bases:
        if base:
            cand = os.path.join(base, "npm", name + ".cmd")
            if os.path.exists(cand):
                return cand
    return None


RAILWAY = find_exe("railway")
CLAUDE = find_exe("claude")

LOCK_STALE_SEC = 600          # research mag lang duren
CLAUDE_TIMEOUT = 360          # max 6 min voor het onderzoek
REQ_RE = re.compile(r"RESEARCH_REQUEST id=(\d+) chat=(\d+)")

PROMPT = (
    "Doe diepgaand, ACTUEEL onderzoek met webzoekopdrachten naar de meest recente "
    "belastingontwikkelingen in Europa, met nadruk op Nederland, Luxemburg, Denemarken, "
    "Finland, Noorwegen en Zweden. Focus op: (1) wijzigingen in vennootschapsbelasting "
    "(CIT) tarieven, (2) BTW-tarieven, (3) nieuwe EU-richtlijnen of -lijsten (bv. "
    "niet-coöperatieve jurisdicties, ViDA, Pillar Two). Kijk vooral naar de laatste ~30 "
    "dagen. Geef per ontwikkeling: land/EU, wat er verandert, of het een VOORSTEL of "
    "AANGENOMEN is, de ingangsdatum indien bekend, en de bron met URL. Schrijf een "
    "beknopte samenvatting in het Nederlands met bullets, maximaal ~3000 tekens, "
    "geschikt voor Telegram. Geen inleiding of disclaimers — alleen de bevindingen."
)


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run(cmd, timeout, stdin_null=False):
    kwargs = {"cwd": HERE, "capture_output": True, "text": True,
              "timeout": timeout, "encoding": "utf-8", "errors": "replace"}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000          # CREATE_NO_WINDOW
    if stdin_null:
        kwargs["stdin"] = subprocess.DEVNULL
    try:
        r = subprocess.run(cmd, **kwargs)
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except Exception as e:  # noqa: BLE001
        return -1, "", str(e)


# ----------------------------------------------------------------- lock ------

def acquire_lock():
    if os.path.exists(LOCK_PATH):
        if time.time() - os.path.getmtime(LOCK_PATH) < LOCK_STALE_SEC:
            return False
    try:
        open(LOCK_PATH, "w").write(str(os.getpid()))
        return True
    except OSError:
        return False


def release_lock():
    try:
        os.remove(LOCK_PATH)
    except OSError:
        pass


# -------------------------------------------------------------- telegram -----

def tg_send(token, chat_id, text):
    # Plain text (geen parse_mode) — Claude-output kan < > & bevatten.
    for i in range(0, len(text), 3800):
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat_id, "text": text[i:i + 3800],
                                "disable_web_page_preview": "true"}, timeout=30)
        except Exception as e:  # noqa: BLE001
            log(f"telegram send fout: {e}")


# ----------------------------------------------------------------- state -----

def read_last():
    try:
        return int(open(LAST_PATH).read().strip())
    except (OSError, ValueError):
        return None


def write_last(v):
    try:
        open(LAST_PATH, "w").write(str(v))
    except OSError:
        pass


# ------------------------------------------------------------ pending req ----

def latest_request():
    """Return (id, chat_id) of the most recent RESEARCH_REQUEST in Railway logs."""
    if not RAILWAY or not os.path.exists(RAILWAY):
        log("railway CLI niet gevonden"); return None
    rc, out, err = run([RAILWAY, "logs", "-d", "--lines", "150"], timeout=60)
    if rc != 0:
        log(f"railway logs faalde: {(err or out)[:120]}"); return None
    found = None
    for line in out.splitlines():
        m = REQ_RE.search(line)
        if m:
            found = (int(m.group(1)), m.group(2))   # last match wins
    return found


# ------------------------------------------------------------ research -------

def do_research(token, chat_id):
    if not CLAUDE or not os.path.exists(CLAUDE):
        tg_send(token, chat_id, "⚠️ Claude CLI niet gevonden op de laptop.")
        return
    log("Claude deep-research gestart…")
    tg_send(token, chat_id, "🔎 Claude doet nu deep research… (kan ~1–3 min duren)")
    rc, out, err = run(
        [CLAUDE, "-p", PROMPT, "--allowed-tools", "WebSearch", "WebFetch",
         "--output-format", "text"],
        timeout=CLAUDE_TIMEOUT, stdin_null=True,
    )
    out = (out or "").strip()
    if rc != 0 or not out:
        msg = (err or out or "onbekende fout")[:300]
        log(f"claude faalde rc={rc}: {msg}")
        if "login" in msg.lower():
            tg_send(token, chat_id, "⚠️ Claude is niet ingelogd op de laptop. "
                                    "Draai eenmalig 'claude' en /login.")
        else:
            tg_send(token, chat_id, f"⚠️ Deep research mislukt: {msg}")
        return
    log(f"Claude klaar ({len(out)} tekens)")
    tg_send(token, chat_id, "🧠 Deep research (Claude) — tax-ontwikkelingen:\n\n" + out)


# ------------------------------------------------------------------ main -----

def main():
    if not acquire_lock():
        log("andere research-runner actief — overgeslagen"); return
    try:
        cfg = load_config()
        token = cfg.get("telegram_token", "").strip()
        if not token:
            log("geen telegram_token (config.local.json?)"); return

        req = latest_request()
        if not req:
            return                              # geen verzoek in de logs
        req_id, chat_id = req
        last = read_last()

        if last is None:
            write_last(req_id)                  # eerste keer: baseline, niet uitvoeren
            log(f"baseline gezet op id={req_id} (geen actie)")
            return
        if req_id <= last:
            return                              # al verwerkt
        log(f"nieuw verzoek id={req_id} chat={chat_id}")
        do_research(token, chat_id)
        write_last(req_id)
    finally:
        release_lock()


def loop(interval=60):
    """Persistent mode: poll every `interval` seconds. Started at logon from the
    Startup folder so it runs in the full user session (Task Scheduler strips the
    profile and then can't see AppData\\npm / Claude auth)."""
    log("research-runner loop gestart")
    while True:
        try:
            main()
        except Exception as e:  # noqa: BLE001
            log(f"loop fout: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    if "--once" in sys.argv:
        main()
    else:
        loop()
