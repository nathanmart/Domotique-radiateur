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
const int EEPROM_SIZE = 256;
const int RECONNECT_INTERVAL = 10000; // 10 secondes
const unsigned long MQTT_RECONNECT_INTERVAL = 5000; // 5 secondes
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
unsigned long lastMqttReconnectAttempt = 0;
bool apActive = false;
char mqttClientId[DEVICE_NAME_MAX_LENGTH];

enum LedPatternId : uint8_t {
  LED_PATTERN_WIFI_CONNECTING = 0,
  LED_PATTERN_WAITING_FOR_SERVER,
  LED_PATTERN_WAITING_FOR_MQTT,
  LED_PATTERN_ONLINE,
  LED_PATTERN_STATE_CHANGED,
};

struct BlinkStep {
  bool ledOn;
  uint16_t durationMs;
};

struct LedPatternDefinition {
  const BlinkStep* steps;
  size_t length;
};

const bool LED_ACTIVE_STATE = LOW;
const bool LED_INACTIVE_STATE = HIGH;

const BlinkStep LED_PATTERN_WIFI_CONNECTING_STEPS[] = {
  {true, 150},
  {false, 150},
};

const BlinkStep LED_PATTERN_WAITING_FOR_SERVER_STEPS[] = {
  {true, 200},
  {false, 200},
  {true, 200},
  {false, 800},
};

const BlinkStep LED_PATTERN_WAITING_FOR_MQTT_STEPS[] = {
  {true, 200},
  {false, 200},
  {true, 200},
  {false, 200},
  {true, 200},
  {false, 800},
};

const BlinkStep LED_PATTERN_ONLINE_STEPS[] = {
  {true, 60},
  {false, 2940},
};

const BlinkStep LED_PATTERN_STATE_CHANGED_STEPS[] = {
  {true, 120},
  {false, 120},
  {true, 120},
  {false, 600},
};

const unsigned long LED_PATTERN_STATE_CHANGED_DURATION_MS = 960;

const LedPatternDefinition LED_PATTERNS[] = {
  {LED_PATTERN_WIFI_CONNECTING_STEPS, sizeof(LED_PATTERN_WIFI_CONNECTING_STEPS) / sizeof(BlinkStep)},
  {LED_PATTERN_WAITING_FOR_SERVER_STEPS, sizeof(LED_PATTERN_WAITING_FOR_SERVER_STEPS) / sizeof(BlinkStep)},
  {LED_PATTERN_WAITING_FOR_MQTT_STEPS, sizeof(LED_PATTERN_WAITING_FOR_MQTT_STEPS) / sizeof(BlinkStep)},
  {LED_PATTERN_ONLINE_STEPS, sizeof(LED_PATTERN_ONLINE_STEPS) / sizeof(BlinkStep)},
  {LED_PATTERN_STATE_CHANGED_STEPS, sizeof(LED_PATTERN_STATE_CHANGED_STEPS) / sizeof(BlinkStep)},
};

LedPatternId baseLedPattern = LED_PATTERN_WIFI_CONNECTING;
LedPatternId currentLedPattern = LED_PATTERN_WIFI_CONNECTING;
size_t currentLedStep = 0;
unsigned long currentLedStepStarted = 0;
bool ledPatternInitialised = false;
bool statusLedSuspended = false;
bool overridePatternActive = false;
unsigned long overridePatternDeadline = 0;

enum RadiatorMode : uint8_t {
  MODE_UNKNOWN = 0,
  MODE_COMFORT,
  MODE_ECO,
  MODE_HORSGEL,
  MODE_OFF,
};

RadiatorMode appliedMode = MODE_UNKNOWN;

void startAccessPoint();
void stopAccessPoint();
void setupServer();
void handleRoot();
void handleSave();
void handleNotFound();
bool handleCaptivePortal();
void handleIdentify();
void handleDeviceName();
void handleMqttHost();
bool loadConfig();
void saveConfig(const DeviceConfig &data);
bool connectToSavedWifi(bool blocking = false);
bool ensureDeviceName();
void refreshMqttClientId();
bool isMqttConfigured();
void configureMqttClient();
void updateStatusLed();
void setStatusLedPattern(LedPatternId pattern);
void suspendStatusLed(bool suspend);
bool attemptMqttReconnect(bool forceAttempt = false);
void setBaseStatusLedPattern(LedPatternId pattern);
void activateTemporaryLedPattern(LedPatternId pattern, unsigned long durationMs);
void triggerStateChangeBlink();
RadiatorMode detectCurrentMode();
const char* modeToCommand(RadiatorMode mode);
void registerAppliedMode(RadiatorMode mode);

