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


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)

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
