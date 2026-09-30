"""환경변수(.env)와 설정 파일(config/settings.json) 로딩."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
TEMPLATE_DIR = DATA_DIR / "templates"
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"
SETTINGS_PATH = ROOT / "config" / "settings.json"
PROMPT_DIR = ROOT / "app" / "llm" / "prompts"

load_dotenv(ROOT / ".env")

DEFAULT_SETTINGS = {
    "matching": {
        "weights": {"purpose": 30, "trl": 20, "scale": 15, "capability": 20, "bonus": 15},
        "llm_reason_top_n": 10,
    },
    "collect": {
        "interval_hours": 24,
        "auto_on_open": True,
        "sources": ["bizinfo", "kstartup"],
        "bizinfo": {"searchCnt": 100, "hashtags": ""},
        "kstartup": {"perPage": 100, "pages": 2},
    },
    "interest": {"regions": [], "hashtags": []},
    "alerts": {"deadline_days": [14, 7, 3], "document_expiry_days": 30, "recipients": []},
    "llm": {"model": "claude-opus-5-5", "effort": "high", "use_fallbacks": True},
}


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def database_url() -> str:
    return env("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'app.db'}"


def _merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return _merge(DEFAULT_SETTINGS, json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
    return deepcopy(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
