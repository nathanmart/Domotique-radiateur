"""Standalone MQTT simulator for virtual radiators.

This script acts as a fake fleet of connected radiators able to react to
messages sent by the Django application.  It subscribes to the configured MQTT
topic, keeps an in-memory cache of the devices state and answers to state
requests.  Whenever a command such as ``COMFORT`` or ``ECO`` is received, the
simulated radiator updates its internal state and acknowledges the change by
publishing the new value back to the broker.

Run the script manually, for example::

    python simulator/fake_radiators.py --devices Cuisine Chambre Salon

The MQTT related arguments default to the same values as the Django project
configuration and can therefore be omitted in most development setups.
"""

from __future__ import annotations

import argparse
import ast
import os
import signal
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from dotenv import load_dotenv
import paho.mqtt.client as mqtt


DEFAULT_ENV_PATHS: List[Path] = [
    Path(__file__).resolve().parent.parent / ".env",
    Path(__file__).resolve().parent / ".env",
]


def _load_default_env() -> None:
    """Load environment variables from the project level .env file if present."""

    for env_path in DEFAULT_ENV_PATHS:
        if env_path.exists():
            load_dotenv(env_path)
            break


def _split_devices(raw: str) -> List[str]:
    """Return the list of device names extracted from a comma separated string."""

    return [device.strip() for device in raw.split(",") if device.strip()]


@dataclass
class SimulatorSettings:
    """Configuration container for the simulator."""

    host: str
    port: int
    topic: str
    devices: List[str] = field(default_factory=list)
    initial_state: str = "DEFAULT"
    verbose: bool = False


class RadiatorSimulator:
    """MQTT helper able to mimic a set of connected radiators."""

    def __init__(self, settings: SimulatorSettings) -> None:
        if not settings.devices:
            raise ValueError("Au moins un radiateur doit être fourni")

        self.settings = settings
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        self._lock = threading.Lock()
        self._running = threading.Event()
        self._states: Dict[str, str] = {
            name: settings.initial_state for name in settings.devices
        }

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Connect to the MQTT broker and start the background network loop."""

        self.client.connect(self.settings.host, self.settings.port)
        self.client.subscribe(self.settings.topic)
        self.client.loop_start()
        self._running.set()
        if self.settings.verbose:
            self._log(
                "Simulation démarrée. Radiateurs: %s",
                ", ".join(self.settings.devices),
            )

    def stop(self) -> None:
        """Stop the MQTT client loop and disconnect gracefully."""

        if not self._running.is_set():
            return
        self._running.clear()
        self.client.loop_stop()
        try:
            self.client.disconnect()
        finally:
            if self.settings.verbose:
                self._log("Simulation arrêtée")

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------
    def _on_connect(self, client, userdata, flags, rc):  # type: ignore[override]
        if rc != 0:
            self._log("Connexion MQTT échouée (code %s)", rc)
        elif self.settings.verbose:
            self._log(
                "Connecté au broker MQTT %s:%s sur le topic '%s'",
                self.settings.host,
                self.settings.port,
                self.settings.topic,
            )

    def _on_message(self, client, userdata, message):  # type: ignore[override]
        payload = message.payload.decode("utf-8", errors="replace")
        parsed = self._parse_payload(payload)
        if not parsed:
            self._log("Message ignoré: %s", payload)
            return

        command = str(parsed.get("COMMAND", "")).strip()
        if not command:
            return

        targets = self._resolve_targets(parsed.get("TO"))
        if not targets:
            return

        if command.upper() == "STATE":
            for target in targets:
                self._publish_state(target, parsed.get("FROM"))
            return

        for target in targets:
            self._apply_state_change(target, command, parsed.get("FROM"))

    # ------------------------------------------------------------------
    # Message handling helpers
    # ------------------------------------------------------------------
    def _parse_payload(self, payload: str) -> Optional[Dict[str, object]]:
        """Attempt to convert the textual payload to a dictionary."""

        try:
            parsed = ast.literal_eval(payload)
        except (ValueError, SyntaxError):
            return None

        if not isinstance(parsed, dict):
            return None
        return parsed

    def _resolve_targets(self, raw_target) -> List[str]:
        """Determine which radiators are addressed by a message."""

        if isinstance(raw_target, str):
            target = raw_target.strip()
            if target in {"ALL", "*"}:
                return list(self._states.keys())
            if target in self._states:
                return [target]
        return []

    def _apply_state_change(self, target: str, new_state: str, sender: object) -> None:
        """Update a radiator state and notify the broker about the change."""

        with self._lock:
            previous = self._states.get(target, self.settings.initial_state)
            self._states[target] = new_state

        if self.settings.verbose:
            self._log(
                "Commande reçue pour %s: %s (ancien état: %s)",
                target,
                new_state,
                previous,
            )

        self._publish_state(target, sender)

    def _publish_state(self, target: str, sender: object) -> None:
        """Publish the current state of a radiator back to the MQTT broker."""

        with self._lock:
            state = self._states.get(target, self.settings.initial_state)

        destination = "Django"
        if isinstance(sender, str) and sender:
            destination = sender

        message = {
            "FROM": target,
            "TO": destination,
            "COMMAND": state,
        }
        self.client.publish(self.settings.topic, str(message))
        if self.settings.verbose:
            self._log(
                "État publié pour %s -> %s: %s",
                target,
                destination,
                state,
            )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _log(self, message: str, *args: object) -> None:
        """Print a formatted log line to stdout."""

        print(message % args if args else message)


def _build_argument_parser() -> argparse.ArgumentParser:
    """Return the command line parser used to launch the simulator."""

    parser = argparse.ArgumentParser(description="Simulateur MQTT de radiateurs")
    parser.add_argument(
        "--host",
        default=os.getenv("MQTT_BROKER_HOST", "127.0.0.1"),
        help="Adresse du broker MQTT (défaut: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MQTT_BROKER_PORT", "1883")),
        help="Port du broker MQTT (défaut: %(default)s)",
    )
    parser.add_argument(
        "--topic",
        default=os.getenv("MQTT_TOPIC", "test"),
        help="Topic écouté et utilisé pour répondre (défaut: %(default)s)",
    )
    parser.add_argument(
        "--devices",
        nargs="*",
        default=_split_devices(os.getenv("MQTT_DEVICES", "")),
        help=(
            "Liste des radiateurs simulés. Par défaut la variable d'environnement "
            "MQTT_DEVICES est utilisée."
        ),
    )
    parser.add_argument(
        "--initial-state",
        default=os.getenv("SIMULATOR_INITIAL_STATE", "DEFAULT"),
        help="État initial attribué à chaque radiateur (défaut: %(default)s)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Afficher les messages détaillés de la simulation",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    """Entry point executed when running the module as a script."""

    _load_default_env()
    parser = _build_argument_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    settings = SimulatorSettings(
        host=args.host,
        port=args.port,
        topic=args.topic,
        devices=list(args.devices),
        initial_state=args.initial_state,
        verbose=args.verbose,
    )

    simulator = RadiatorSimulator(settings)

    stop_event = threading.Event()

    def _handle_signal(signum, frame):  # noqa: ANN001 - Signature imposed by signal
        simulator.stop()
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    simulator.start()
    stop_event.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
