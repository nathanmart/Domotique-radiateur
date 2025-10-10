"""HTTP views for the radiator application."""

from __future__ import annotations

import json
import math
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from ipaddress import ip_address, ip_network
import http.client
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from typing import Optional

try:
    import netifaces  # type: ignore
except ImportError:  # pragma: no cover - optional dependency handled at runtime
    netifaces = None

from .config import MQTT_SETTINGS, TIMEZONE
from .models import (
    get_device,
    load_devices,
    record_discovered_device,
    remove_device,
    rename_device,
)
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
SERVICE_WORKER_PATH = Path(settings.BASE_DIR) / "static" / "js" / "service-worker.js"

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
@login_required
def planning(request):
    """Render the planning page along with the JSON payload."""

    enregistrer_log("Requete page 'planning'")
    data = _load_schedule()
    return render(request, "planning.html", {"data": json.dumps(data, ensure_ascii=False)})


@never_cache
def service_worker(request):
    """Serve the service worker script from the project root."""

    if not SERVICE_WORKER_PATH.exists():
        return HttpResponse(
            "// Service worker introuvable",
            content_type="application/javascript",
            status=404,
        )

    response = HttpResponse(
        SERVICE_WORKER_PATH.read_text(encoding="utf-8"),
        content_type="application/javascript",
    )
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
@login_required
def index(request):
    """Render the main dashboard page."""

    enregistrer_log("Requete page 'index'")
    radiators = get_all_radiator_names()
    disabled_states = load_disabled_states()
    cached_states = get_cached_states()
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
        "initial_states": cached_states,
        "radiator_cards": radiator_cards,
        "has_active_radiators": has_active_radiators,
    }
    return render(request, "index.html", context)


@csrf_exempt
@never_cache
@login_required
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
@login_required
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
@login_required
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
@login_required
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
        "custom_devices": [
            {
                "name": device.name,
                "ip_address": device.ip_address,
                "added_at_display": device.added_at.astimezone(TIMEZONE).strftime(
                    "%d/%m/%Y %H:%M"
                ),
            }
            for device in load_devices()
        ],
    }
    return render(request, "options.html", context)


ESP_DISCOVERY_ENDPOINT = "/identify"
ESP_RENAME_ENDPOINT = "/device-name"
ESP_MQTT_HOST_ENDPOINT = "/mqtt-host"
ESP_DISCOVERY_TIMEOUT = 1.5
ESP_DISCOVERY_SIGNATURE = "esp8266-radiator"
ESP_SCAN_MAX_WORKERS = 24
ESP_SCAN_MAX_HOSTS = 1024


def _collect_candidate_networks(local_ip: str) -> list[ip_network]:
    """Return IPv4 networks that should be scanned for ESP8266 modules."""

    networks: list[ip_network] = []
    seen: set[str] = set()

    def register(network: ip_network) -> None:
        if network.version != 4:
            return
        if network.prefixlen >= 31:
            return
        if network.num_addresses > ESP_SCAN_MAX_HOSTS + 2:
            return
        key = network.with_prefixlen
        if key in seen:
            return
        seen.add(key)
        networks.append(network)

    if netifaces is not None:
        for interface in netifaces.interfaces():
            try:
                addresses = netifaces.ifaddresses(interface)
            except ValueError:
                continue
            for details in addresses.get(netifaces.AF_INET, []):
                addr = details.get("addr")
                netmask = details.get("netmask")
                if not addr or not netmask:
                    continue
                try:
                    network = ip_network(f"{addr}/{netmask}", strict=False)
                except ValueError:
                    continue
                register(network)

    try:
        parsed_local = ip_network(f"{local_ip}/24", strict=False)
    except ValueError:
        parsed_local = None
    if parsed_local is not None:
        register(parsed_local)

    try:
        mqtt_ip = ip_address(MQTT_SETTINGS.host)
    except ValueError:
        mqtt_ip = None
    if mqtt_ip is not None and mqtt_ip.version == 4 and not mqtt_ip.is_loopback:
        try:
            register(ip_network(f"{mqtt_ip}/24", strict=False))
        except ValueError:
            pass

    return networks


