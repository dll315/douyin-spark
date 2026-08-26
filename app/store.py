import copy
import datetime
import json
import os
import threading
import uuid

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "data.json")

DEFAULT_MESSAGES = [
    "早上好，来续火花啦 🔥",
    "今日份火花打卡 ✅",
    "别让咱们的火花灭了，快冒个泡~",
]

DEFAULT_DATA = {
    "settings": {
        "hour": 9,
        "minute": 0,
        "jitter_minutes": 20,
        "headless": True,
        "default_messages": DEFAULT_MESSAGES,
    },
    "contacts": [],
    "logs": [],
}

_lock = threading.Lock()


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_id():
    return uuid.uuid4().hex[:12]


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load():
    with _lock:
        _ensure_dir()
        if not os.path.exists(DATA_FILE):
            return copy.deepcopy(DEFAULT_DATA)
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = copy.deepcopy(DEFAULT_DATA)
        merged.update({k: v for k, v in data.items() if k != "settings"})
        merged["settings"] = {**DEFAULT_DATA["settings"], **data.get("settings", {})}
        return merged


def save(data):
    with _lock:
        _ensure_dir()
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)


def add_log(level, text, limit=300):
    data = load()
    data["logs"].insert(0, {"time": now_str(), "level": level, "text": str(text)})
    data["logs"] = data["logs"][:limit]
    save(data)
