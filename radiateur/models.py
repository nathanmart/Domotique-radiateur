"""File-based storage helpers for user-declared radiator devices."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
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
    ordered = sorted(devices, key=lambda device: device.name.lower())
    serialized = [device.to_json() for device in ordered]
    DEVICES_FILE_PATH.write_text(
        json.dumps(serialized, ensure_ascii=False, indent=4), encoding="utf-8"
    )


def get_device(name: str) -> RadiatorDevice | None:
    """Return the stored device matching ``name`` if available."""

    normalized = name.strip()
    if not normalized:
        return None

    for device in load_devices():
        if device.name == normalized:
            return device
    return None


def record_discovered_device(
    name: str, ip_address: str | None
) -> tuple[RadiatorDevice, bool]:
    """Register or update a device discovered on the local network."""

    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Le nom de l'appareil est requis.")

    sanitized_ip: str | None
    if isinstance(ip_address, str):
        sanitized_ip = ip_address.strip() or None
    else:
        sanitized_ip = None

    devices = load_devices()
    for index, existing in enumerate(devices):
        if existing.name == normalized_name:
            updated = replace(existing, ip_address=sanitized_ip)
            devices[index] = updated
            save_devices(devices)
            return updated, False

    record = RadiatorDevice(
        name=normalized_name,
        ip_address=sanitized_ip,
        added_at=datetime.now(TIMEZONE),
    )
    devices.append(record)
    save_devices(devices)
    return record, True


def rename_device(old_name: str, new_name: str) -> RadiatorDevice:
    """Rename an existing device and return the updated record."""

    normalized_old = old_name.strip()
    normalized_new = new_name.strip()
    if not normalized_old:
        raise ValueError("L'ancien nom est invalide.")
    if not normalized_new:
        raise ValueError("Le nouveau nom est requis.")

    devices = load_devices()
    for device in devices:
        if device.name == normalized_new and device.name != normalized_old:
            raise ValueError("Un appareil avec ce nom existe déjà.")

    updated_device: RadiatorDevice | None = None
    for index, device in enumerate(devices):
        if device.name == normalized_old:
            updated_device = RadiatorDevice(
                name=normalized_new,
                ip_address=device.ip_address,
                added_at=device.added_at,
            )
            devices[index] = updated_device
            break

    if updated_device is None:
        raise KeyError(normalized_old)

    save_devices(devices)
    return updated_device


def remove_device(name: str) -> bool:
    """Delete the device with the given name. Return ``True`` if removed."""

    normalized = name.strip()
    if not normalized:
        return False

    devices = load_devices()
    filtered = [device for device in devices if device.name != normalized]
    if len(filtered) == len(devices):
        return False

    save_devices(filtered)
    return True


def get_device_names() -> List[str]:
    """Return the list of registered device names."""

    return [device.name for device in load_devices()]
