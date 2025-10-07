# Analyse du firmware ESP8266

## Fonctionnement général

Le firmware `main.ino` configure un ESP8266 comme client Wi-Fi et MQTT après une phase de provisionnement local. Au démarrage, le module crée un point d'accès ouvert `Radiateur-Setup` et héberge une page de configuration. L'utilisateur y saisit le SSID, le mot de passe Wi-Fi et **l'adresse IP du serveur MQTT**. Ces informations sont sauvegardées dans l'EEPROM et réutilisées aux démarrages suivants. Une fois connecté au réseau et au broker, l'appareil écoute sur le topic `test` et exécute une commande lorsque le message reçu contient les champs JSON `FROM`, `TO` et `COMMAND`. Les commandes `COMFORT`, `ECO`, `OFF`, `HORSGEL`, `STATE` déclenchent respectivement les fonctions qui pilotent les broches de sortie. La fonction `checkEtat()` renvoie l'état actuel en publiant un message JSON.

## Points qui fonctionnent bien

- **Portail de configuration autonome** : le point d'accès intégré et le serveur HTTP permettent de reconfigurer le Wi-Fi et l'IP du broker sans recompiler le firmware.【F:ESP8266/main.ino†L48-L115】【F:ESP8266/main.ino†L186-L251】
- **Connexion Wi-Fi et MQTT** : les fonctions `setup()` et `reconnect()` gèrent correctement la connexion au réseau Wi-Fi et la reconnexion MQTT si la liaison se perd.【F:ESP8266/main.ino†L48-L115】
- **Traitement JSON** : l'utilisation de `ArduinoJson` pour décoder les messages et vérifier les champs garantit que seules les commandes destinées à ce client (`TO == "Chambre"`) sont exécutées.【F:ESP8266/main.ino†L117-L174】
- **Pilotage des sorties** : les fonctions `modeComfort()`, `modeEco()`, `modeHorsGel()` et `modeOff()` écrivent clairement les niveaux logiques attendus pour chaque mode sur les deux sorties configurées.【F:ESP8266/main.ino†L118-L136】
- **Retour d'état** : `checkEtat()` lit les sorties actuelles, dérive le mode et publie un message JSON structuré à destination du serveur Django.【F:ESP8266/main.ino†L138-L158】

## Points à améliorer ou risques

1. **Stockage non chiffré** : les identifiants et l'IP du broker restent enregistrés en clair dans l'EEPROM. Sur un module compromis physiquement, ils peuvent être extraits. L'ajout d'un chiffrement léger ou d'un mot de passe pour le portail limiterait ce risque.【F:ESP8266/main.ino†L189-L251】
2. **Gestion minimale des erreurs** : en cas d'échec de connexion Wi-Fi ou MQTT, le code boucle indéfiniment sans rétroaction ni délai exponentiel. Ajouter des traces série ou un mécanisme de redémarrage éviterait les blocages silencieux.【F:ESP8266/main.ino†L74-L115】【F:ESP8266/main.ino†L174-L185】
3. **Sécurité MQTT** : la connexion au broker se fait sans authentification ni TLS. Si le réseau n'est pas isolé, un acteur malveillant peut publier des commandes ou écouter l'état. Envisager l'usage d'identifiants MQTT ou d'un canal chiffré.
4. **Validation des commandes** : les valeurs du champ `COMMAND` sont comparées à des chaînes en clair. Il serait prudent de prévoir un `else` qui ignore explicitement les commandes inconnues et éventuellement journalise la tentative pour faciliter le diagnostic.【F:ESP8266/main.ino†L129-L174】
5. **État des broches au démarrage** : les sorties sont mises à `LOW` immédiatement, ce qui force le mode confort avant de recevoir une commande. Selon l'installation, il pourrait être préférable d'attendre l'ordre du serveur ou de mémoriser le dernier état connu.【F:ESP8266/main.ino†L62-L71】
6. **LED de statut** : la fonction `clignoter()` est utilisée pour signaler l'initialisation, mais la LED reste ensuite allumée (`HIGH`). Ajouter un indicateur visuel pour la connexion Wi-Fi/MQTT faciliterait le diagnostic sur site.【F:ESP8266/main.ino†L66-L71】【F:ESP8266/main.ino†L115-L123】
7. **Robustesse JSON** : si un message manque un champ attendu, `doc["..."]` renverra une chaîne vide. Tester la présence des clés (avec `containsKey`) permettrait de rejeter proprement les messages mal formés avant d'accéder aux valeurs.【F:ESP8266/main.ino†L129-L174】

## Pistes d'évolution

- Externaliser la configuration Wi-Fi et MQTT (SPIFFS, LittleFS, OTA) pour pouvoir reconfigurer les modules sans reprogrammer.
- Ajouter une commande `PING`/`PONG` ou un `last will` MQTT pour surveiller la disponibilité des radiateurs.
- Mettre en place un watchdog logiciel ou matériel pour redémarrer automatiquement en cas de blocage prolongé.
- Activer la liaison série (`Serial.begin`) pendant le développement pour faciliter le débogage, puis la désactiver uniquement en production.

Ces ajustements amélioreront la sécurité, la résilience et la maintenabilité du firmware.