void applyLedState(bool on) {
  digitalWrite(LED_BUILTIN, on ? LED_ACTIVE_STATE : LED_INACTIVE_STATE);
}

void resetLedPatternState() {
  const LedPatternDefinition& pattern = LED_PATTERNS[currentLedPattern];
  currentLedStep = 0;
  currentLedStepStarted = millis();
  ledPatternInitialised = true;
  if (pattern.length > 0) {
    applyLedState(pattern.steps[0].ledOn);
  }
}

void setStatusLedPattern(LedPatternId pattern) {
  if (currentLedPattern == pattern && ledPatternInitialised && !statusLedSuspended) {
    return;
  }
  currentLedPattern = pattern;
  ledPatternInitialised = false;
}

void suspendStatusLed(bool suspend) {
  statusLedSuspended = suspend;
  if (suspend) {
    overridePatternActive = false;
  } else {
    ledPatternInitialised = false;
    setStatusLedPattern(baseLedPattern);
  }
}

void advanceStatusLed() {
  if (statusLedSuspended) {
    return;
  }
  if (overridePatternActive) {
    unsigned long now = millis();
    if ((long)(now - overridePatternDeadline) >= 0) {
      overridePatternActive = false;
      setStatusLedPattern(baseLedPattern);
    }
  }
  if (!ledPatternInitialised) {
    resetLedPatternState();
  }
  const LedPatternDefinition& pattern = LED_PATTERNS[currentLedPattern];
  if (pattern.length == 0) {
    return;
  }
  unsigned long now = millis();
  const BlinkStep* steps = pattern.steps;
  const BlinkStep& step = steps[currentLedStep];
  if (now - currentLedStepStarted >= step.durationMs) {
    currentLedStep = (currentLedStep + 1) % pattern.length;
    currentLedStepStarted = now;
    applyLedState(steps[currentLedStep].ledOn);
  }
}

void updateStatusLed() {
  if (statusLedSuspended) {
    return;
  }
  LedPatternId desiredPattern = LED_PATTERN_WIFI_CONNECTING;
  if (WiFi.status() != WL_CONNECTED) {
    desiredPattern = LED_PATTERN_WIFI_CONNECTING;
  } else if (!isMqttConfigured()) {
    desiredPattern = LED_PATTERN_WAITING_FOR_SERVER;
  } else if (!client.connected()) {
    desiredPattern = LED_PATTERN_WAITING_FOR_MQTT;
  } else {
    desiredPattern = LED_PATTERN_ONLINE;
  }

  setBaseStatusLedPattern(desiredPattern);
  advanceStatusLed();
}

void setBaseStatusLedPattern(LedPatternId pattern) {
  if (baseLedPattern == pattern) {
    return;
  }
  baseLedPattern = pattern;
  if (!overridePatternActive) {
    setStatusLedPattern(baseLedPattern);
  }
}

void activateTemporaryLedPattern(LedPatternId pattern, unsigned long durationMs) {
  overridePatternActive = true;
  overridePatternDeadline = millis() + durationMs;
  setStatusLedPattern(pattern);
}

void triggerStateChangeBlink() {
  if (statusLedSuspended) {
    return;
  }
  activateTemporaryLedPattern(LED_PATTERN_STATE_CHANGED, LED_PATTERN_STATE_CHANGED_DURATION_MS);
}

RadiatorMode detectCurrentMode() {
  int highState = digitalRead(pinHigh);
  int lowState = digitalRead(pinLow);

  if (highState == LOW && lowState == LOW) {
    return MODE_COMFORT;
  }
  if (highState == HIGH && lowState == HIGH) {
    return MODE_ECO;
  }
  if (highState == HIGH && lowState == LOW) {
    return MODE_OFF;
  }
  if (highState == LOW && lowState == HIGH) {
    return MODE_HORSGEL;
  }
  return MODE_UNKNOWN;
}

const char* modeToCommand(RadiatorMode mode) {
  switch (mode) {
    case MODE_COMFORT:
      return "COMFORT";
    case MODE_ECO:
      return "ECO";
    case MODE_OFF:
      return "OFF";
    case MODE_HORSGEL:
      return "HORS GEL";
    default:
      return "UNKNOWN";
  }
}

