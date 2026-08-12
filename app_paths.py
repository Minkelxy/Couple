"""统一应用数据目录：迁移到 Windows %APPDATA%\\CoupleSuite，为 exe 打包奠基。"""
import os
import json
from pathlib import Path

from common_utils import log_warning

APP_NAME = "CoupleSuite"
APP_ROOT = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
CONFIG_DIR = APP_ROOT / "config"
DATA_DIR = APP_ROOT / "data"        # 信箱数据
IMAGES_DIR = APP_ROOT / "images"    # 相框默认图片目录
CACHE_DIR = APP_ROOT / "cache"
LOGS_DIR = APP_ROOT / "logs"
SUITE_CONFIG = CONFIG_DIR / "suite.json"
# 四大新模块数据目录
CHECKIN_DIR = APP_ROOT / "checkin"    # 打卡日历
MOVIES_DIR = APP_ROOT / "movies"      # 影视追剧
TRAVEL_DIR = APP_ROOT / "travel"      # 旅行地图


def ensure_dirs():
    for d in (APP_ROOT, CONFIG_DIR, DATA_DIR, IMAGES_DIR, CACHE_DIR, LOGS_DIR,
              CHECKIN_DIR, MOVIES_DIR, TRAVEL_DIR):
        d.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "letters").mkdir(exist_ok=True)
    (MOVIES_DIR / "posters").mkdir(exist_ok=True)
    (TRAVEL_DIR / "photos").mkdir(exist_ok=True)
    (CHECKIN_DIR / "images").mkdir(exist_ok=True)


def is_first_run():
    return not SUITE_CONFIG.exists()


def load_suite():
    if not SUITE_CONFIG.exists():
        return {}
    try:
        return json.loads(SUITE_CONFIG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log_warning("套件配置加载失败，返回空: %s", e)
        return {}


def save_suite(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SUITE_CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def update_suite(**kwargs):
    data = load_suite()
    data.update(kwargs)
    save_suite(data)
    return data
