from .views import *
from .parametres import *
import json
from datetime import datetime, timedelta

# Envoie aux radiateurs leur nouveau mode
def envoyer_changement_etat_mqtt(mode, mqtt_client, liste_radiateur=LISTE_RADIATEUR, mqtt_topic=TOPIC_MQTT):
    for appareil in liste_radiateur:

        message = {
            "FROM": "Django",
            "TO": appareil,
            "COMMAND": mode,
        }
        mqtt_client.publish(str(message), mqtt_topic)
    return True

# Met à jour le mode des radiateurs en fonction du planning
# Boucle infini bloquante, A EXECUTER DANS UN THREAD
def maj_etat_selon_planning(mqtt_client):
    last_min = datetime.now() - timedelta(minutes=1)
    while True:
        heure_actuelle = datetime.now()
        if heure_actuelle.minute != last_min.minute:

            with open("radiateur/templates/data.json", "r") as file:
                data = json.load(file)

            for event in data:
                start = event["start"]
                end = event["end"]
                start = datetime.strptime(start, "%Y-%m-%dT%H:%M:%S").replace(second=0, microsecond=0)
                end = datetime.strptime(end, "%Y-%m-%dT%H:%M:%S").replace(second=0, microsecond=0)

                heure_actuelle = datetime.now().replace(second=0, microsecond=0)

                if end == heure_actuelle:
                    envoyer_changement_etat_mqtt("ECO", mqtt_client)
                elif start == heure_actuelle:
                    envoyer_changement_etat_mqtt("COMFORT", mqtt_client)

            last_min = heure_actuelle
            time.sleep(30)

        time.sleep(10)
