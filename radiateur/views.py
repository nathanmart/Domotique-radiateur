import ast
# import json
import threading
import time
import mimetypes

import paho.mqtt.client as mqtt
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template import loader
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from .fonction import *
from .MQTTClient import MQTTClient
from .parametres import IP_MQTT, TOPIC_MQTT, LISTE_RADIATEUR

global mqtt_client, liste_etat


@csrf_exempt
@never_cache
def planning(request):
    json_path = "radiateur/templates/data.json"
    with open(json_path) as f:
        data = f.read()
    return render(request, 'planning.html', {'data': data})
    # return HttpResponse(loader.get_template("planning.html").render({}, request))

@csrf_exempt
def index(request):
    return HttpResponse(loader.get_template("index.html").render({}))

@csrf_exempt
@never_cache
def getjson(request):
    with open("radiateur/templates/data.json", "r") as file:
        data = json.load(file)

    print("Les data:")
    print(data)
    return HttpResponse(data)

@never_cache
@csrf_exempt
def maj_json(request):
    data = request.body.decode('utf-8')
    data = data[1:-1]
    data= json.loads(f"[{data}]")

    with open("radiateur/templates/data.json", "w") as file:
        json.dump(data, file, indent=4)

    print("Enregistrer le fichier data.json")


    return HttpResponse(200)


@csrf_exempt
def changement_etat(request):
    mode = json.loads(request.body)['mode']
    retour = envoyer_changement_etat_mqtt(mode, mqtt_client)
    if retour:
        return HttpResponse(status=200)
    else:
        return HttpResponse(status=400)


@csrf_exempt
def retourner_etat(request):
    global mqtt_client
    demander_etat_au_appareil(mqtt_client)
    return JsonResponse(liste_etat)

@csrf_exempt
def get_image_url(request):
    # etat = request.GET.get('etat')
    # print(etat)
    image_url = "static/img/logo_confort.webp"
    image_data = open(image_url, 'rb').read()
    content_type, _ = mimetypes.guess_type(image_url)
    return HttpResponse(image_data, content_type=content_type)


# Création de la liste des état
liste_etat = {}
for radiateur in LISTE_RADIATEUR:
    liste_etat[radiateur] = "DEFAULT"
# Envoie de cette liste au programme fonction.py
set_liste_etat(liste_etat)

# Client MQTTT pour envoyer les requetes
mqtt_client = MQTTClient(IP_MQTT)
mqtt_client.subscribe(TOPIC_MQTT)

# Thread pour mettre suivre les instructions du planning
t = threading.Thread(target=maj_etat_selon_planning, args=(mqtt_client,)).start()

# Thread pour mettre à jour les états
thread_etat = threading.Thread(target=boucle_demander_etat_appareil, args=(mqtt_client,)).start()
