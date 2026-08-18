"""Centralized application data paths and suite configuration storage."""
from __future__ import annotations

import os
from pathlib import Path

from common_utils import AtomicJsonStore

APP_NAME = "CoupleSuite"
APP_ROOT = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
CONFIG_DIR = APP_ROOT / "config"
DATA_DIR = APP_ROOT / "data"
IMAGES_DIR = APP_ROOT / "images"
CACHE_DIR = APP_ROOT / "cache"
LOGS_DIR = APP_ROOT / "logs"
SUITE_CONFIG = CONFIG_DIR / "suite.json"
CHECKIN_DIR = APP_ROOT / "checkin"
MOVIES_DIR = APP_ROOT / "movies"
TRAVEL_DIR = APP_ROOT / "travel"

_SUITE_STORE = AtomicJsonStore(SUITE_CONFIG, {})


def ensure_dirs():
    for directory in (
        APP_ROOT,
        CONFIG_DIR,
        DATA_DIR,
        IMAGES_DIR,
        CACHE_DIR,
        LOGS_DIR,
        CHECKIN_DIR,
        MOVIES_DIR,
        TRAVEL_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "letters").mkdir(exist_ok=True)
    (MOVIES_DIR / "posters").mkdir(exist_ok=True)
    (TRAVEL_DIR / "photos").mkdir(exist_ok=True)
    (CHECKIN_DIR / "images").mkdir(exist_ok=True)


def is_first_run():
    return not SUITE_CONFIG.exists()


def load_suite():
    data = _SUITE_STORE.load()
    return data if isinstance(data, dict) else {}


def save_suite(data: dict):
    _SUITE_STORE.save(data)


def update_suite(**kwargs):
    return _SUITE_STORE.update(**kwargs)
