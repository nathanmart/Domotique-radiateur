"""HTTP views for the radiator application."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from .config import MQTT_SETTINGS
from .runtime import get_cached_states, get_mqtt_client
from .services import (
    demander_etat_au_appareil,
    enregistrer_log,
    envoyer_changement_etat_mqtt,
    load_disabled_states,
    update_disabled_state,
)

DATA_FILE_PATH = Path(__file__).resolve().parent / "templates" / "data.json"

WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _default_schedule() -> dict[str, list[dict[str, str]]]:
    """Return an empty schedule for each weekday."""

    return {day: [] for day in WEEKDAYS}


def _load_schedule() -> dict[str, list[dict[str, str]]]:
    """Load the current schedule from disk or return a default structure."""

    if not DATA_FILE_PATH.exists():
        return _default_schedule()

    try:
        data = json.loads(DATA_FILE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_schedule()

    if not isinstance(data, dict):
        return _default_schedule()

    schedule = _default_schedule()
    for day, entries in data.items():
        if day not in WEEKDAYS or not isinstance(entries, list):
            continue

        filtered: list[dict[str, str]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            start = entry.get("start")
            end = entry.get("end")
            if not isinstance(start, str) or not isinstance(end, str):
                continue
            filtered.append({"start": start, "end": end})

        schedule[day] = filtered

    return schedule


def _validate_schedule(payload: object) -> dict[str, list[dict[str, str]]]:
    """Validate and normalize the incoming schedule payload."""

    if not isinstance(payload, dict):
        raise ValueError("Le planning doit être un objet JSON.")

    schedule = _default_schedule()

    for day in WEEKDAYS:
        raw_entries = payload.get(day, [])
        if raw_entries in (None, ""):
            raw_entries = []

        if not isinstance(raw_entries, list):
            raise ValueError(f"Le jour {day} doit contenir une liste de créneaux.")

        normalized: list[dict[str, str]] = []
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                raise ValueError("Chaque créneau doit être un objet JSON.")

            start = raw_entry.get("start")
            end = raw_entry.get("end")

            if not isinstance(start, str) or not isinstance(end, str):
                raise ValueError("Les heures doivent être des chaînes au format HH:MM.")

            try:
                start_time = datetime.strptime(start, "%H:%M")
                end_time = datetime.strptime(end, "%H:%M")
            except ValueError as exc:
                raise ValueError("Format d'heure invalide. Utilisez HH:MM.") from exc

            if start_time >= end_time:
                raise ValueError("L'heure de fin doit être postérieure à l'heure de début.")

            normalized.append({"start": start_time.strftime("%H:%M"), "end": end_time.strftime("%H:%M")})

        normalized.sort(key=lambda item: item["start"])

        previous_end = None
        for entry in normalized:
            if previous_end and entry["start"] < previous_end:
                raise ValueError("Les créneaux ne doivent pas se chevaucher.")
            previous_end = entry["end"]

        schedule[day] = normalized

    return schedule


@csrf_exempt
@never_cache
def planning(request):
    """Render the planning page along with the JSON payload."""

    enregistrer_log("Requete page 'planning'")
    data = _load_schedule()
    return render(request, "planning.html", {"data": json.dumps(data, ensure_ascii=False)})


@csrf_exempt
def index(request):
    """Render the main dashboard page."""

    enregistrer_log("Requete page 'index'")
    disabled_states = load_disabled_states()
    radiator_cards: list[tuple[str, bool]] = []
    has_active_radiators = False
    for radiator in MQTT_SETTINGS.devices:
        is_disabled = disabled_states.get(radiator, False)
        if not is_disabled:
            has_active_radiators = True
        radiator_cards.append((radiator, is_disabled))
    context = {
        "radiators": MQTT_SETTINGS.devices,
        "disabled_states": disabled_states,
        "radiator_cards": radiator_cards,
        "has_active_radiators": has_active_radiators,
    }
    return render(request, "index.html", context)


@csrf_exempt
@never_cache
def maj_json(request):
    """Persist the planning JSON received from the front-end."""

    enregistrer_log("Reception requete modification planning")
    try:
        payload = json.loads(request.body.decode("utf-8"))
        schedule = _validate_schedule(payload)
    except (json.JSONDecodeError, ValueError):
        return HttpResponse(status=400)

    DATA_FILE_PATH.write_text(
        json.dumps(schedule, indent=4, ensure_ascii=False), encoding="utf-8"
    )
    return HttpResponse(status=200)


@csrf_exempt
def changement_etat(request):
    """Handle state change requests sent from the UI."""

    enregistrer_log("Reception requete modification état")
    client = get_mqtt_client()
    if client is None:
        return HttpResponse(status=503)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    mode = payload.get("mode")
    if not isinstance(mode, str):
        return HttpResponse(status=400)

    radiator = payload.get("radiator")
    if radiator:
        if radiator not in MQTT_SETTINGS.devices:
            return HttpResponse(status=400)
        liste_radiateur: list[str] | None = [radiator]
    else:
        liste_radiateur = None

    retour = envoyer_changement_etat_mqtt(mode, client, liste_radiateur)
    if retour is None:
        return HttpResponse(status=503)

    return JsonResponse({"applied_modes": retour, "disabled": load_disabled_states()})


@csrf_exempt
def retourner_etat(request):
    """Return the latest device states after requesting them from MQTT."""

    client = get_mqtt_client()
    if client is None:
        enregistrer_log("Impossible de retourner l'état: client MQTT indisponible")
        return JsonResponse({"states": get_cached_states(), "disabled": load_disabled_states()})

    demander_etat_au_appareil(client)
    time.sleep(0.05)
    return JsonResponse({"states": get_cached_states(), "disabled": load_disabled_states()})


@csrf_exempt
def options(request):
    """Display and update the options page allowing per-radiator overrides."""

    if request.method == "POST":
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return HttpResponse(status=400)

        radiator = payload.get("radiator")
        if not isinstance(radiator, str) or radiator not in MQTT_SETTINGS.devices:
            return HttpResponse(status=400)

        disabled = bool(payload.get("disabled", False))
        try:
            updated_map = update_disabled_state(radiator, disabled)
        except KeyError:
            return HttpResponse(status=400)

        client = get_mqtt_client()
        if disabled and client is not None:
            envoyer_changement_etat_mqtt("ECO", client, [radiator])

        enregistrer_log(
            f"Mise à jour option radiateur {radiator}: {'désactivé' if disabled else 'activé'}"
        )
        return JsonResponse({"disabled": updated_map})

    enregistrer_log("Requete page 'options'")
    disabled_states = load_disabled_states()
    context = {
        "radiators": MQTT_SETTINGS.devices,
        "disabled_states": disabled_states,
        "radiator_options": [
            (radiator, disabled_states.get(radiator, False))
            for radiator in MQTT_SETTINGS.devices
        ],
    }
    return render(request, "options.html", context)
