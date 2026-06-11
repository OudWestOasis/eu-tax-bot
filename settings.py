# -*- coding: utf-8 -*-
"""
Central config loader.

Secrets are read from environment variables first (GitHub Actions sets these
from repository Secrets), with config.json as a local fallback. This way no real
token is ever committed: config.json ships with empty secret fields.

Env vars:
  TELEGRAM_TOKEN    - bot token from BotFather
  TELEGRAM_CHAT_ID  - destination chat id for pushed messages
"""

import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
LOCAL_CONFIG_PATH = os.path.join(HERE, "config.local.json")


def load_config():
    with open(CONFIG_PATH, encoding="utf-8-sig") as f:  # utf-8-sig tolerates a BOM
        cfg = json.load(f)

    # Local secret overrides (gitignored, never committed). Used on the laptop
    # so it has the real token/chat without putting them in the repo.
    # Precedence: environment > config.local.json > config.json
    if os.path.exists(LOCAL_CONFIG_PATH):
        try:
            with open(LOCAL_CONFIG_PATH, encoding="utf-8-sig") as f:
                cfg.update({k: v for k, v in json.load(f).items() if v not in ("", None)})
        except (OSError, json.JSONDecodeError):
            pass

    # Environment overrides config.json (so secrets stay out of the repo).
    cfg["telegram_token"] = (
        os.environ.get("TELEGRAM_TOKEN") or cfg.get("telegram_token", "")
    ).strip()
    cfg["chat_id"] = str(
        os.environ.get("TELEGRAM_CHAT_ID") or cfg.get("chat_id", "")
    ).strip()
    # Recipient for the weekly e-mail (not a secret; env may override).
    cfg["email_to"] = (
        os.environ.get("EMAIL_TO") or cfg.get("email_to", "")
    ).strip()
    return cfg
