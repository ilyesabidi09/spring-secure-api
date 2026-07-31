"""Chargement de la configuration YAML + variables d'environnement (.env)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).with_name("settings.yaml")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Charge settings.yaml. Les secrets (identifiants Tradovate) restent en env."""
    cfg_path = Path(path) if path else _CONFIG_PATH
    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    cfg["credentials"] = {
        "name": os.environ.get("TRADOVATE_USERNAME", ""),
        "password": os.environ.get("TRADOVATE_PASSWORD", ""),
        "app_id": os.environ.get("TRADOVATE_APP_ID", ""),
        "app_version": os.environ.get("TRADOVATE_APP_VERSION", "1.0"),
        "cid": os.environ.get("TRADOVATE_CID", ""),
        "sec": os.environ.get("TRADOVATE_SECRET", ""),
        "account_spec": os.environ.get("TRADOVATE_ACCOUNT_SPEC", ""),
        "account_id": int(os.environ.get("TRADOVATE_ACCOUNT_ID", "0") or 0),
    }
    return cfg
