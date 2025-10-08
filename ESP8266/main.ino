#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <EEPROM.h>
#include <DNSServer.h>
#include <cstring>


#define LED_BUILTIN 2

const uint16_t mqtt_port = 1883;
const char* mqtt_topic = "test";

const size_t DEVICE_NAME_MAX_LENGTH = 64;

const char* ap_ssid = "Radiateur-Setup";
const char* default_mqtt_server = "192.168.1.151";
const int EEPROM_SIZE = 256;
const int RECONNECT_INTERVAL = 10000; // 10 secondes
const byte DNS_PORT = 53;

struct DeviceConfig {
  char ssid[32];
  char password[64];
  char mqttServer[64];
  char deviceName[DEVICE_NAME_MAX_LENGTH];
};



const int pinHigh = 14;
const int pinLow = 12;


WiFiClient espClient;
PubSubClient client(espClient);
ESP8266WebServer server(80);
DNSServer dnsServer;

DeviceConfig deviceConfig;
bool credentialsLoaded = false;
unsigned long lastReconnectAttempt = 0;
bool apActive = false;
char mqttClientId[DEVICE_NAME_MAX_LENGTH];

void startAccessPoint();
void stopAccessPoint();
void setupServer();
void handleRoot();
void handleSave();
void handleNotFound();
bool handleCaptivePortal();
void handleIdentify();
void handleDeviceName();
bool loadConfig();
void saveConfig(const DeviceConfig &data);
bool connectToSavedWifi(bool blocking = false);
bool ensureDeviceName();
void refreshMqttClientId();