def _enumerate_local_hosts() -> list[str]:
    """Return IPv4 hosts that are worth probing for ESP8266 discovery."""

    local_ip = _detect_local_ip(MQTT_SETTINGS.host)
    try:
        parsed_local = ip_address(local_ip)
    except ValueError:
        parsed_local = None

    local_ip_str = str(parsed_local) if parsed_local is not None else ""
    hosts: list[str] = []
    seen: set[str] = set()

    def add_host(value: str) -> None:
        if value == local_ip_str:
            return
        if value in seen:
            return
        seen.add(value)
        hosts.append(value)

    for device in load_devices():
        if not device.ip_address:
            continue
        try:
            parsed = ip_address(device.ip_address)
        except ValueError:
            continue
        if parsed.version != 4 or parsed.is_loopback or parsed.is_unspecified:
            continue
        add_host(str(parsed))

    networks = _collect_candidate_networks(local_ip)
    for network in networks:
        remaining = ESP_SCAN_MAX_HOSTS - len(hosts)
        if remaining <= 0:
            break

        total_hosts = max(network.num_addresses - 2, 0)
        if total_hosts == 0:
            continue

        focus_ip = None
        if parsed_local is not None and parsed_local in network:
            focus_ip = int(parsed_local)

        if total_hosts <= remaining:
            for host in network.hosts():
                if len(hosts) >= ESP_SCAN_MAX_HOSTS:
                    break
                add_host(str(host))
            continue

        step = max(1, math.ceil(total_hosts / remaining))
        network_start = int(network.network_address) + 1
        network_end = int(network.broadcast_address) - 1

        sampled: set[int] = set()

        def enqueue(address: int) -> None:
            if len(hosts) >= ESP_SCAN_MAX_HOSTS:
                return
            if address < network_start or address > network_end:
                return
            if address in sampled:
                return
            sampled.add(address)
            add_host(str(ip_address(address)))

        if focus_ip is not None:
            enqueue(focus_ip)

            offset = step
            while len(hosts) < ESP_SCAN_MAX_HOSTS and offset <= total_hosts:
                enqueue(focus_ip - offset)
                enqueue(focus_ip + offset)
                offset += step

        current = network_start
        while len(hosts) < ESP_SCAN_MAX_HOSTS and current <= network_end:
            enqueue(current)
            current += step

        enqueue(network_start)
        enqueue(network_end)

    try:
        mqtt_ip = ip_address(MQTT_SETTINGS.host)
    except ValueError:
        mqtt_ip = None
    if mqtt_ip is not None and mqtt_ip.version == 4 and not mqtt_ip.is_loopback:
        add_host(str(mqtt_ip))

    return hosts


def _probe_esp8266(host: str) -> dict[str, str] | None:
    """Attempt to retrieve identification information from an ESP8266."""

    connection: http.client.HTTPConnection | None = None
    try:
        connection = http.client.HTTPConnection(host, timeout=ESP_DISCOVERY_TIMEOUT)
        connection.request("GET", ESP_DISCOVERY_ENDPOINT)
        response = connection.getresponse()
        if response.status != 200:
            return None
        payload = response.read()
    except (OSError, http.client.HTTPException):
        return None
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass

    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None
    if data.get("device_type") != ESP_DISCOVERY_SIGNATURE:
        return None

    raw_name = data.get("name")
    if not isinstance(raw_name, str):
        return None
    name = raw_name.strip()
    if not name:
        return None

    ip_value = data.get("ip_address")
    ip_str = str(ip_value).strip() if isinstance(ip_value, str) else host

    return {
        "name": name,
        "ip_address": ip_str,
        "mac_address": data.get("mac_address"),
    }


def _discover_esp8266_devices(hosts: list[str] | None = None) -> list[dict[str, str]]:
    """Scan the local network and return every responding ESP8266."""

    hosts = hosts if hosts is not None else _enumerate_local_hosts()
    if not hosts:
        return []

    results: list[dict[str, str]] = []
    workers = min(len(hosts), ESP_SCAN_MAX_WORKERS) or 1
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_probe_esp8266, host): host for host in hosts}
        for future in as_completed(futures):
            info = future.result()
            if info is not None:
                results.append(info)

    return results