void registerAppliedMode(RadiatorMode mode) {
  if (appliedMode != mode) {
    appliedMode = mode;
    triggerStateChangeBlink();
  } else {
    appliedMode = mode;
  }
}

void setup() {
  // Serial.begin(115200);
  // delay(10);

  EEPROM.begin(EEPROM_SIZE);
  credentialsLoaded = loadConfig();
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

  appliedMode = detectCurrentMode();

  setStatusLedPattern(LED_PATTERN_WIFI_CONNECTING);
  updateStatusLed();

  suspendStatusLed(true);
  clignoter(3000, 500);
  suspendStatusLed(false);
  updateStatusLed();

  WiFi.mode(WIFI_AP_STA);
  startAccessPoint();
  setupServer();

  connectToSavedWifi(true);

  configureMqttClient();
  client.setCallback(callback);
}

void loop() {
  updateStatusLed();

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
    updateStatusLed();
    return;
  }

  if (apActive) {
    stopAccessPoint();
  }

  if (isMqttConfigured()) {
    if (!client.connected()) {
      attemptMqttReconnect(false);
    }
    if (client.connected()) {
      client.loop();
    }
  }

  // Lecture de l'entrée série et publication de messages MQTT
  if (Serial.available()) {
    String input = Serial.readStringUntil('\n');
    publishMessage(input);
  }

  updateStatusLed();
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

  DynamicJsonDocument doc(256);
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

bool attemptMqttReconnect(bool forceAttempt = false) {
  if (!isMqttConfigured()) {
    return false;
  }

  unsigned long now = millis();
  if (!forceAttempt && (now - lastMqttReconnectAttempt) < MQTT_RECONNECT_INTERVAL) {
    return client.connected();
  }

  lastMqttReconnectAttempt = now;

  if (client.connected()) {
    return true;
  }

  if (client.connect(mqttClientId)) {
    client.subscribe(mqtt_topic);
    return true;
  }

  return false;
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
  server.on("/mqtt-host", HTTP_POST, handleMqttHost);
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
  page += "<p>L'adresse du serveur MQTT sera configurée automatiquement lors de la détection par le serveur Django.</p>";
  page += "<button type='submit'>Enregistrer</button></form></body></html>";
  server.send(200, "text/html", page);
}

