#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>


#define LED_BUILTIN 2

const char* ssid = "Bbox-1A72D098";
const char* password = "N2vGETVJ93ueSXseMX";
const char* mqtt_server = "192.168.1.151";
const char* mqtt_topic = "test";
const char* mqtt_client_id = "Chambre"; 



const int pinHigh = 14;
const int pinLow = 12;


WiFiClient espClient;
PubSubClient client(espClient);

void setup() {
  // Serial.begin(115200);
  // delay(10);

  pinMode(pinHigh, OUTPUT);
  pinMode(pinLow, OUTPUT);
  pinMode(LED_BUILTIN, OUTPUT);

  digitalWrite(pinHigh, LOW);
  digitalWrite(pinLow, LOW);
  
  clignoter(3000, 500);

  // Connexion au réseau Wi-Fi
  // Serial.println();
  // Serial.print("Connexion au réseau Wi-Fi ");
  // Serial.println(ssid);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    // Serial.print(".");
  }
  // Serial.println();
  // Serial.println("Connecté au réseau Wi-Fi");
  
  // Configuration du client MQTT
  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  // Lecture de l'entrée série et publication de messages MQTT
  if (Serial.available()) {
    String input = Serial.readStringUntil('\n');
    publishMessage(input);
  }
}

void callback(char* topic, byte* payload, unsigned int length) {
  String texte;
  
  // Serial.print("Contenu du message: ");
  for (int i = 0; i < length; i++) {
    texte += (char)payload[i];
  }
  // Serial.print(texte);
  // Serial.println();

  // if (texte == "CLIGNOTER") clignoter(2000, 500);
  // else if (texte == "COMFORT") modeComfort();
  // else if (texte == "ECO") modeEco();
  // else if (texte == "OFF") modeOff();
  // else if (texte == "HORSGEL") modeHorsGel();
  // else if (texte == "ETAT") checkEtat();

  DynamicJsonDocument doc(JSON_OBJECT_SIZE(3));
  DeserializationError error = deserializeJson(doc, texte);

    // Vérifiez s'il y a eu une erreur d'analyse JSON
  if (error) {
    // Serial.print("Erreur d'analyse JSON: ");
    // Serial.println(error.c_str());
    return;
  }

  const String from = doc["FROM"];
  const String to = doc["TO"];
  const String command = doc["COMMAND"];
  
  if(from=="Django" && to==mqtt_client_id){
      if (command == "CLIGNOTER") clignoter(2000, 500);
      else if (command == "COMFORT") modeComfort();
      else if (command == "ECO") modeEco();
      else if (command == "OFF") modeOff();
      else if (command == "HORSGEL") modeHorsGel();
      else if (command == "STATE") checkEtat();
  }
  // else {
  //   Serial.println("Ne nous concerne pas");
  // }

}

void publishMessage(String message) {
  client.publish(mqtt_topic, message.c_str());
  // if (client.publish(mqtt_topic, message.c_str())) {
    // Serial.print("Message MQTT publié avec succès: ");
    // Serial.println(message);
  // } else {
    // Serial.print("Échec de la publication du message MQTT: ");
    // Serial.println(message);
  // }
}

void reconnect() {
  while (!client.connected()) {
    // Serial.print("Tentative de connexion au serveur MQTT...");
    
    if (client.connect(mqtt_client_id)) {
      // Serial.println("Connecté au serveur MQTT");
      client.subscribe(mqtt_topic);
    } else {
      // Serial.print("Échec, rc=");
      // Serial.print(client.state());
      // Serial.println(" Réessayez dans 5 secondes.");
      delay(5000);
    }
  }
}

void clignoter(int totalDuration, int blinkSpeed) {
  int numberOfBlinks = totalDuration / (2 * blinkSpeed);
  for (int i = 0; i < numberOfBlinks; i++) {
    digitalWrite(LED_BUILTIN, LOW);
    delay(blinkSpeed);
    digitalWrite(LED_BUILTIN, HIGH);
    delay(blinkSpeed);
  }
}

void modeComfort(){
    digitalWrite(pinHigh, LOW);
    digitalWrite(pinLow, LOW);
}

void modeEco(){   
  digitalWrite(pinHigh, HIGH);
  digitalWrite(pinLow, HIGH);
}

void modeHorsGel(){
  digitalWrite(pinHigh, LOW);
  digitalWrite(pinLow, HIGH); 
}

void modeOff(){
  digitalWrite(pinHigh, HIGH);
  digitalWrite(pinLow, LOW);
}

void checkEtat(){
  String mode;
  if (digitalRead(pinHigh) == LOW && digitalRead(pinLow) == LOW) {
    mode = "COMFORT";
  } else if (digitalRead(pinHigh) == HIGH && digitalRead(pinLow) == HIGH) {
    mode = "ECO";
  } else if (digitalRead(pinHigh) == HIGH && digitalRead(pinLow) == LOW) {
    mode = "OFF";
  } else {
    mode = "HORS GEL";
  }

  const size_t capacity = JSON_OBJECT_SIZE(3); // Réglez la capacité en fonction du nombre de paires clé-valeur que vous prévoyez d'avoir
  DynamicJsonDocument message(capacity);
  message["FROM"] = mqtt_client_id;
  message["TO"] = "Django";
  message["COMMAND"] = mode;

  String jsonStr;
  serializeJson(message, jsonStr);
  delay(10);
  publishMessage(jsonStr);

}










