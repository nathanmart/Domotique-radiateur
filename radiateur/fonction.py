from .views import *
from .parametres import *
import json
from datetime import datetime, timedelta


# Reception de la lisste afin de la lier entre les différents programmes
def set_liste_etat(liste):
    global liste_etat
    liste_etat = liste


# Envoie aux radiateurs leur nouveau mode
def envoyer_changement_etat_mqtt(mode, mqtt_client, liste_radiateur=LISTE_RADIATEUR, mqtt_topic=TOPIC_MQTT):
    for appareil in liste_radiateur:
        message = {
            "FROM": "Django",
            "TO": appareil,
            "COMMAND": mode,
        }
        mqtt_client.publish(str(message), mqtt_topic)
        enregistrer_log(f"Modification état: {appareil} --> {mode}")
    return True

# Met à jour le mode des radiateurs en fonction du planning
# Boucle infini bloquante, A EXECUTER DANS UN THREAD
def maj_etat_selon_planning(mqtt_client):
    last_min = datetime.now(paris_tz) - timedelta(minutes=1)
    while True:
        heure_actuelle = datetime.now(paris_tz)
        if heure_actuelle.minute != last_min.minute:
            with open("radiateur/templates/data.json", "r") as file:
                data = json.load(file)

            for event in data:
                start = event["start"]
                end = event["end"]
                start = datetime.strptime(start, "%Y-%m-%dT%H:%M:%S").replace(second=0, microsecond=0)
                start = paris_tz.localize(start)
                end = datetime.strptime(end, "%Y-%m-%dT%H:%M:%S").replace(second=0, microsecond=0)
                end = paris_tz.localize(end)

                heure_actuelle = datetime.now(paris_tz).replace(second=0, microsecond=0)
                if end == heure_actuelle:
                    enregistrer_log("Depuis planning --> ECO")
                    envoyer_changement_etat_mqtt("ECO", mqtt_client)
                elif start == heure_actuelle:
                    enregistrer_log("Depuis planning --> CONFORT")
                    envoyer_changement_etat_mqtt("COMFORT", mqtt_client)

            last_min = heure_actuelle
            time.sleep(30)

        time.sleep(10)

def boucle_demander_etat_appareil(mqtt_client, nb_try = 1, liste_radiateur=LISTE_RADIATEUR, delai=15):
    while True:
        demander_etat_au_appareil(mqtt_client, nb_try, liste_radiateur)
        time.sleep(delai)

# Envoie des demandes aux radiateurs pour connaitre leur état
def demander_etat_au_appareil(mqtt_client, nb_try = 1, liste_radiateur=LISTE_RADIATEUR):
    global liste_etat
    enregistrer_log(f"Demande etat des appareils: {liste_radiateur} - Tentative : {nb_try}")
    # Lorsque la fonction est appele recursivement pour la 4eme (donc 3 try), on considère que le radiateur est
    # deconnecté
    if nb_try >= 4:
        for radiateur in liste_radiateur:
            liste_etat[radiateur] = "ERROR"
            return 0

    # Enregistrement de l'heure de début d'exection
    start_time = time.time()
    # On envoie la requete à chaque radiateurs
    # Et on créé le dicictionnaire qui stocke si on a bien reçu une réponse
    reponse_obtenu = {}
    for appareil in liste_radiateur:
        reponse_obtenu[appareil] = False
        message = {
            "FROM": "Django",
            "TO": appareil,
            "COMMAND": "STATE"
        }
        mqtt_client.publish(str(message), TOPIC_MQTT)

    del message

    # Récupère en boucle les mesages obtenues.
    # S'arrète si:
    # -Tous les appareils ont répondu
    # -Un certain délai est passé
    old_nb_message = 0
    run = True
    while run:
        message_recu = mqtt_client.get_message_recu()
        new_nb_message = len(message_recu)
        # Pour éviter de relire plusieur fois les mêmes messages, ont ne lit que les nouveaux, lorsque'il y en a
        for i in range(old_nb_message, new_nb_message):
            horaire = message_recu[i][0]
            if horaire >= start_time:
                message = message_recu[i][1]
                message = ast.literal_eval(message)
                expediteur = message["FROM"]
                if message["TO"] == "Django" and expediteur in reponse_obtenu:
                    # Dans ce cas on a une réponse valide
                    reponse_obtenu[expediteur] = True
                    liste_etat[expediteur] = message["COMMAND"]
                    enregistrer_log(f"Reponse sur son état obtenu de {expediteur} : {message['COMMAND']}")

        # Dans le cas ou tout les appareils ont répondu, on casse la boucle
        if not False in reponse_obtenu.values():
            return 1

        # Au bout de 2 secondes sans réponse, on casse la boucle
        if time.time() - start_time > 2:
            # On fait la liste des radieur sans réponse
            liste_radiateur_sans_retour = []
            for cle, value in reponse_obtenu.items():
                if value == False:
                    liste_radiateur_sans_retour.append(cle)

            # Recursivité sur cette fonction, en limitant la liste des radiateurs à seulement ceux n'ayants pas
            # donnés de réponse
            return demander_etat_au_appareil(mqtt_client, nb_try + 1, liste_radiateur_sans_retour)

        old_nb_message = new_nb_message
        time.sleep(0.01)

    return 0

def enregistrer_log(message, fichier="log.txt"):
    heure_actuelle = datetime.now(paris_tz).strftime("%Y-%m-%d %H:%M:%S")
    message_formate = f"[{heure_actuelle}] {message}\n"

    with open(fichier, "a") as f:
        f.write(message_formate)