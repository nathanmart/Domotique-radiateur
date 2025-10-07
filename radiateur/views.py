"""HTTP views for the radiator application."""

from __future__ import annotations

import json
import socket
import time
from datetime import datetime
from ipaddress import ip_address
from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from typing import Optional

from .config import MQTT_SETTINGS
from .models import RadiatorDevice
from .runtime import get_cached_states, get_mqtt_client
from .services import (
    demander_etat_au_appareil,
    enregistrer_log,
    envoyer_changement_etat_mqtt,
    get_all_radiator_names,
    get_liste_etat,
    load_disabled_states,
    save_disabled_states,
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


MINUTES_IN_DAY = 24 * 60


def _parse_time(value: str, *, allow_midnight: bool) -> int:
    """Parse an HH:MM string into minutes, optionally allowing 24:00."""

    if value == "24:00":
        if allow_midnight:
            return MINUTES_IN_DAY
        raise ValueError("L'heure 24:00 n'est autorisée qu'en fin de créneau.")

    try:
        time = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError("Format d'heure invalide. Utilisez HH:MM.") from exc

    minutes = time.hour * 60 + time.minute
    if minutes >= MINUTES_IN_DAY:
        raise ValueError("Les heures doivent être comprises entre 00:00 et 23:59.")
    return minutes


def _format_time(minutes: int) -> str:
    """Convert minutes to HH:MM, handling 24:00 as a special case."""

    if minutes == MINUTES_IN_DAY:
        return "24:00"
    hours, mins = divmod(minutes, 60)
    return f"{hours:02d}:{mins:02d}"


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

        parsed_entries: list[tuple[int, int]] = []
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                raise ValueError("Chaque créneau doit être un objet JSON.")

            start = raw_entry.get("start")
            end = raw_entry.get("end")

            if not isinstance(start, str) or not isinstance(end, str):
                raise ValueError("Les heures doivent être des chaînes au format HH:MM.")

            start_minutes = _parse_time(start, allow_midnight=False)
            end_minutes = _parse_time(end, allow_midnight=True)

            if start_minutes >= end_minutes:
                raise ValueError("L'heure de fin doit être postérieure à l'heure de début.")

            parsed_entries.append((start_minutes, end_minutes))

        parsed_entries.sort(key=lambda entry: entry[0])

        normalized: list[dict[str, str]] = []
        previous_end = None
        for start_minutes, end_minutes in parsed_entries:
            if previous_end is not None and start_minutes < previous_end:
                raise ValueError("Les créneaux ne doivent pas se chevaucher.")
            normalized.append({
                "start": _format_time(start_minutes),
                "end": _format_time(end_minutes),
            })
            previous_end = end_minutes

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
    radiators = get_all_radiator_names()
    disabled_states = load_disabled_states()
    radiator_cards: list[tuple[str, bool]] = []
    has_active_radiators = False
    for radiator in radiators:
        is_disabled = disabled_states.get(radiator, False)
        if not is_disabled:
            has_active_radiators = True
        radiator_cards.append((radiator, is_disabled))
    context = {
        "radiators": radiators,
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
    known_radiators = set(get_all_radiator_names())
    if radiator:
        if radiator not in known_radiators:
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
        known_radiators = set(get_all_radiator_names())
        if not isinstance(radiator, str) or radiator not in known_radiators:
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
    radiators = get_all_radiator_names()
    disabled_states = load_disabled_states()
    context = {
        "radiators": radiators,
        "disabled_states": disabled_states,
        "radiator_options": [
            (radiator, disabled_states.get(radiator, False))
            for radiator in radiators
        ],
        "mqtt_host": _detect_local_ip(MQTT_SETTINGS.host),
        "custom_devices": list(RadiatorDevice.objects.order_by("name")),
    }
    return render(request, "options.html", context)


@csrf_exempt
@never_cache
def devices(request):
    """Register a new ESP8266 radiator from the local network."""

    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Requête invalide."}, status=400)

    raw_name = payload.get("name")
    if not isinstance(raw_name, str):
        return JsonResponse({"error": "Le nom de l'appareil est requis."}, status=400)

    name = raw_name.strip()
    if not name:
        return JsonResponse({"error": "Le nom de l'appareil est requis."}, status=400)
    if len(name) > 64:
        return JsonResponse({"error": "Le nom doit contenir 64 caractères maximum."}, status=400)

    known_radiators = set(get_all_radiator_names())
    if name in known_radiators:
        return JsonResponse({"error": "Un appareil avec ce nom existe déjà."}, status=409)

    raw_ip = payload.get("ip_address")
    normalized_ip: Optional[str]
    if raw_ip in (None, ""):
        normalized_ip = None
    elif isinstance(raw_ip, str):
        try:
            parsed_ip = ip_address(raw_ip.strip())
        except ValueError:
            return JsonResponse({"error": "Adresse IP invalide."}, status=400)

        if not (parsed_ip.is_private or parsed_ip.is_link_local or parsed_ip.is_loopback):
            return JsonResponse(
                {"error": "L'adresse IP doit appartenir au réseau local."},
                status=400,
            )
        normalized_ip = str(parsed_ip)
    else:
        return JsonResponse({"error": "Adresse IP invalide."}, status=400)

    device = RadiatorDevice.objects.create(name=name, ip_address=normalized_ip)

    states = load_disabled_states()
    if name not in states:
        states[name] = False
        save_disabled_states(states)

    state_map = get_liste_etat()
    state_map.setdefault(name, "DEFAULT")

    enregistrer_log(
        f"Nouveau radiateur ajouté: {name}"
        + (f" ({normalized_ip})" if normalized_ip else "")
    )

    return JsonResponse(
        {
            "name": device.name,
            "ip_address": device.ip_address,
        },
        status=201,
    )


def _detect_local_ip(default: str) -> str:
    """Return the best local IPv4 address for the MQTT broker."""

    candidate: Optional[str] = None

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            candidate = sock.getsockname()[0]
    except OSError:
        candidate = None

    if not candidate or candidate.startswith("127."):
        try:
            hostname_ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            hostname_ip = ""
        if hostname_ip and not hostname_ip.startswith("127."):
            candidate = hostname_ip

    return candidate or default
