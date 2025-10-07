# Fonctionnement du firmware ESP8266

Ce firmware transforme l'ESP8266 en radiateur connecté piloté via MQTT. Il combine un portail de configuration Wi-Fi/MQTT et un client MQTT qui exécute les commandes reçues.

## Démarrage et portail de configuration

1. **Mode point d'accès** : à la mise sous tension, l'ESP8266 active `Radiateur-Setup`, un point d'accès ouvert.
2. **Portail captif** : dès qu'un appareil se connecte à ce Wi-Fi, un portail de connexion s'ouvre automatiquement (comme sur les hotspots publics). À défaut, l'interface reste accessible via `http://192.168.4.1/`. Le formulaire permet de saisir :
   - le SSID du réseau Wi-Fi à rejoindre ;
   - le mot de passe correspondant (facultatif si le Wi-Fi est ouvert) ;
   - l'adresse IP du serveur MQTT que l'appareil doit contacter.
3. **Enregistrement** : après validation, les informations sont stockées dans l'EEPROM (`DeviceConfig`). Elles sont automatiquement réutilisées aux démarrages suivants.
4. **Tentative de connexion** : le module coupe son point d'accès et tente de rejoindre le Wi-Fi saisi. Une fois le Wi-Fi opérationnel, le client MQTT est configuré avec l'IP fournie.

Si aucune configuration n'est présente, un serveur par défaut `192.168.1.151` est utilisé jusqu'à ce qu'une valeur soit fournie via l'interface.

## Fonctionnement réseau quotidien

- La boucle principale entretient en permanence la page de configuration (`server.handleClient()`) et surveille l'état Wi-Fi. Si la connexion Wi-Fi tombe, l'ESP8266 relance son point d'accès de configuration et retente régulièrement de rejoindre le réseau connu (`connectToSavedWifi`).
- Dès que le Wi-Fi est établi, l'AP est coupé et le client MQTT se reconnecte automatiquement au broker défini (`reconnect`).

## Pilotage par MQTT

- Le client s'abonne au topic `test` avec l'identifiant `Chambre`.
- Lorsqu'un message JSON est reçu, les champs `FROM`, `TO` et `COMMAND` sont vérifiés.
- Si le message provient de `Django` et est destiné à `Chambre`, la commande associée déclenche les fonctions : `modeComfort`, `modeEco`, `modeOff`, `modeHorsGel`, `clignoter` ou `checkEtat`.
- `checkEtat` publie l'état courant sur le même topic au format JSON.

## Reconfigurer le Wi-Fi ou le serveur MQTT

Pour changer de Wi-Fi, de mot de passe ou d'adresse de broker :

1. **Forcer le mode configuration** :
   - Coupez l'alimentation du module puis rallumez-le ; ou
   - Attendez qu'il perde la connexion (par exemple, éloignez le point d'accès actuel). Au prochain échec de liaison, `Radiateur-Setup` réapparaît automatiquement.
2. **Connexion au portail** : connectez-vous au Wi-Fi `Radiateur-Setup`, ouvrez `http://192.168.4.1/` et mettez à jour les champs souhaités.
3. **Validation** : après enregistrement, l'ESP8266 tente immédiatement de rejoindre le nouveau réseau et, si la connexion aboutit, se connecte au broker MQTT à l'adresse indiquée.
4. **Retour au service** : une fois la liaison établie, le point d'accès de configuration est coupé. Les nouvelles valeurs sont mémorisées pour les démarrages futurs.

Cette procédure peut être répétée autant de fois que nécessaire lors d'un déménagement ou d'une modification de la configuration réseau.
