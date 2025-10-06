# Simulateur de radiateurs MQTT

Ce dossier contient un script autonome permettant de simuler des radiateurs
connectés. Le script se connecte au broker MQTT défini dans les variables
d'environnement (ou via les options de la ligne de commande), écoute les
messages envoyés par l'application Django et publie des réponses factices.

## Utilisation

```bash
python simulator/fake_radiators.py --devices Cuisine Chambre --verbose
```

Sans arguments supplémentaires, le script réutilise les valeurs configurées
dans le projet (hôte, port, topic et liste des radiateurs via la variable
`MQTT_DEVICES`).

* Les commandes `STATE` provoquent l'envoi de l'état courant du radiateur.
* Toute autre commande reçue pour un radiateur met à jour son état et une
  réponse est automatiquement publiée afin d'informer Django du changement.

Interrompez le programme avec `Ctrl+C` pour quitter proprement.
