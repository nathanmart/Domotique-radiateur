"""File-based storage helpers for user-declared radiator devices."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

from .config import TIMEZONE

DEVICES_FILE_PATH = Path(__file__).resolve().parent / "templates" / "devices.json"


@dataclass
class RadiatorDevice:
    """Lightweight representation of a user-declared ESP8266 radiator."""

    name: str
    ip_address: str | None
    added_at: datetime

    def to_json(self) -> dict[str, str | None]:
        """Serialize the device as a JSON-compatible dictionary."""

        return {
            "name": self.name,
            "ip_address": self.ip_address,
            "added_at": self.added_at.isoformat(),
        }

    @classmethod
    def from_json(cls, payload: object) -> "RadiatorDevice" | None:
        """Create a device from a raw JSON payload, returning None if invalid."""

        if not isinstance(payload, dict):
            return None

        raw_name = payload.get("name")
        if not isinstance(raw_name, str):
            return None
        name = raw_name.strip()
        if not name:
            return None

        raw_ip = payload.get("ip_address")
        if raw_ip in (None, ""):
            ip_address: str | None = None
        elif isinstance(raw_ip, str):
            ip_address = raw_ip.strip() or None
        else:
            return None

        raw_added_at = payload.get("added_at")
        if isinstance(raw_added_at, str):
            try:
                added_at = datetime.fromisoformat(raw_added_at)
            except ValueError:
                added_at = datetime.now(TIMEZONE)
        else:
            added_at = datetime.now(TIMEZONE)

        if added_at.tzinfo is None:
            added_at = TIMEZONE.localize(added_at)
        else:
            added_at = added_at.astimezone(TIMEZONE)

        return cls(name=name, ip_address=ip_address, added_at=added_at)


def load_devices() -> List[RadiatorDevice]:
    """Return the list of user-declared devices stored on disk."""

    if not DEVICES_FILE_PATH.exists():
        return []

    try:
        raw = json.loads(DEVICES_FILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(raw, list):
        return []

    devices: List[RadiatorDevice] = []
    for payload in raw:
        device = RadiatorDevice.from_json(payload)
        if device is not None:
            devices.append(device)

    devices.sort(key=lambda device: device.name.lower())
    return devices


def save_devices(devices: Iterable[RadiatorDevice]) -> None:
    """Persist the given device collection to disk."""

    DEVICES_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    serialized = [device.to_json() for device in devices]
    DEVICES_FILE_PATH.write_text(
        json.dumps(serialized, ensure_ascii=False, indent=4), encoding="utf-8"
    )


def add_device(name: str, ip_address: str | None) -> RadiatorDevice:
    """Register a new device and return the resulting record."""

    devices = load_devices()
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Le nom de l'appareil est requis.")

    for existing in devices:
        if existing.name == normalized_name:
            raise ValueError("Un appareil avec ce nom existe déjà.")

    sanitized_ip: str | None
    if isinstance(ip_address, str):
        sanitized_ip = ip_address.strip() or None
    else:
        sanitized_ip = None

    record = RadiatorDevice(
        name=normalized_name,
        ip_address=sanitized_ip,
        added_at=datetime.now(TIMEZONE),
    )

    devices.append(record)
    save_devices(devices)
    return record


def get_device_names() -> List[str]:
    """Return the list of registered device names."""

    return [device.name for device in load_devices()]
