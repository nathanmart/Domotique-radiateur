"""Application configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import pytz
from django.conf import settings


@dataclass(frozen=True)
class MQTTSettings:
    """Strongly typed container for MQTT related settings."""

    host: str
    port: int
    topic: str
    devices: List[str]
    log_file: Path


def _resolve_log_path(filename: str) -> Path:
    """Return the absolute path of a log file relative to the log directory."""

    path = Path(filename)
    if not path.is_absolute():
        path = Path(settings.LOG_DIRECTORY) / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


TIMEZONE = pytz.timezone(settings.APP_TIMEZONE)
APP_LOG_FILE = _resolve_log_path(settings.APP_LOG_FILE)
MQTT_LOG_FILE = _resolve_log_path(settings.MQTT_LOG_FILE)

MQTT_SETTINGS = MQTTSettings(
    host=settings.MQTT_BROKER_HOST,
    port=settings.MQTT_BROKER_PORT,
    topic=settings.MQTT_TOPIC,
    devices=settings.MQTT_DEVICES,
    log_file=MQTT_LOG_FILE,
)
