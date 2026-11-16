"""Ablage für Einstellungen, Zwischenspeicher und Downloads unter %LOCALAPPDATA%\\Tool-Hub."""
import json
import os

from . import APP_NAME


def data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def downloads_dir():
    path = os.path.join(data_dir(), "downloads")
    os.makedirs(path, exist_ok=True)
    return path


def _path(name):
    return os.path.join(data_dir(), name)


def load(name, default):
    try:
        with open(_path(name), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def save(name, data):
    target = _path(name)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, target)
