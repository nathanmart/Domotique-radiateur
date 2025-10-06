"""Wrapper around ``paho.mqtt.client`` used by the application."""

from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import List, Tuple

import paho.mqtt.client as mqtt

from .config import TIMEZONE


class MQTTClient:
    """Minimal MQTT client tailored for the project needs."""

    def __init__(self, broker_address: str, broker_port: int = 1883, log_path=None) -> None:
        self.client = mqtt.Client()
        self.client.connect(broker_address, broker_port)
        self.message_recu: List[Tuple[float, str]] = []
        self._log_path = log_path
        self._lock = Lock()

    def publish(self, message: str, topic: str) -> None:
        self.client.publish(topic, message)

    def subscribe(self, topic: str) -> None:
        self.client.on_message = self.on_message
        self.client.subscribe(topic)
        self.client.loop_start()

    def on_message(self, client, userdata, message) -> None:  # type: ignore[override]
        payload = message.payload.decode("utf-8")
        with self._lock:
            self.message_recu.append((datetime.now(TIMEZONE).timestamp(), payload))
        if self._log_path:
            timestamp = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
            with open(self._log_path, "a", encoding="utf-8") as file:
                file.write(f"{timestamp} : {payload}\n")

    def unsubscribe(self) -> int:
        self.client.loop_stop()
        return 1

    def get_message_recu(self) -> List[Tuple[float, str]]:
        with self._lock:
            return list(self.message_recu)

    def reset_message_recu(self) -> int:
        with self._lock:
            self.message_recu = []
        return 1
