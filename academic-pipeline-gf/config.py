"""Configuration loader."""

import os
from pathlib import Path
from typing import Any
import yaml
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Override secrets from env
    if config.get("alerts", {}).get("telegram", {}).get("enabled"):
        config["alerts"]["telegram"]["bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN", "")
        config["alerts"]["telegram"]["chat_id"] = os.getenv("TELEGRAM_CHAT_ID", "")

    if config.get("alerts", {}).get("email", {}).get("enabled"):
        config["alerts"]["email"]["smtp_user"] = os.getenv("SMTP_USER", "")
        config["alerts"]["email"]["smtp_pass"] = os.getenv("SMTP_PASS", "")
        config["alerts"]["email"]["from_email"] = os.getenv("FROM_EMAIL", "")
        config["alerts"]["email"]["to_email"] = os.getenv("TO_EMAIL", "")

    return config


CONFIG = load_config()