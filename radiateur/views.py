"""HTTP views for the radiator application."""

from __future__ import annotations

import json
import time
from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template import loader
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from .runtime import get_cached_states, get_mqtt_client
from .services import (
    demander_etat_au_appareil,
    enregistrer_log,
    envoyer_changement_etat_mqtt,
)

DATA_FILE_PATH = Path(__file__).resolve().parent / "templates" / "data.json"


@csrf_exempt
@never_cache
def planning(request):
    """Render the planning page along with the JSON payload."""

    enregistrer_log("Requete page 'planning'")
    if not DATA_FILE_PATH.exists():
        DATA_FILE_PATH.write_text("[]", encoding="utf-8")

    data = DATA_FILE_PATH.read_text(encoding="utf-8")
    return render(request, "planning.html", {"data": data})


@csrf_exempt
def index(request):
    """Render the main dashboard page."""

    enregistrer_log("Requete page 'index'")
    return HttpResponse(loader.get_template("index.html").render({}))


@csrf_exempt
@never_cache
def maj_json(request):
    """Persist the planning JSON received from the front-end."""

    enregistrer_log("Reception requete modification planning")
    raw_body = request.body.decode("utf-8")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        trimmed = raw_body.strip()
        if len(trimmed) > 2:
            try:
                payload = json.loads(f"[{trimmed[1:-1]}]")
            except Exception:
                return HttpResponse(status=400)
        else:
            return HttpResponse(status=400)

    DATA_FILE_PATH.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    return HttpResponse(status=200)


@csrf_exempt
def changement_etat(request):
    """Handle state change requests sent from the UI."""

    enregistrer_log("Reception requete modification état")
    client = get_mqtt_client()
    if client is None:
        return HttpResponse(status=503)

    mode = json.loads(request.body.decode("utf-8")).get("mode")
    if not mode:
        return HttpResponse(status=400)

    retour = envoyer_changement_etat_mqtt(mode, client)
    return HttpResponse(status=200 if retour else 503)


@csrf_exempt
def retourner_etat(request):
    """Return the latest device states after requesting them from MQTT."""

    client = get_mqtt_client()
    if client is None:
        enregistrer_log("Impossible de retourner l'état: client MQTT indisponible")
        return JsonResponse(get_cached_states())

    demander_etat_au_appareil(client)
    time.sleep(0.05)
    return JsonResponse(get_cached_states())