void handleSave() {
  if (!server.hasArg("ssid") || !server.hasArg("device_name")) {
    server.send(400, "text/plain", "Paramètres manquants");
    return;
  }

  String newSsid = server.arg("ssid");
  String newPassword = server.hasArg("password") ? server.arg("password") : "";
  String newDeviceName = server.arg("device_name");

  newSsid.trim();
  newPassword.trim();
  newDeviceName.trim();

  if (newSsid.length() == 0 || newDeviceName.length() == 0) {
    server.send(400, "text/plain", "Le SSID et le nom de l'appareil sont obligatoires");
    return;
  }

  if (newDeviceName.length() >= DEVICE_NAME_MAX_LENGTH) {
    server.send(400, "text/plain", "Le nom de l'appareil est trop long");
    return;
  }

  newSsid.toCharArray(deviceConfig.ssid, sizeof(deviceConfig.ssid));
  newPassword.toCharArray(deviceConfig.password, sizeof(deviceConfig.password));
  newDeviceName.toCharArray(deviceConfig.deviceName, sizeof(deviceConfig.deviceName));
  saveConfig(deviceConfig);
  credentialsLoaded = strlen(deviceConfig.ssid) > 0;

  refreshMqttClientId();
  configureMqttClient();
  if (client.connected()) {
    client.disconnect();
  }

  bool connected = connectToSavedWifi(true);

  if (connected) {
    if (isMqttConfigured()) {
      attemptMqttReconnect(true);
    }
    server.send(200, "text/html", "<html><body><h1>Connexion réussie</h1><p>L'ESP8266 est connecté au réseau \"" + newSsid + "\".</p><p>Nom de l'appareil&nbsp;: " + newDeviceName + "</p><p>Le serveur Django configurera automatiquement le broker MQTT lors de la détection.</p></body></html>");
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
    updateStatusLed();
  }

  if (WiFi.status() == WL_CONNECTED) {
    stopAccessPoint();
    updateStatusLed();
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
  if (isMqttConfigured()) {
    doc["mqtt_server"] = deviceConfig.mqttServer;
  }

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
  configureMqttClient();

  if (client.connected()) {
    client.disconnect();
  }
  if (WiFi.status() == WL_CONNECTED && isMqttConfigured()) {
    attemptMqttReconnect(true);
  }

  updateStatusLed();

  StaticJsonDocument<96> response;
  response["status"] = "ok";
  response["name"] = deviceConfig.deviceName;
  String payload;
  serializeJson(response, payload);
  server.send(200, "application/json", payload);
}

void handleMqttHost() {
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

  const char* requestedHost = doc["host"];
  if (requestedHost == nullptr) {
    server.send(400, "application/json", "{\"error\":\"Adresse manquante\"}");
    return;
  }

  String hostValue = String(requestedHost);
  hostValue.trim();
  if (hostValue.length() == 0) {
    server.send(400, "application/json", "{\"error\":\"Adresse invalide\"}");
    return;
  }

  if (hostValue.length() >= sizeof(deviceConfig.mqttServer)) {
    server.send(400, "application/json", "{\"error\":\"Adresse trop longue\"}");
    return;
  }

  char previousHost[sizeof(deviceConfig.mqttServer)];
  strncpy(previousHost, deviceConfig.mqttServer, sizeof(previousHost));
  previousHost[sizeof(previousHost) - 1] = '\0';

  hostValue.toCharArray(deviceConfig.mqttServer, sizeof(deviceConfig.mqttServer));
  saveConfig(deviceConfig);
  configureMqttClient();

  bool hostChanged = strcmp(previousHost, deviceConfig.mqttServer) != 0;
  if (hostChanged && client.connected()) {
    client.disconnect();
  }

  StaticJsonDocument<96> response;
  response["status"] = "ok";
  response["host"] = deviceConfig.mqttServer;
  String payload;
  serializeJson(response, payload);
  server.send(200, "application/json", payload);

  if (WiFi.status() == WL_CONNECTED) {
    if (!client.connected() || hostChanged) {
      attemptMqttReconnect(true);
    }
  }

  updateStatusLed();
}

void handleNotFound() {
  if (handleCaptivePortal()) {
    return;
  }

  server.send(404, "text/plain", "Not found");
}

void clignoter(int totalDuration, int blinkSpeed) {
  suspendStatusLed(true);
  int numberOfBlinks = totalDuration / (2 * blinkSpeed);
  for (int i = 0; i < numberOfBlinks; i++) {
    digitalWrite(LED_BUILTIN, LOW);
    delay(blinkSpeed);
    digitalWrite(LED_BUILTIN, HIGH);
    delay(blinkSpeed);
  }
  suspendStatusLed(false);
  updateStatusLed();
}

void modeComfort(){
    digitalWrite(pinHigh, LOW);
    digitalWrite(pinLow, LOW);
    registerAppliedMode(MODE_COMFORT);
}

void modeEco(){
  digitalWrite(pinHigh, HIGH);
  digitalWrite(pinLow, HIGH);
  registerAppliedMode(MODE_ECO);
}

void modeHorsGel(){
  digitalWrite(pinHigh, LOW);
  digitalWrite(pinLow, HIGH);
  registerAppliedMode(MODE_HORSGEL);
}

void modeOff(){
  digitalWrite(pinHigh, HIGH);
  digitalWrite(pinLow, LOW);
  registerAppliedMode(MODE_OFF);
}

void checkEtat(){
  RadiatorMode mode = detectCurrentMode();
  const char* command = modeToCommand(mode);
  appliedMode = mode;

  DynamicJsonDocument message(256);
  message["FROM"] = mqttClientId;
  message["TO"] = "Django";
  message["COMMAND"] = command;

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

bool isMqttConfigured() {
  return deviceConfig.mqttServer[0] != '\0' && deviceConfig.mqttServer[0] != char(0xFF);
}

void configureMqttClient() {
  if (isMqttConfigured()) {
    client.setServer(deviceConfig.mqttServer, mqtt_port);
  }
  lastMqttReconnectAttempt = 0;
}

void refreshMqttClientId() {
  if (deviceConfig.deviceName[0] == '\0') {
    ensureDeviceName();
  }
  strncpy(mqttClientId, deviceConfig.deviceName, sizeof(mqttClientId) - 1);
  mqttClientId[sizeof(mqttClientId) - 1] = '\0';
}










