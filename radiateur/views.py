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


global mqtt_client


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
    # global message_recu
    etat = {
        "Chambre" : "None",
        "Cuisine" : "None",
    }
    etat_images = {
        "ECO": "static/img/logo_eco.webp",
        "CONFORT": "static/img/logo_confort.webp",
        "ERROR": "static/img/logo_erreur.webp",
        "HORS_GEL": "static/img/logo_hors_gel.webp",
        "OFF": "static/img/logo_off.webp",
    }

    for appareil in LISTE_RADIATEUR:

        message = {
            "FROM": "Django",
            "TO": appareil,
            "COMMAND": "STATE"
        }
        mqtt_client.publish(str(message), TOPIC_MQTT)

        mqtt_client.subscribe(TOPIC_MQTT)

        run = True
        start_time = time.time()
        while run:
            message_recu = mqtt_client.get_message_recu()
            if message_recu:
                mqtt_client.reset_message_recu()
                message_recu = ast.literal_eval(message_recu)
                if message_recu["FROM"] == appareil:
                    etat[appareil] = message_recu["COMMAND"]
                    mqtt_client.unsubscribe()
                    break

                message_recu = None

            if time.time() - start_time > 1:
                etat[appareil] = "ERROR"
                break

            time.sleep(0.01)

    print(etat)
    return JsonResponse(etat)

@csrf_exempt
def get_image_url(request):
    # etat = request.GET.get('etat')
    # print(etat)
    image_url = "static/img/logo_confort.webp"
    image_data = open(image_url, 'rb').read()
    content_type, _ = mimetypes.guess_type(image_url)
    return HttpResponse(image_data, content_type=content_type)


# Client MQTTT pour envoyer les requetes
mqtt_client = MQTTClient(IP_MQTT)

# Thread pour mettre suivre les instructions du planning
t = threading.Thread(target=maj_etat_selon_planning, args=(mqtt_client,)).start()
# t.start()