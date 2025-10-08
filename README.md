# Domotique radiateur – Guide d'installation sur Raspberry Pi

Ce document récapitule toutes les commandes nécessaires pour préparer un Raspberry Pi fraîchement installé afin d'exécuter ce projet Django ainsi que le courtier MQTT Mosquitto.

## 1. Mise à jour du système et installation des dépendances de base
```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git mosquitto mosquitto-clients
```

## 2. Récupération du projet
```bash
cd ~
git clone https://github.com/<votre-utilisateur>/Domotique-radiateur.git
cd Domotique-radiateur
```
> Si le dépôt se trouve déjà sur la machine, placez-vous simplement dans son dossier.

## 3. Création de l'environnement virtuel Python
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 4. Configuration des variables d'environnement
Créer un fichier `.env` à la racine du projet pour y stocker les secrets et paramètres MQTT :
```bash
cp .env.example .env  # s'il existe déjà un modèle
```
Sinon, créez le fichier :
```bash
cat <<'ENV' > .env
DJANGO_SECRET_KEY=changez-moi
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
APP_TIMEZONE=Europe/Paris
MQTT_BROKER_HOST=127.0.0.1
MQTT_BROKER_PORT=1883
MQTT_TOPIC=test
MQTT_DEVICES=radiateur_1,radiateur_2
ENV
```
> Ajustez les valeurs selon votre installation.

## 5. Préparation de la base de données et du compte administrateur
```bash
python manage.py migrate
python manage.py createsuperuser
```

## 6. Démarrage du courtier Mosquitto
Le paquet `mosquitto` installe un service systemd. Pour le démarrer et l'activer au démarrage :
```bash
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

Pour vérifier son état :
```bash
sudo systemctl status mosquitto
```

## 7. Lancement du serveur de développement Django
Avec l'environnement virtuel toujours activé :
```bash
python manage.py runserver 0.0.0.0:8000
```

Le site est maintenant accessible depuis votre réseau via `http://<IP_du_Pi>:8000/`.

## 8. (Optionnel) Lancer le simulateur de radiateurs
```bash
python simulator/fake_radiators.py
```

Ce script utilise les mêmes variables d'environnement pour publier des messages MQTT factices.

## 9. Maintenance courante
- Pour mettre à jour les dépendances Python : `pip install -r requirements.txt --upgrade`
- Pour quitter l'environnement virtuel : `deactivate`
- Pour récupérer les derniers changements Git :
  ```bash
  git pull
  pip install -r requirements.txt
  python manage.py migrate
  ```

Ce guide couvre l'essentiel pour démarrer rapidement le projet sur un Raspberry Pi.

## Indicateurs lumineux de l'ESP8266

L'ESP8266 embarque un indicateur lumineux intégré (LED) configuré dans `ESP8266/main.ino`.
Il informe en temps réel sur la progression de la connexion :

| État du microcontrôleur | Motif lumineux (LED active sur un ESP-12E = LED allumée) | Signification |
| --- | --- | --- |
| Connexion Wi-Fi en cours | Deux éclats rapides espacés de 150 ms (`on/off` répétés) | L'ESP cherche le réseau Wi-Fi enregistré ou tente de s'y reconnecter. |
| Wi-Fi connecté, en attente du serveur Django | Deux éclats moyens (200 ms) suivis d'une pause d'1 s | Le Wi-Fi est disponible mais la configuration côté serveur (API) reste incomplète. |
| Wi-Fi + serveur OK, connexion MQTT en attente | Trois éclats de 200 ms puis une pause de 800 ms | L'ESP attend de joindre le broker MQTT configuré. |
| Tout connecté | Flash discret (60 ms) toutes les ~3 s | Wi-Fi, Django et MQTT fonctionnent : l'appareil est pleinement opérationnel. |
| Changement d'état appliqué | Deux brefs flashs de 120 ms suivis d'une courte pause | Confirmation visuelle que le relais a bien reçu un nouvel ordre (Confort, Éco, Hors gel ou Arrêt). |

> Remarque : La LED intégrée de l'ESP8266 est câblée en logique inverse (LOW = allumé).
