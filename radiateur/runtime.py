"""Runtime helpers to bootstrap the MQTT infrastructure."""

from __future__ import annotations

import threading
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


def initialize() -> None:
    """Initialize MQTT client and background workers once."""

    global _initialized, _mqtt_client
    with _state_lock:
        if _initialized:
            return

        enregistrer_log("Démarrage du serveur")
        liste_initiale = {radiateur: "DEFAULT" for radiateur in MQTT_SETTINGS.devices}
        set_liste_etat(liste_initiale)

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
