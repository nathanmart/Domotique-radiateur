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

## 10. Déploiement en production avec Gunicorn et Nginx

Les sections précédentes permettent de lancer le serveur en mode développement. Pour une mise
en production durable, nous allons utiliser Gunicorn comme serveur d'application WSGI et Nginx
comme proxy inverse.

### 10.1 Installation des paquets nécessaires

Installez Nginx via `apt` et ajoutez Gunicorn dans votre environnement virtuel afin qu'il
utilise exactement les mêmes dépendances Python que votre projet :

```bash
sudo apt install -y nginx
source /home/nathan/Domotique-radiateur/.venv/bin/activate
pip install gunicorn
```

Si le service Mosquitto n'était pas encore activé, vérifiez son état et activez-le pour un
redémarrage automatique :

```bash
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

### 10.2 Service systemd pour Gunicorn

Créez un fichier `/etc/systemd/system/gunicorn.service` avec le contenu suivant (adaptez les
chemins si nécessaire) :

```ini
[Unit]
Description=Gunicorn daemon for Domotique-radiateur
After=network.target mosquitto.service
Requires=mosquitto.service

[Service]
User=nathan
Group=www-data
WorkingDirectory=/home/nathan/Domotique-radiateur
Environment="PATH=/home/nathan/Domotique-radiateur/.venv/bin"
EnvironmentFile=/home/nathan/Domotique-radiateur/.env
ExecStart=/home/nathan/Domotique-radiateur/.venv/bin/gunicorn \
    --workers 3 \
    --bind unix:/run/gunicorn/gunicorn-domotique.sock \
    djangoProject1.wsgi:application

[Install]
WantedBy=multi-user.target
```

> Adaptez `User`, `WorkingDirectory` et les chemins au compte système qui possède le
> projet. Le chemin WSGI (`djangoProject1.wsgi`) reste identique.

Créez le dossier du socket Unix avant de démarrer le service afin d'éviter les erreurs de
permission :

```bash
sudo mkdir -p /run/gunicorn
sudo chown nathan:www-data /run/gunicorn
sudo chmod 775 /run/gunicorn
```

Ensuite, rechargez systemd et démarrez le service :

```bash
sudo systemctl daemon-reload
sudo systemctl enable gunicorn
sudo systemctl start gunicorn
sudo systemctl status gunicorn
```

La section `[Unit]` garantit que Mosquitto est lancé avant Gunicorn afin que les connexions MQTT
du projet soient immédiatement disponibles.

### 10.3 Configuration de Nginx

Créez un fichier `/etc/nginx/sites-available/domotique` :

```nginx
server {
    listen 80;
    server_name domotique.local <IP_du_Pi>;

    location = /favicon.ico { access_log off; log_not_found off; }
    location /static/ {
        alias /home/nathan/Domotique-radiateur/static/;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/run/gunicorn/gunicorn-domotique.sock;
    }
}
```

Activez le site et testez la configuration :

```bash
sudo ln -s /etc/nginx/sites-available/domotique /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

Nginx redirigera désormais les requêtes HTTP vers Gunicorn, qui fera tourner l'application Django.
Vérifiez l'état des services critiques :

```bash
sudo systemctl status mosquitto
sudo systemctl status gunicorn
sudo systemctl status nginx
```

> En cas de modification du code, rechargez Gunicorn avec `sudo systemctl restart gunicorn`.

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
