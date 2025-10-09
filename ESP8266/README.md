# Fonctionnement du firmware ESP8266

Ce firmware transforme l'ESP8266 en radiateur connecté piloté via MQTT. Il combine un portail de configuration Wi-Fi/MQTT et un client MQTT qui exécute les commandes reçues.

## Démarrage et portail de configuration

1. **Mode point d'accès** : à la mise sous tension, l'ESP8266 active `Radiateur-Setup`, un point d'accès ouvert.
2. **Portail captif** : dès qu'un appareil se connecte à ce Wi-Fi, un portail de connexion s'ouvre automatiquement (comme sur les hotspots publics). À défaut, l'interface reste accessible via `http://192.168.4.1/`. Le formulaire permet de saisir :
   - le SSID du réseau Wi-Fi à rejoindre ;
   - le mot de passe correspondant (facultatif si le Wi-Fi est ouvert) ;
   - le **nom de l'appareil**, qui servira d'identifiant MQTT.
3. **Enregistrement** : après validation, les informations sont stockées dans l'EEPROM (`DeviceConfig`). Elles sont automatiquement réutilisées aux démarrages suivants. Si aucun nom n'est fourni (ancien firmware), un identifiant de secours `RADIATEUR-XXXXXX` basé sur l'ID du module est généré et mémorisé.
4. **Tentative de connexion** : le module coupe son point d'accès et tente de rejoindre le Wi-Fi saisi. Il reste ensuite à l'écoute des instructions du serveur Django pour connaître l'adresse du broker MQTT.

## Fonctionnement réseau quotidien

- La boucle principale entretient en permanence la page de configuration (`server.handleClient()`) et surveille l'état Wi-Fi. Si la connexion Wi-Fi tombe, l'ESP8266 relance son point d'accès de configuration et retente régulièrement de rejoindre le réseau connu (`connectToSavedWifi`).
- Dès que le Wi-Fi est établi, l'AP est coupé. Tant que l'adresse du broker n'a pas été fournie, l'ESP8266 reste en attente. Dès que le serveur Django lui transmet l'IP détectée, le client MQTT est configuré et la connexion est tentée automatiquement (`reconnect`).

## Pilotage par MQTT

- Le client s'abonne au topic `test` avec l'identifiant issu du portail (champ *Nom de l'appareil*).
- Lorsqu'un message JSON est reçu, les champs `FROM`, `TO` et `COMMAND` sont vérifiés.
- Si le message provient de `Django` et est destiné à ce nom, la commande associée déclenche les fonctions : `modeComfort`, `modeEco`, `modeOff`, `modeHorsGel`, `clignoter` ou `checkEtat`.
- `checkEtat` publie l'état courant sur le même topic au format JSON.

## Gestion de la mémoire d'état et du redémarrage

- Le firmware mémorise désormais en EEPROM le dernier mode appliqué (Confort, Éco, Hors gel ou Off). Lorsqu'il redémarre après
  une coupure de courant, l'ESP8266 restaure cette consigne sans passer par une séquence de clignotements parasites sur les
  fils `pinHigh`/`pinLow`.
- Au démarrage, les broches de pilotage sont laissées en haute impédance puis configurées en sortie uniquement une fois que la
  configuration a été relue. Cette précaution évite que le module ne reste bloqué si les broches sont déjà reliées au montage au
  moment où l'alimentation 3,3&nbsp;V revient (cas typique après une coupure secteur sur le radiateur).
- Les changements d'état sont enregistrés avec une temporisation minimale d'une seconde pour limiter l'usure de l'EEPROM tout en
  garantissant la reprise du dernier mode en cas de redémarrage brusque.

## Détection et administration depuis Django

- L'ESP8266 expose une route HTTP `GET /identify` qui renvoie un JSON avec son nom, son adresse IP locale et son adresse MAC. Le serveur Django balaie régulièrement le réseau local via cette route lorsqu'on demande l'ajout d'appareils.
- Une fois détecté, l'appareil est ajouté automatiquement dans `devices.json`. Les noms et IP sont affichés sur la page Options.
- Le serveur Django envoie ensuite une requête `POST /mqtt-host` au module pour lui transmettre l'adresse locale du broker. L'ESP8266 l'enregistre en EEPROM et tente immédiatement de se connecter si le Wi-Fi est actif.
- La route `POST /device-name` permet de renommer l'appareil à distance ; le serveur Django l'utilise lorsqu'un renommage est effectué depuis l'interface. Le firmware met alors à jour l'EEPROM et se reconnecte au broker avec le nouvel identifiant.
- La page Options offre aussi la possibilité de supprimer un radiateur du registre JSON côté serveur.

## Reconfigurer le Wi-Fi

Pour changer de Wi-Fi ou de mot de passe :

1. **Forcer le mode configuration** :
   - Coupez l'alimentation du module puis rallumez-le ; ou
   - Attendez qu'il perde la connexion (par exemple, éloignez le point d'accès actuel). Au prochain échec de liaison, `Radiateur-Setup` réapparaît automatiquement.
2. **Connexion au portail** : connectez-vous au Wi-Fi `Radiateur-Setup`, ouvrez `http://192.168.4.1/` et mettez à jour les champs souhaités.
3. **Validation** : après enregistrement, l'ESP8266 tente immédiatement de rejoindre le nouveau réseau.
4. **Retour au service** : une fois la liaison établie, le point d'accès de configuration est coupé. Le serveur Django redonnera automatiquement l'adresse du broker lors du prochain scan.

Cette procédure peut être répétée autant de fois que nécessaire lors d'un déménagement ou d'une modification de la configuration réseau. Pour renommer l'appareil, il suffit d'utiliser le bouton « Renommer » de la page Options : Django met à jour l'ESP8266 via HTTP puis remplace l'entrée correspondante dans `devices.json`.
