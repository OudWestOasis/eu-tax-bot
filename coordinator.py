# -*- coding: utf-8 -*-
"""
Coördinatie tussen laptop en cloud, zodat er nooit dubbel verstuurd wordt.

Idee:
  - De laptop ververst (als hij draait) een "heartbeat": een tijdstempel in een
    GitHub repo-variabele (LAPTOP_HEARTBEAT). Dat kost geen commits.
  - De cloud-runs lezen die heartbeat aan het begin. Is die vers (< 3 min) en
    draait de run NIET op de laptop, dan gaat de cloud die ronde stand-by.
  - De laptop draait altijd (doet zelf geen stand-by-check).

Onderscheid laptop/cloud via env-var RUN_LOCATION ("laptop" of "cloud").
De heartbeat-waarde komt in de cloud binnen via env LAPTOP_HEARTBEAT
(gevuld door de workflow met ${{ vars.LAPTOP_HEARTBEAT }}).
"""

import os
from datetime import datetime, timezone

HEARTBEAT_MAX_AGE = 180          # seconden: < 3 min = "laptop is actief"
CLOCK_SKEW_TOLERANCE = 120       # sta wat klokverschil toe (heartbeat 'in de toekomst')


def run_location():
    return (os.environ.get("RUN_LOCATION") or "cloud").strip().lower()


def heartbeat_now_iso():
    """Tijdstempel om de heartbeat mee te zetten (UTC, ISO-8601)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_heartbeat(value):
    if not value:
        return None
    value = value.strip()
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def heartbeat_age_seconds(value):
    dt = parse_heartbeat(value)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


def heartbeat_is_fresh(value, max_age=HEARTBEAT_MAX_AGE):
    age = heartbeat_age_seconds(value)
    if age is None:
        return False
    return -CLOCK_SKEW_TOLERANCE <= age <= max_age


def should_cloud_standby():
    """True = de cloud moet deze ronde niets doen (laptop neemt het over)."""
    if run_location() == "laptop":
        return False                      # de laptop draait altijd
    return heartbeat_is_fresh(os.environ.get("LAPTOP_HEARTBEAT", ""))
