#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <EEPROM.h>
#include <cstring>


#define LED_BUILTIN 2

const uint16_t mqtt_port = 1883;
const char* mqtt_topic = "test";
const char* mqtt_client_id = "Chambre";

const char* ap_ssid = "Radiateur-Setup";
const char* default_mqtt_server = "192.168.1.151";
const int EEPROM_SIZE = 256;
const int RECONNECT_INTERVAL = 10000; // 10 secondes

struct DeviceConfig {
  char ssid[32];
  char password[64];
  char mqttServer[64];
};



const int pinHigh = 14;
const int pinLow = 12;


WiFiClient espClient;
PubSubClient client(espClient);
ESP8266WebServer server(80);

DeviceConfig deviceConfig;
bool credentialsLoaded = false;
unsigned long lastReconnectAttempt = 0;
bool apActive = false;

void startAccessPoint();
void setupServer();
void handleRoot();
void handleSave();
bool loadConfig();
void saveConfig(const DeviceConfig &data);
bool connectToSavedWifi(bool blocking = false);

void setup() {
  // Serial.begin(115200);
  // delay(10);

  EEPROM.begin(EEPROM_SIZE);
  credentialsLoaded = loadConfig();
  if (strlen(deviceConfig.mqttServer) == 0) {
    strncpy(deviceConfig.mqttServer, default_mqtt_server, sizeof(deviceConfig.mqttServer) - 1);
    deviceConfig.mqttServer[sizeof(deviceConfig.mqttServer) - 1] = '\0';
  }

  pinMode(pinHigh, OUTPUT);
  pinMode(pinLow, OUTPUT);
  pinMode(LED_BUILTIN, OUTPUT);

  digitalWrite(pinHigh, LOW);
  digitalWrite(pinLow, LOW);

  clignoter(3000, 500);

  WiFi.mode(WIFI_AP_STA);
  startAccessPoint();
  setupServer();

  connectToSavedWifi(true);

  // Configuration du client MQTT
  client.setServer(deviceConfig.mqttServer, mqtt_port);
  client.setCallback(callback);
}

void loop() {
  server.handleClient();

  if (WiFi.status() != WL_CONNECTED) {
    if (!apActive) {
      startAccessPoint();
    }
    unsigned long now = millis();
    if (credentialsLoaded && now - lastReconnectAttempt > RECONNECT_INTERVAL) {
      lastReconnectAttempt = now;
      connectToSavedWifi();
    }
    return;
  }

  if (apActive) {
    WiFi.softAPdisconnect(true);
    apActive = false;
  }

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

void startAccessPoint() {
  WiFi.softAP(ap_ssid);
  apActive = true;
}

void setupServer() {
  server.on("/", HTTP_GET, handleRoot);
  server.on("/save", HTTP_POST, handleSave);
  server.begin();
}

void handleRoot() {
  String page = "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Configuration WiFi</title></head><body>";
  page += "<h1>Configuration du WiFi</h1>";
  page += "<p>Statut actuel : ";
  if (WiFi.status() == WL_CONNECTED) {
    page += "connecté à " + WiFi.SSID();
  } else {
    page += "non connecté";
  }
  page += "</p>";
  page += "<form method='POST' action='/save'>";
  page += "<label>SSID : <input name='ssid' value='";
  if (credentialsLoaded) {
    page += deviceConfig.ssid;
  }
  page += "' required></label><br><br>";
  page += "<label>Mot de passe : <input name='password' type='password' placeholder='Mot de passe WiFi'></label><br><br>";
  page += "<label>Serveur MQTT : <input name='mqtt_server' value='";
  if (strlen(deviceConfig.mqttServer) > 0) {
    page += deviceConfig.mqttServer;
  }
  page += "' required></label><br><br>";
  page += "<button type='submit'>Enregistrer</button></form></body></html>";
  server.send(200, "text/html", page);
}

void handleSave() {
  if (!server.hasArg("ssid") || !server.hasArg("mqtt_server")) {
    server.send(400, "text/plain", "Paramètres manquants");
    return;
  }

  String newSsid = server.arg("ssid");
  String newPassword = server.arg("password");
  String newMqttServer = server.arg("mqtt_server");

  newSsid.trim();
  newPassword.trim();
  newMqttServer.trim();

  if (newSsid.length() == 0 || newMqttServer.length() == 0) {
    server.send(400, "text/plain", "Le SSID et l'adresse du serveur MQTT sont obligatoires");
    return;
  }

  newSsid.toCharArray(deviceConfig.ssid, sizeof(deviceConfig.ssid));
  newPassword.toCharArray(deviceConfig.password, sizeof(deviceConfig.password));
  newMqttServer.toCharArray(deviceConfig.mqttServer, sizeof(deviceConfig.mqttServer));
  saveConfig(deviceConfig);
  credentialsLoaded = strlen(deviceConfig.ssid) > 0;

  client.setServer(deviceConfig.mqttServer, mqtt_port);
  client.disconnect();

  bool connected = connectToSavedWifi(true);

  if (connected) {
    reconnect();
    server.send(200, "text/html", "<html><body><h1>Connexion réussie</h1><p>L'ESP8266 est connecté au réseau \"" + newSsid + "\" et utilisera le serveur MQTT \"" + newMqttServer + "\".</p></body></html>");
  } else {
    server.send(200, "text/html", "<html><body><h1>Connexion impossible</h1><p>Vérifiez les informations saisies et réessayez.</p></body></html>");
  }
}

bool loadConfig() {
  memset(&deviceConfig, 0, sizeof(deviceConfig));
  EEPROM.get(0, deviceConfig);

  bool wifiConfigured = deviceConfig.ssid[0] != '\0' && deviceConfig.ssid[0] != char(0xFF);
  bool mqttConfigured = deviceConfig.mqttServer[0] != '\0' && deviceConfig.mqttServer[0] != char(0xFF);

  if (!wifiConfigured) {
    memset(deviceConfig.ssid, 0, sizeof(deviceConfig.ssid));
    memset(deviceConfig.password, 0, sizeof(deviceConfig.password));
  }
  if (!mqttConfigured) {
    memset(deviceConfig.mqttServer, 0, sizeof(deviceConfig.mqttServer));
  }

  return wifiConfigured;
}

void saveConfig(const DeviceConfig &data) {
  EEPROM.put(0, data);
  EEPROM.commit();
}

bool connectToSavedWifi(bool blocking) {
  if (!credentialsLoaded || strlen(deviceConfig.ssid) == 0) {
    return false;
  }

  WiFi.begin(deviceConfig.ssid, deviceConfig.password);
  lastReconnectAttempt = millis();

  if (!blocking) {
    return true;
  }

  unsigned long startAttempt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startAttempt < 15000) {
    delay(500);
  }

  if (WiFi.status() == WL_CONNECTED) {
    WiFi.softAPdisconnect(true);
    apActive = false;
    return true;
  }

  return false;
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










