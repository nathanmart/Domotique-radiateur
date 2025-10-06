"""Business logic for radiator scheduling and MQTT communication."""

from __future__ import annotations

import ast
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable

from .config import APP_LOG_FILE, MQTT_SETTINGS, TIMEZONE


_liste_etat: Dict[str, str] = {}


def set_liste_etat(liste: Dict[str, str]) -> None:
    """Register the shared dictionary used to track device states."""

    global _liste_etat
    _liste_etat = liste


def get_liste_etat() -> Dict[str, str]:
    """Expose the current state of the radiators."""

    return _liste_etat


def enregistrer_log(message: str, fichier: Path | None = None) -> None:
    """Persist an application log entry."""

    log_file = fichier or APP_LOG_FILE
    timestamp = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {message}\n")


def envoyer_changement_etat_mqtt(mode: str, mqtt_client, liste_radiateur: Iterable[str] | None = None) -> bool:
    """Send the desired mode to all registered radiators via MQTT."""

    liste_radiateur = list(liste_radiateur or MQTT_SETTINGS.devices)
    if not mqtt_client:
        enregistrer_log("Aucun client MQTT disponible pour envoyer le changement d'état")
        return False

    for appareil in liste_radiateur:
        message = {
            "FROM": "Django",
            "TO": appareil,
            "COMMAND": mode,
        }
        mqtt_client.publish(str(message), MQTT_SETTINGS.topic)
        enregistrer_log(f"Modification état: {appareil} --> {mode}")
    return True


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
            with open(planning_path, "r", encoding="utf-8") as file:
                data = json.load(file)

            for event in data:
                start = datetime.strptime(event["start"], "%Y-%m-%dT%H:%M:%S").replace(second=0, microsecond=0)
                end = datetime.strptime(event["end"], "%Y-%m-%dT%H:%M:%S").replace(second=0, microsecond=0)
                start = TIMEZONE.localize(start)
                end = TIMEZONE.localize(end)

                current_time = datetime.now(TIMEZONE).replace(second=0, microsecond=0)
                if end == current_time:
                    enregistrer_log("Depuis planning --> ECO")
                    envoyer_changement_etat_mqtt("ECO", mqtt_client)
                elif start == current_time:
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

    liste_radiateur = list(liste_radiateur or MQTT_SETTINGS.devices)
    if not mqtt_client:
        enregistrer_log("Aucun client MQTT disponible pour interroger les appareils")
        return

    while True:
        demander_etat_au_appareil(mqtt_client, nb_try, liste_radiateur)
        time.sleep(delai)


def demander_etat_au_appareil(mqtt_client, nb_try: int = 1, liste_radiateur: Iterable[str] | None = None):
    """Request the state of each radiator and update the shared cache."""

    if not mqtt_client:
        enregistrer_log("Aucun client MQTT disponible pour demander l'état des appareils")
        return 0

    liste_radiateur = list(liste_radiateur or MQTT_SETTINGS.devices)
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

        if time.time() - start_time > 2:
            liste_radiateur_sans_retour = [cle for cle, value in reponse_obtenu.items() if not value]
            return demander_etat_au_appareil(
                mqtt_client, nb_try + 1, liste_radiateur_sans_retour
            )

        old_nb_message = new_nb_message
        time.sleep(0.01)

    return 0
