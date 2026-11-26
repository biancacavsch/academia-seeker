"""Configuration loader.

Precedência: config.yaml → ui_settings.yaml (overlay editável pela webview)
→ variáveis de ambiente (.env, só para segredos).
"""

import os
from pathlib import Path
from typing import Any
import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yaml"
UI_SETTINGS_PATH = BASE_DIR / "ui_settings.yaml"
ACTIVE_SURVEYS_PATH = BASE_DIR / "active_surveys.yaml"


def deep_merge(base: dict, override: dict) -> dict:
    """Mescla `override` sobre `base` recursivamente, sem mutar os originais."""
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_ui_settings() -> dict[str, Any]:
    """Lê o overlay gravado pela webview. Arquivo ausente = sem ajustes."""
    if not UI_SETTINGS_PATH.exists():
        return {}
    try:
        with open(UI_SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        # Nunca deixa uma edição inválida derrubar o pipeline.
        return {}


def load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config = deep_merge(config, load_ui_settings())

    # Limite rígido: nenhuma lista de termos/consulta passa de 30 itens,
    # mesmo quando o valor vem do config.yaml versionado.
    try:
        from limits import enforce_limits
        enforce_limits(config)
    except Exception:
        pass

    # Override secrets from env (sempre por último)
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


def reload_config() -> dict[str, Any]:
    """Recarrega CONFIG em memória (mantém o mesmo objeto importado por outros módulos)."""
    CONFIG.clear()
    CONFIG.update(load_config())
    return CONFIG
