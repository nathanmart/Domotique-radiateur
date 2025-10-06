"""Runtime helpers to bootstrap the MQTT infrastructure."""

from __future__ import annotations

import socket
import subprocess
import threading
import time
from typing import Optional

from .config import MQTT_SETTINGS
from .mqtt_client import MQTTClient
from .services import (
    enregistrer_log,
    maj_etat_selon_planning,
    set_liste_etat,
)

_state_lock = threading.Lock()
_initialized = False
_mqtt_client: Optional[MQTTClient] = None


def _can_connect() -> bool:
    """Return True when a TCP connection to the broker can be established."""

    try:
        with socket.create_connection(
            (MQTT_SETTINGS.host, MQTT_SETTINGS.port), timeout=1
        ):
            return True
    except OSError:
        return False


def _ensure_broker_running() -> None:
    """Start the MQTT broker when possible if it's not already up."""

    if _can_connect():
        return

    command = MQTT_SETTINGS.start_command
    if not command:
        return

    try:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # pragma: no cover - platform dependent
        enregistrer_log(
            "Impossible de démarrer le serveur MQTT automatiquement: %s" % exc
        )
        return

    deadline = time.time() + MQTT_SETTINGS.start_timeout
    while time.time() < deadline:
        if _can_connect():
            enregistrer_log(
                "Serveur MQTT démarré via la commande configurée"
            )
            return
        time.sleep(0.5)

    enregistrer_log(
        "Le serveur MQTT ne répond pas malgré la tentative de démarrage automatique"
    )


def initialize() -> None:
    """Initialize MQTT client and background workers once."""

    global _initialized, _mqtt_client
    with _state_lock:
        if _initialized:
            return

        enregistrer_log("Démarrage du serveur")
        liste_initiale = {radiateur: "DEFAULT" for radiateur in MQTT_SETTINGS.devices}
        set_liste_etat(liste_initiale)

        _ensure_broker_running()

        try:
            client = MQTTClient(
                MQTT_SETTINGS.host,
                MQTT_SETTINGS.port,
                MQTT_SETTINGS.log_file,
            )
            client.subscribe(MQTT_SETTINGS.topic)
            _mqtt_client = client
            enregistrer_log("Client MQTT connecté")
            threading.Thread(
                target=maj_etat_selon_planning,
                args=(client,),
                daemon=True,
            ).start()
        except Exception as exc:  # pragma: no cover - network failures during tests
            enregistrer_log(f"Impossible de joindre le serveur MQTT: {exc}")
            _mqtt_client = None

        _initialized = True


def get_mqtt_client() -> Optional[MQTTClient]:
    """Return the shared MQTT client instance when available."""

    return _mqtt_client


def runtime_ready() -> bool:
    """Indicate whether the runtime initialization has been attempted."""

    return _initialized


def get_cached_states():
    """Expose the mutable dictionary storing the devices state."""

    from .services import get_liste_etat

    return get_liste_etat()
