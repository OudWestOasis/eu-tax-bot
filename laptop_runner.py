# -*- coding: utf-8 -*-
"""
Laptop-runner — draait ~elke minuut via Windows Taakplanner.

Per ronde:
  1. lock pakken (geen overlappende instances)
  2. git pull --rebase  -> nieuwste gedeelde state ophalen (best effort)
  3. heartbeat verversen in de GitHub repo-variabele LAPTOP_HEARTBEAT
     -> ALLEEN als dit lukt gaan we verder met sturen. Zo weet de cloud dat de
        laptop actief is en gaat die stand-by => nooit dubbel.
  4. als "laptop" (RUN_LOCATION=laptop):
       - poller.main()  -> commando's beantwoorden (elke ronde)
       - tax_monitor.main() -> nieuws-scan, maar GETHROTTLED (niet elke minuut)
  5. gewijzigde state terug pushen (best effort)

Robuust: bij geen internet / git-fout / gh-fout slaan we netjes over en crashen
we niet. Secrets komen uit config.local.json (gitignored) via settings.py.
"""

import os
import sys
import time
import shutil
import subprocess
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "OudWestOasis/eu-tax-bot"
HEARTBEAT_VAR = "LAPTOP_HEARTBEAT"
LOCK_PATH = os.path.join(HERE, "runner.lock")
LAST_SCAN_PATH = os.path.join(HERE, "last_scan.txt")
RUN_LOG = os.path.join(HERE, "laptop_runner.log")

SCAN_INTERVAL_SEC = 600          # nieuws-scan hooguit elke 10 min (niet elke minuut)
LOCK_STALE_SEC = 240             # lock ouder dan dit = vorige run vastgelopen


def log(msg):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line)
    try:
        with open(RUN_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def gh_path():
    p = shutil.which("gh")
    if p:
        return p
    fallback = r"C:\Program Files\GitHub CLI\gh.exe"
    return fallback if os.path.exists(fallback) else None


def run(cmd, timeout=60):
    """Run a command; return (ok, output). Never raises.

    On Windows we pass CREATE_NO_WINDOW so git/gh don't flash a console window
    when this runner is launched windowless via pythonw.
    """
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                           timeout=timeout, **kwargs)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# ----------------------------------------------------------------- lock ------

def acquire_lock():
    if os.path.exists(LOCK_PATH):
        age = time.time() - os.path.getmtime(LOCK_PATH)
        if age < LOCK_STALE_SEC:
            return False                       # another run is active
        log(f"stale lock ({int(age)}s) — overriding")
    try:
        with open(LOCK_PATH, "w") as f:
            f.write(str(os.getpid()))
        return True
    except OSError:
        return False


def release_lock():
    try:
        os.remove(LOCK_PATH)
    except OSError:
        pass


# --------------------------------------------------------------- git sync ----

def git_pull():
    ok, out = run(["git", "pull", "--rebase", "--autostash", "origin", "main"])
    log(f"git pull: {'ok' if ok else 'SKIPPED'} ({out.splitlines()[-1] if out else ''})")
    return ok


def git_push_state():
    ok, out = run(["git", "status", "--porcelain", "state.json"])
    if not out.strip():
        return                                 # nothing changed -> no push (no spam)
    run(["git", "add", "state.json"])
    run(["git", "commit", "-m", "Update dedup state (laptop) [skip ci]"])
    run(["git", "pull", "--rebase", "--autostash", "origin", "main"])
    ok, out = run(["git", "push", "origin", "main"])
    log(f"git push state: {'ok' if ok else 'FAILED'}")


# -------------------------------------------------------------- heartbeat ----

def refresh_heartbeat():
    """Set LAPTOP_HEARTBEAT = now via gh. Returns True on success."""
    gh = gh_path()
    if not gh:
        log("gh niet gevonden — heartbeat NIET gezet (laptop stuurt niet)")
        return False
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ok, out = run([gh, "variable", "set", HEARTBEAT_VAR, "--repo", REPO, "--body", now])
    if ok:
        log(f"heartbeat gezet: {now}")
    else:
        log(f"heartbeat zetten MISLUKT: {out[:120]}")
    return ok


# ------------------------------------------------------------------ scan -----

def scan_due():
    try:
        with open(LAST_SCAN_PATH) as f:
            last = float(f.read().strip())
    except (OSError, ValueError):
        return True
    return (time.time() - last) >= SCAN_INTERVAL_SEC


def mark_scan():
    try:
        with open(LAST_SCAN_PATH, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


# ------------------------------------------------------------------ main -----

def main():
    if not acquire_lock():
        log("andere runner actief — deze ronde overgeslagen")
        return
    try:
        os.environ["RUN_LOCATION"] = "laptop"   # we always run, never stand by

        git_pull()                              # (a) nieuwste gedeelde state

        if not refresh_heartbeat():             # (b) claim het 'actief' zijn
            # Geen heartbeat => we kunnen niet garanderen dat de cloud stand-by
            # gaat. Dus NIET sturen (voorkomt dubbel). Cloud handelt het af.
            log("geen heartbeat -> niets sturen deze ronde")
            return

        # (c) commando's — elke ronde
        try:
            import poller
            poller.main()
        except SystemExit:
            log("poller: SystemExit (config?)")
        except Exception as e:  # noqa: BLE001
            log(f"poller fout: {e}")

        # (c) nieuws-scan — gethrottled
        if scan_due():
            try:
                import tax_monitor
                tax_monitor.main()
                mark_scan()
                log("scan gedraaid")
            except SystemExit:
                log("scan: SystemExit (config?)")
            except Exception as e:  # noqa: BLE001
                log(f"scan fout: {e}")
        else:
            log("scan nog niet aan de beurt (throttle)")

        git_push_state()                        # (d) gewijzigde state terug
    finally:
        release_lock()
    log("ronde klaar")


if __name__ == "__main__":
    main()