def _push_device_name(ip: str, name: str) -> bool:
    """Request the ESP8266 to update its device name."""

    payload = json.dumps({"name": name})
    connection: http.client.HTTPConnection | None = None
    try:
        connection = http.client.HTTPConnection(ip, timeout=ESP_DISCOVERY_TIMEOUT)
        connection.request(
            "POST",
            ESP_RENAME_ENDPOINT,
            body=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        if response.status != 200:
            return False
        raw = response.read()
    except (OSError, http.client.HTTPException):
        return False
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False

    return isinstance(data, dict) and data.get("status") == "ok"


def _push_mqtt_host(ip: str, host: str) -> bool:
    """Send the MQTT broker address to the ESP8266."""

    payload = json.dumps({"host": host})
    connection: http.client.HTTPConnection | None = None
    try:
        connection = http.client.HTTPConnection(ip, timeout=ESP_DISCOVERY_TIMEOUT)
        connection.request(
            "POST",
            ESP_MQTT_HOST_ENDPOINT,
            body=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        if response.status != 200:
            return False
        raw = response.read()
    except (OSError, http.client.HTTPException):
        return False
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False

    return isinstance(data, dict) and data.get("status") == "ok"


@csrf_exempt
@never_cache
@login_required
def devices(request):
    """Manage ESP8266 registrations via the JSON registry."""

    if request.method == "POST":
        mqtt_host = _detect_local_ip(MQTT_SETTINGS.host)
        hosts = _enumerate_local_hosts()
        if not hosts:
            return JsonResponse(
                {
                    "error": "Impossible de déterminer l'adresse IP locale pour scanner le réseau.",
                },
                status=503,
            )

        enregistrer_log("Recherche d'appareils ESP8266 sur le réseau local")
        discovered = _discover_esp8266_devices(hosts)

        added: list[dict[str, str | None]] = []
        existing: list[dict[str, str | None]] = []
        configured: list[str] = []
        seen: set[str] = set()

        state_map = get_liste_etat()
        disabled_states = load_disabled_states()
        states_changed = False

        for info in discovered:
            name = info["name"]
            if name in seen:
                continue
            seen.add(name)

            try:
                record, created = record_discovered_device(name, info.get("ip_address"))
            except ValueError:
                continue

            assigned_host: str | None = None
            if record.ip_address and mqtt_host:
                if _push_mqtt_host(record.ip_address, mqtt_host):
                    assigned_host = mqtt_host
                    configured.append(record.name)
                else:
                    enregistrer_log(
                        "Impossible de configurer le broker MQTT pour %s (%s)",
                        record.name,
                        record.ip_address,
                    )

            entry = {
                "name": record.name,
                "ip_address": record.ip_address,
                "added_at": record.added_at.isoformat(),
                "mqtt_host": assigned_host,
            }

            if created:
                added.append(entry)
                if record.name not in state_map:
                    state_map[record.name] = "DEFAULT"
                if disabled_states.get(record.name) is None:
                    disabled_states[record.name] = False
                    states_changed = True
                enregistrer_log(
                    "Nouveau radiateur détecté: %s%s"
                    % (
                        record.name,
                        f" ({record.ip_address})" if record.ip_address else "",
                    )
                )
            else:
                existing.append(entry)

        if states_changed:
            save_disabled_states(disabled_states)

        payload = {
            "added": added,
            "existing": existing,
            "detected": len(discovered),
            "configured": configured,
        }
        return JsonResponse(payload)

    if request.method == "PATCH":
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return JsonResponse({"error": "Requête invalide."}, status=400)

        raw_old = payload.get("old_name")
        raw_new = payload.get("new_name")
        if not isinstance(raw_old, str) or not isinstance(raw_new, str):
            return JsonResponse({"error": "Noms invalides."}, status=400)

        old_name = raw_old.strip()
        new_name = raw_new.strip()
        if not old_name or not new_name:
            return JsonResponse({"error": "Les noms fournis sont invalides."}, status=400)
        if len(new_name) > 63:
            return JsonResponse({"error": "Le nouveau nom est trop long."}, status=400)

        if old_name == new_name:
            return JsonResponse({"name": old_name})

        record = get_device(old_name)
        if record is None:
            return JsonResponse({"error": "Appareil introuvable."}, status=404)

        if not record.ip_address:
            return JsonResponse(
                {
                    "error": "Adresse IP inconnue pour contacter l'appareil. Relancez une détection avant de le renommer.",
                },
                status=409,
            )

        existing_device = get_device(new_name)
        if existing_device is not None and existing_device.name != old_name:
            return JsonResponse({"error": "Un appareil avec ce nom existe déjà."}, status=409)

        if not _push_device_name(record.ip_address, new_name):
            return JsonResponse(
                {"error": "Impossible de contacter l'appareil pour mettre à jour son nom."},
                status=502,
            )

        try:
            updated = rename_device(old_name, new_name)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=409)
        except KeyError:
            return JsonResponse({"error": "Appareil introuvable."}, status=404)

        state_map = get_liste_etat()
        if old_name in state_map:
            state_map[new_name] = state_map.pop(old_name)
        else:
            state_map.setdefault(new_name, "DEFAULT")

        states = load_disabled_states()
        previous_state = states.pop(old_name, False)
        states[new_name] = previous_state
        save_disabled_states(states)

        enregistrer_log(f"Radiateur renommé: {old_name} -> {new_name}")

        return JsonResponse(
            {
                "name": updated.name,
                "ip_address": updated.ip_address,
            }
        )

    if request.method == "DELETE":
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return JsonResponse({"error": "Requête invalide."}, status=400)

        raw_name = payload.get("name")
        if not isinstance(raw_name, str):
            return JsonResponse({"error": "Nom invalide."}, status=400)

        name = raw_name.strip()
        if not name:
            return JsonResponse({"error": "Nom invalide."}, status=400)

        if not remove_device(name):
            return JsonResponse({"error": "Appareil introuvable."}, status=404)

        state_map = get_liste_etat()
        state_map.pop(name, None)

        states = load_disabled_states()
        if name in states:
            del states[name]
        save_disabled_states(states)

        enregistrer_log(f"Radiateur supprimé: {name}")

        return JsonResponse({"deleted": name})

    return HttpResponse(status=405)


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
