"""Business logic for radiator scheduling and MQTT communication."""

from __future__ import annotations

import ast
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List

from .config import APP_LOG_FILE, MQTT_SETTINGS, TIMEZONE
from .models import get_device_names


_liste_etat: Dict[str, str] = {}

OPTIONS_FILE_PATH = Path(__file__).resolve().parent / "templates" / "options.json"


def get_all_radiator_names() -> List[str]:
    """Return the union of configured and user-declared radiators."""

    base = [name.strip() for name in MQTT_SETTINGS.devices if name.strip()]
    seen = {name for name in base}

    extras = get_device_names()

    for extra in extras:
        if extra and extra not in seen:
            base.append(extra)
            seen.add(extra)

    return base


def _ensure_state_entries() -> None:
    """Ensure the shared state dictionary tracks every known radiator."""

    for radiator in get_all_radiator_names():
        _liste_etat.setdefault(radiator, "DEFAULT")


def _default_disabled_states() -> Dict[str, bool]:
    """Return the default disabled state for each configured radiator."""

    return {radiator: False for radiator in get_all_radiator_names()}


def load_disabled_states() -> Dict[str, bool]:
    """Load the per-radiator disabled configuration from disk."""

    defaults = _default_disabled_states()
    if not OPTIONS_FILE_PATH.exists():
        return defaults

    try:
        raw = json.loads(OPTIONS_FILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults

    if not isinstance(raw, dict):
        return defaults

    for radiator, value in raw.items():
        if radiator in defaults:
            defaults[radiator] = bool(value)

    return defaults


def save_disabled_states(states: Dict[str, bool]) -> Dict[str, bool]:
    """Persist the disabled map to disk and return the sanitized structure."""

    sanitized = _default_disabled_states()
    for radiator, value in states.items():
        if radiator in sanitized:
            sanitized[radiator] = bool(value)

    OPTIONS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPTIONS_FILE_PATH.write_text(
        json.dumps(sanitized, ensure_ascii=False, indent=4), encoding="utf-8"
    )
    return sanitized


def update_disabled_state(radiator: str, disabled: bool) -> Dict[str, bool]:
    """Update and persist the disabled flag for a specific radiator."""

    states = load_disabled_states()
    if radiator not in states:
        raise KeyError(radiator)

    states[radiator] = bool(disabled)
    return save_disabled_states(states)


def set_liste_etat(liste: Dict[str, str]) -> None:
    """Register the shared dictionary used to track device states."""

    global _liste_etat
    _liste_etat = liste


def get_liste_etat() -> Dict[str, str]:
    """Expose the current state of the radiators."""

    _ensure_state_entries()
    return _liste_etat


def enregistrer_log(message: str, fichier: Path | None = None) -> None:
    """Persist an application log entry."""

    log_file = fichier or APP_LOG_FILE
    timestamp = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {message}\n")


def envoyer_changement_etat_mqtt(
    mode: str, mqtt_client, liste_radiateur: Iterable[str] | None = None
) -> Dict[str, str] | None:
    """Send the desired mode to the selected radiators via MQTT.

    The function honours the disabled configuration and forces the ECO mode
    when a radiator has been deactivated from the options page.
    """

    liste_radiateur = list(liste_radiateur or get_all_radiator_names())
    if not liste_radiateur:
        return {}

    if not mqtt_client:
        enregistrer_log("Aucun client MQTT disponible pour envoyer le changement d'état")
        return None

    disabled_map = load_disabled_states()
    applied_modes: Dict[str, str] = {}

    _ensure_state_entries()

    for appareil in liste_radiateur:
        forced_mode = "ECO" if disabled_map.get(appareil) else mode
        message = {
            "FROM": "Django",
            "TO": appareil,
            "COMMAND": forced_mode,
        }
        mqtt_client.publish(str(message), MQTT_SETTINGS.topic)
        applied_modes[appareil] = forced_mode
        _liste_etat[appareil] = forced_mode
        enregistrer_log(f"Modification état: {appareil} --> {forced_mode}")

    return applied_modes


WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _sanitize_schedule(payload: object) -> Dict[str, List[Dict[str, str]]]:
    """Return a predictable structure from the raw JSON payload."""

    schedule: Dict[str, List[Dict[str, str]]] = {day: [] for day in WEEKDAYS}
    if not isinstance(payload, dict):
        return schedule

    for day, entries in payload.items():
        if day not in schedule or not isinstance(entries, list):
            continue

        sanitized_entries: List[Dict[str, str]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            start = entry.get("start")
            end = entry.get("end")
            if isinstance(start, str) and isinstance(end, str):
                sanitized_entries.append({"start": start, "end": end})

        schedule[day] = sanitized_entries

    return schedule


def _parse_slot(time_str: str, reference: datetime) -> datetime | None:
    """Convert an HH:MM (or 24:00) string to an aware datetime."""

    if time_str == "24:00":
        base = reference.replace(hour=0, minute=0, second=0, microsecond=0)
        return base + timedelta(days=1)

    try:
        parsed = datetime.strptime(time_str, "%H:%M")
    except ValueError:
        return None

    return reference.replace(
        hour=parsed.hour,
        minute=parsed.minute,
        second=0,
        microsecond=0,
    )


def maj_etat_selon_planning(mqtt_client) -> None:
    """Update radiator states according to the planning definition."""

    if not mqtt_client:
        return

    last_minute = datetime.now(TIMEZONE) - timedelta(minutes=1)
    planning_path = Path(__file__).resolve().parent / "templates" / "data.json"
    if not planning_path.exists():
        enregistrer_log(f"Fichier de planning introuvable: {planning_path}")
        return

    while True:
        heure_actuelle = datetime.now(TIMEZONE)
        if heure_actuelle.minute != last_minute.minute:
            try:
                data = json.loads(planning_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}

            schedule = _sanitize_schedule(data)
            weekday = WEEKDAYS[heure_actuelle.weekday()]
            entries = schedule.get(weekday, [])

            current_time = heure_actuelle.replace(second=0, microsecond=0)
            for entry in entries:
                start_time = _parse_slot(entry.get("start", ""), current_time)
                end_time = _parse_slot(entry.get("end", ""), current_time)

                if not start_time or not end_time:
                    continue

                # Convert the parsed timestamps to the configured timezone
                if start_time.tzinfo is None:
                    start_time = TIMEZONE.localize(start_time)
                if end_time.tzinfo is None:
                    end_time = TIMEZONE.localize(end_time)

                if end_time == current_time:
                    enregistrer_log("Depuis planning --> ECO")
                    envoyer_changement_etat_mqtt("ECO", mqtt_client)
                elif start_time == current_time:
                    enregistrer_log("Depuis planning --> COMFORT")
                    envoyer_changement_etat_mqtt("COMFORT", mqtt_client)

            last_minute = heure_actuelle
            time.sleep(30)

        time.sleep(10)


def boucle_demander_etat_appareil(
    mqtt_client,
    nb_try: int = 1,
    liste_radiateur: Iterable[str] | None = None,
    delai: int = 15,
) -> None:
    """Continuously request device states at a fixed interval."""

    liste_radiateur = list(liste_radiateur or get_all_radiator_names())
    if not mqtt_client:
        enregistrer_log("Aucun client MQTT disponible pour interroger les appareils")
        return

    while True:
        demander_etat_au_appareil(mqtt_client, nb_try, liste_radiateur)
        time.sleep(delai)


def demander_etat_au_appareil(
    mqtt_client,
    nb_try: int = 1,
    liste_radiateur: Iterable[str] | None = None,
    timeout: float = 2.0,
):
    """Request the state of each radiator and update the shared cache."""

    if not mqtt_client:
        enregistrer_log("Aucun client MQTT disponible pour demander l'état des appareils")
        return 0

    liste_radiateur = list(liste_radiateur or get_all_radiator_names())
    enregistrer_log(
        f"Demande etat des appareils: {liste_radiateur} - Tentative : {nb_try}"
    )

    if nb_try >= 4:
        for radiateur in liste_radiateur:
            _liste_etat[radiateur] = "ERROR"
        return 0

    start_time = time.time()
    reponse_obtenu = {appareil: False for appareil in liste_radiateur}

    for appareil in liste_radiateur:
        message = {
            "FROM": "Django",
            "TO": appareil,
            "COMMAND": "STATE",
        }
        mqtt_client.publish(str(message), MQTT_SETTINGS.topic)

    del message

    old_nb_message = 0
    run = True
    while run:
        message_recu = mqtt_client.get_message_recu()
        new_nb_message = len(message_recu)
        for i in range(old_nb_message, new_nb_message):
            horaire, message = message_recu[i]
            if horaire >= start_time:
                parsed = ast.literal_eval(message)
                expediteur = parsed["FROM"]
                if parsed["TO"] == "Django" and expediteur in reponse_obtenu:
                    reponse_obtenu[expediteur] = True
                    _liste_etat[expediteur] = parsed["COMMAND"]
                    enregistrer_log(
                        f"Reponse sur son état obtenu de {expediteur} : {parsed['COMMAND']}"
                    )

        if all(reponse_obtenu.values()):
            return 1

        if time.time() - start_time > timeout:
            liste_radiateur_sans_retour = [
                cle for cle, value in reponse_obtenu.items() if not value
            ]
            return demander_etat_au_appareil(
                mqtt_client, nb_try + 1, liste_radiateur_sans_retour, timeout
            )

        old_nb_message = new_nb_message
        time.sleep(0.01)

    return 0