void setup() {
  // Serial.begin(115200);
  // delay(10);

  EEPROM.begin(EEPROM_SIZE);
  credentialsLoaded = loadConfig();
  if (strlen(deviceConfig.mqttServer) == 0) {
    strncpy(deviceConfig.mqttServer, default_mqtt_server, sizeof(deviceConfig.mqttServer) - 1);
    deviceConfig.mqttServer[sizeof(deviceConfig.mqttServer) - 1] = '\0';
  }

  bool nameAssigned = ensureDeviceName();
  refreshMqttClientId();
  if (nameAssigned) {
    saveConfig(deviceConfig);
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

  if (apActive) {
    dnsServer.processNextRequest();
  }

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
    stopAccessPoint();
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
  
  if(from=="Django" && to==mqttClientId){
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
    
    if (client.connect(mqttClientId)) {
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
  IPAddress apIP = WiFi.softAPIP();
  dnsServer.start(DNS_PORT, "*", apIP);
  apActive = true;
}

void setupServer() {
  server.on("/", HTTP_GET, handleRoot);
  server.on("/save", HTTP_POST, handleSave);
  server.on("/identify", HTTP_GET, handleIdentify);
  server.on("/device-name", HTTP_POST, handleDeviceName);
  server.onNotFound(handleNotFound);
  server.begin();
}

void handleRoot() {
  if (handleCaptivePortal()) {
    return;
  }

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
  page += "<label>Nom de l'appareil : <input name='device_name' maxlength='";
  page += String(DEVICE_NAME_MAX_LENGTH - 1);
  page += "' value='";
  if (strlen(deviceConfig.deviceName) > 0) {
    page += deviceConfig.deviceName;
  }
  page += "' required></label><br><br>";
  page += "<label>Serveur MQTT : <input name='mqtt_server' value='";
  if (strlen(deviceConfig.mqttServer) > 0) {
    page += deviceConfig.mqttServer;
  }
  page += "' required></label><br><br>";
  page += "<button type='submit'>Enregistrer</button></form></body></html>";
  server.send(200, "text/html", page);
}

void handleSave() {
  if (!server.hasArg("ssid") || !server.hasArg("mqtt_server") || !server.hasArg("device_name")) {
    server.send(400, "text/plain", "Paramètres manquants");
    return;
  }

  String newSsid = server.arg("ssid");
  String newPassword = server.arg("password");
  String newMqttServer = server.arg("mqtt_server");
  String newDeviceName = server.arg("device_name");

  newSsid.trim();
  newPassword.trim();
  newMqttServer.trim();
  newDeviceName.trim();

  if (newSsid.length() == 0 || newMqttServer.length() == 0 || newDeviceName.length() == 0) {
    server.send(400, "text/plain", "Le SSID, le nom de l'appareil et l'adresse du serveur MQTT sont obligatoires");
    return;
  }

  if (newDeviceName.length() >= DEVICE_NAME_MAX_LENGTH) {
    server.send(400, "text/plain", "Le nom de l'appareil est trop long");
    return;
  }

  newSsid.toCharArray(deviceConfig.ssid, sizeof(deviceConfig.ssid));
  newPassword.toCharArray(deviceConfig.password, sizeof(deviceConfig.password));
  newMqttServer.toCharArray(deviceConfig.mqttServer, sizeof(deviceConfig.mqttServer));
  newDeviceName.toCharArray(deviceConfig.deviceName, sizeof(deviceConfig.deviceName));
  saveConfig(deviceConfig);
  credentialsLoaded = strlen(deviceConfig.ssid) > 0;

  refreshMqttClientId();
  client.setServer(deviceConfig.mqttServer, mqtt_port);
  client.disconnect();

  bool connected = connectToSavedWifi(true);

  if (connected) {
    reconnect();
    server.send(200, "text/html", "<html><body><h1>Connexion réussie</h1><p>L'ESP8266 est connecté au réseau \"" + newSsid + "\" et utilisera le serveur MQTT \"" + newMqttServer + "\".</p><p>Nom de l'appareil&nbsp;: " + newDeviceName + "</p></body></html>");
  } else {
    server.send(200, "text/html", "<html><body><h1>Connexion impossible</h1><p>Vérifiez les informations saisies et réessayez.</p></body></html>");
  }
}

void stopAccessPoint() {
  dnsServer.stop();
  WiFi.softAPdisconnect(true);
  apActive = false;
}

bool loadConfig() {
  memset(&deviceConfig, 0, sizeof(deviceConfig));
  EEPROM.get(0, deviceConfig);

  bool wifiConfigured = deviceConfig.ssid[0] != '\0' && deviceConfig.ssid[0] != char(0xFF);
  bool mqttConfigured = deviceConfig.mqttServer[0] != '\0' && deviceConfig.mqttServer[0] != char(0xFF);
  bool nameConfigured = deviceConfig.deviceName[0] != '\0' && deviceConfig.deviceName[0] != char(0xFF);

  if (!wifiConfigured) {
    memset(deviceConfig.ssid, 0, sizeof(deviceConfig.ssid));
    memset(deviceConfig.password, 0, sizeof(deviceConfig.password));
  }
  if (!mqttConfigured) {
    memset(deviceConfig.mqttServer, 0, sizeof(deviceConfig.mqttServer));
  }
  if (!nameConfigured) {
    memset(deviceConfig.deviceName, 0, sizeof(deviceConfig.deviceName));
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
    stopAccessPoint();
    return true;
  }

  return false;
}

bool handleCaptivePortal() {
  if (!apActive) {
    return false;
  }

  String host = server.hostHeader();
  if (!host.length()) {
    return false;
  }

  IPAddress apIP = WiFi.softAPIP();
  String apIpStr = apIP.toString();

  if (host == apIpStr || host == String(ap_ssid) || host == apIpStr + ":80") {
    return false;
  }

  server.sendHeader("Location", String("http://") + apIpStr);
  server.send(302, "text/html", "<!DOCTYPE html><html><head><meta http-equiv='refresh' content='0; url=http://" + apIpStr + "' /></head><body>Redirection vers le portail de configuration…</body></html>");
  return true;
}

void handleIdentify() {
  StaticJsonDocument<200> doc;
  doc["device_type"] = "esp8266-radiator";
  doc["name"] = deviceConfig.deviceName;
  doc["ip_address"] = WiFi.localIP().toString();
  doc["mac_address"] = WiFi.macAddress();

  String payload;
  serializeJson(doc, payload);
  server.send(200, "application/json", payload);
}

void handleDeviceName() {
  if (!server.hasArg("plain")) {
    server.send(400, "application/json", "{\"error\":\"Requête invalide\"}");
    return;
  }

  StaticJsonDocument<128> doc;
  DeserializationError error = deserializeJson(doc, server.arg("plain"));
  if (error) {
    server.send(400, "application/json", "{\"error\":\"JSON invalide\"}");
    return;
  }

  const char* requestedName = doc["name"];
  if (requestedName == nullptr) {
    server.send(400, "application/json", "{\"error\":\"Nom manquant\"}");
    return;
  }

  String newName = String(requestedName);
  newName.trim();
  if (newName.length() == 0) {
    server.send(400, "application/json", "{\"error\":\"Nom invalide\"}");
    return;
  }
  if (newName.length() >= DEVICE_NAME_MAX_LENGTH) {
    server.send(400, "application/json", "{\"error\":\"Nom trop long\"}");
    return;
  }

  newName.toCharArray(deviceConfig.deviceName, sizeof(deviceConfig.deviceName));
  saveConfig(deviceConfig);
  refreshMqttClientId();

  if (client.connected()) {
    client.disconnect();
  }
  if (WiFi.status() == WL_CONNECTED) {
    reconnect();
  }

  StaticJsonDocument<96> response;
  response["status"] = "ok";
  response["name"] = deviceConfig.deviceName;
  String payload;
  serializeJson(response, payload);
  server.send(200, "application/json", payload);
}

void handleNotFound() {
  if (handleCaptivePortal()) {
    return;
  }

  server.send(404, "text/plain", "Not found");
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
  message["FROM"] = mqttClientId;
  message["TO"] = "Django";
  message["COMMAND"] = mode;

  String jsonStr;
  serializeJson(message, jsonStr);
  delay(10);
  publishMessage(jsonStr);

}

bool ensureDeviceName() {
  if (deviceConfig.deviceName[0] == '\0' || deviceConfig.deviceName[0] == char(0xFF)) {
    String fallback = String("Radiateur-");
    fallback += String(ESP.getChipId(), HEX);
    fallback.toUpperCase();
    fallback.toCharArray(deviceConfig.deviceName, sizeof(deviceConfig.deviceName));
    return true;
  }
  return false;
}

void refreshMqttClientId() {
  if (deviceConfig.deviceName[0] == '\0') {
    ensureDeviceName();
  }
  strncpy(mqttClientId, deviceConfig.deviceName, sizeof(mqttClientId) - 1);
  mqttClientId[sizeof(mqttClientId) - 1] = '\0';
}










