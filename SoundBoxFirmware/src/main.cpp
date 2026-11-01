// SoundBoxRadio: ESP32 -> PCM5102A -> PAM8403. No external Arduino libraries.
#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <driver/i2s.h>
#include <freertos/queue.h>

constexpr int PIN_LRCK = 25, PIN_DIN = 26, PIN_BCK = 27;
constexpr int PIN_BUTTON = 13, PIN_LED = 14;
constexpr uint32_t SAMPLE_RATE = 48000;
constexpr size_t FRAME_SAMPLES = 960;
constexpr size_t FRAME_BYTES = FRAME_SAMPLES * 4;
constexpr size_t QUEUE_FRAMES = 21, PREBUFFER_FRAMES = 12; // 120 ms startup reserve
// PCM5102A full scale is 2.1 Vrms. PAM8403 gain is 24 dB.
// -22 dB on this receiver prevents gross analogue input overload at 5 V.
constexpr int DAC_GAIN_Q15 = 2621; // 0.08, applied after mono downmix

struct PcmFrame { int16_t sample[FRAME_SAMPLES * 2]; };
Preferences preferences;
WebServer web(80);
DNSServer dns;
QueueHandle_t audioQueue = nullptr;
String ssid, password, serverHost;
uint16_t serverPort = 5000;
bool configMode = false, retryWiFi = false;
volatile bool streamConnected = false, playing = false, muted = false;
volatile uint32_t reconnects = 0, underruns = 0;
volatile uint8_t receiverVolume = 100;
portMUX_TYPE errorMux = portMUX_INITIALIZER_UNLOCKED;
char errorText[120] = "Waiting for server";

void setError(const char* message) {
  portENTER_CRITICAL(&errorMux);
  strlcpy(errorText, message, sizeof(errorText));
  portEXIT_CRITICAL(&errorMux);
}

String escaped(String value) {
  value.replace("&", "&amp;"); value.replace("<", "&lt;");
  value.replace("\"", "&quot;"); value.replace("'", "&#39;");
  return value;
}

String page() {
  String html = R"HTML(<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SoundBoxRadio</title>
<style>body{font:16px system-ui;background:#101923;color:#e3edf3;margin:0;padding:24px}main{max-width:540px;margin:auto}section{background:#1a2a39;border:1px solid #334c60;border-radius:16px;padding:22px;margin:18px 0}h1{margin-bottom:4px}p,small{color:#adc2d1}label{display:block;margin:15px 0 5px}input,button{box-sizing:border-box;width:100%;padding:12px;border-radius:8px;border:1px solid #526a7c;background:#101923;color:inherit}button{background:#62dec5;color:#10232a;font-weight:700;cursor:pointer;margin-top:16px}a{color:#62dec5}#state{white-space:pre-line}input[type=range]{padding:0}</style>
<main><h1>SoundBoxRadio</h1><p>ESP32 · PCM5102A · PAM8403</p><section><strong>Состояние приёмника</strong><p id="state">Подключение…</p>
<button onclick="fetch('/mute',{method:'POST'}).then(refresh)">Включить / отключить звук</button>
<label>Громкость приёмника <output id="level">100</output>%</label><input type="range" min="0" max="100" value="100" oninput="level.value=this.value" onchange="fetch('/volume?value='+this.value,{method:'POST'})"></section>
<section><h2>Подключение</h2><form action="/save" method="post"><label>Сеть Wi-Fi</label><input name="ssid" required maxlength="63" value=")HTML";
  html += escaped(ssid);
  html += R"HTML("><label>Пароль Wi-Fi (пусто — оставить прежний)</label><input name="password" type="password" maxlength="63"><label>IPv4 компьютера с сервером</label><input name="host" required placeholder="192.168.1.100" value=")HTML";
  html += escaped(serverHost);
  html += "\"><label>Порт</label><input name=\"port\" type=\"number\" min=\"1\" max=\"65535\" value=\"" + String(serverPort);
  html += R"HTML("><button>Сохранить и перезапустить</button></form></section>
<small>GPIO13: нажатие — тишина, удержание 3 секунды — настройка Wi-Fi.<br>GPIO14: горит — звук, мигает — ожидание.</small></main>
<script>async function refresh(){try{let s=await(await fetch('/api/status')).json();document.getElementById('state').textContent=(s.connected?'Сервер подключён':'Нет потока')+' · '+(s.muted?'Звук отключён':s.playing?'Воспроизведение':'Буферизация')+'\nБуфер: '+s.buffer_ms+' мс · Переподключения: '+s.reconnects+' · Паузы сети: '+s.underruns+'\n'+s.error;}catch{}}refresh();setInterval(refresh,2000)</script></html>)HTML";
  return html;
}

void startWeb() {
  web.on("/", HTTP_GET, [] { web.send(200, "text/html; charset=utf-8", page()); });
  web.on("/save", HTTP_POST, [] {
    String newSsid = web.arg("ssid"), host = web.arg("host");
    long port = web.arg("port").toInt();
    IPAddress ip;
    if (newSsid.isEmpty() || newSsid.length() > 63 || !ip.fromString(host) || port < 1 || port > 65535) {
      web.send(400, "text/plain; charset=utf-8", "Проверьте имя Wi-Fi, IPv4 сервера и порт."); return;
    }
    preferences.begin("radio", false);
    preferences.putString("ssid", newSsid);
    if (!web.arg("password").isEmpty() || newSsid != ssid)
      preferences.putString("password", web.arg("password"));
    preferences.putString("serverIP", host);
    preferences.putInt("port", port);
    preferences.putBool("configured", true);
    preferences.putBool("forceAP", false);
    preferences.end();
    web.send(200, "text/html; charset=utf-8", "Настройки сохранены. Приёмник перезапускается.");
    delay(300); ESP.restart();
  });
  web.on("/api/status", HTTP_GET, [] {
    char error[120];
    portENTER_CRITICAL(&errorMux);
    strlcpy(error, errorText, sizeof(error));
    portEXIT_CRITICAL(&errorMux);
    // All error messages below are fixed strings with no JSON control characters.
    String json = "{\"connected\":" + String(streamConnected ? "true" : "false");
    json += ",\"playing\":" + String(playing ? "true" : "false");
    json += ",\"muted\":" + String(muted ? "true" : "false");
    json += ",\"volume\":" + String(receiverVolume);
    json += ",\"buffer_ms\":" + String(audioQueue ? uxQueueMessagesWaiting(audioQueue) * 20 : 0);
    json += ",\"reconnects\":" + String(reconnects) + ",\"underruns\":" + String(underruns);
    json += ",\"error\":\"" + String(error) + "\"}";
    web.send(200, "application/json", json);
  });
  web.on("/mute", HTTP_POST, [] { muted = !muted; web.send(200, "text/plain", "OK"); });
  web.on("/volume", HTTP_POST, [] {
    int level = web.arg("value").toInt();
    if (level < 0 || level > 100) { web.send(400, "text/plain", "0..100"); return; }
    receiverVolume = level; web.send(200, "text/plain", "OK");
  });
  web.onNotFound([] { web.sendHeader("Location", "/"); web.send(302, "text/plain", ""); });
  web.begin();
}

bool setupI2S() {
  i2s_config_t settings = {};
  settings.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX);
  settings.sample_rate = SAMPLE_RATE;
  settings.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  settings.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;
  settings.communication_format = I2S_COMM_FORMAT_STAND_I2S; // FMT=GND on PCM5102A
  settings.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  settings.dma_buf_count = 6;
  settings.dma_buf_len = 240;
  settings.use_apll = true;
  settings.tx_desc_auto_clear = true;
  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = PIN_BCK; pins.ws_io_num = PIN_LRCK;
  pins.data_out_num = PIN_DIN; pins.data_in_num = I2S_PIN_NO_CHANGE;
  esp_err_t result = i2s_driver_install(I2S_NUM_0, &settings, 0, nullptr);
  if (result == ESP_OK) result = i2s_set_pin(I2S_NUM_0, &pins);
  if (result != ESP_OK) { Serial.printf("I2S error %d\n", result); return false; }
  i2s_zero_dma_buffer(I2S_NUM_0);
  return true;
}

void writeFrame(PcmFrame& frame) {
  size_t offset = 0;
  while (offset < FRAME_BYTES) {
    size_t written = 0;
    if (i2s_write(I2S_NUM_0, (uint8_t*)frame.sample + offset, FRAME_BYTES - offset,
                  &written, pdMS_TO_TICKS(100)) != ESP_OK || !written) {
      setError("I2S write failed"); break;
    }
    offset += written;
  }
}

void audioTask(void*) {
  PcmFrame frame = {};
  bool buffered = false;
  int16_t lastOutput = 0;
  for (;;) {
    if (!streamConnected) buffered = false;
    if (!buffered && streamConnected && uxQueueMessagesWaiting(audioQueue) >= PREBUFFER_FRAMES)
      buffered = true;
    bool haveAudio = buffered && xQueueReceive(audioQueue, &frame, 0) == pdTRUE;
    if (!haveAudio) {
      if (buffered) { ++underruns; buffered = false; }
      memset(&frame, 0, sizeof(frame));
      // A short fade avoids a step at the boundary of a network interruption.
      for (int i = 0; i < 64; ++i)
        frame.sample[2 * i] = frame.sample[2 * i + 1] = lastOutput * (63 - i) / 64;
      lastOutput = 0;
    } else {
      const int gain = muted ? 0 : DAC_GAIN_Q15 * receiverVolume / 100;
      for (size_t i = 0; i < FRAME_SAMPLES; ++i) {
        int32_t mono = ((int32_t)frame.sample[2*i] + frame.sample[2*i+1]) / 2;
        int16_t output = mono * gain / 32768;
        // This installation has one speaker: put the complete mono mix on L and R.
        frame.sample[2*i] = frame.sample[2*i+1] = output;
      }
      lastOutput = frame.sample[FRAME_SAMPLES * 2 - 1];
    }
    playing = haveAudio && !muted;
    writeFrame(frame); // DMA clocks the entire receiver, not the network task.
  }
}

bool openStream(WiFiClient& client) {
  IPAddress ip;
  if (!ip.fromString(serverHost) || !client.connect(ip, serverPort, 3000)) {
    setError("Server connection failed"); return false;
  }
  client.setNoDelay(true);
  client.setTimeout(2000);
  // HTTP/1.0 deliberately requests a raw close-delimited body. No chunk parser.
  client.print("GET /api/radio/stream HTTP/1.0\r\nHost: " + serverHost +
               "\r\nConnection: close\r\nAccept: application/octet-stream\r\n\r\n");
  String status = client.readStringUntil('\n');
  if (!status.startsWith("HTTP/1.0 200") && !status.startsWith("HTTP/1.1 200")) {
    setError("Server returned an HTTP error"); return false;
  }
  bool validRate = false, validBits = false, validChannels = false, validFormat = false;
  size_t headerBytes = status.length();
  uint32_t started = millis();
  for (;;) {
    String line = client.readStringUntil('\n'); line.trim();
    headerBytes += line.length();
    if (headerBytes > 8192 || millis() - started > 5000) {
      setError("Invalid HTTP headers"); return false;
    }
    if (line.isEmpty()) break;
    line.toLowerCase();
    if (line.startsWith("transfer-encoding:")) {
      setError("Chunked response is unsupported; update server"); return false;
    }
    if (line == "x-audio-rate: 48000") validRate = true;
    if (line == "x-audio-channels: 2") validChannels = true;
    if (line == "x-audio-bits: 16") validBits = true;
    if (line == "x-audio-format: s16le") validFormat = true;
  }
  if (!(validRate && validBits && validChannels && validFormat)) {
    setError("PCM format mismatch; update server and firmware"); return false;
  }
  return true;
}

void networkTask(void*) {
  PcmFrame frame;
  bool connectedBefore = false;
  for (;;) {
    if (WiFi.status() != WL_CONNECTED) {
      streamConnected = false;
      setError("Wi-Fi disconnected"); WiFi.reconnect();
      vTaskDelay(pdMS_TO_TICKS(2000)); continue;
    }
    WiFiClient client;
    if (!openStream(client)) { client.stop(); vTaskDelay(pdMS_TO_TICKS(1000)); continue; }
    xQueueReset(audioQueue);
    streamConnected = true;
    if (connectedBefore) ++reconnects;
    connectedBefore = true;
    setError("");
    size_t received = 0;
    uint32_t lastData = millis();
    while (WiFi.status() == WL_CONNECTED && (client.connected() || client.available())) {
      int available = client.available();
      if (!available) {
        if (millis() - lastData > 3000) { setError("Stream timeout"); break; }
        vTaskDelay(pdMS_TO_TICKS(1)); continue;
      }
      size_t amount = min((size_t)available, FRAME_BYTES - received);
      int count = client.read((uint8_t*)frame.sample + received, amount);
      if (count <= 0) continue;
      received += count; lastData = millis();
      if (received == FRAME_BYTES) {
        // TCP and a bounded frame queue provide backpressure. Never drop sample bytes.
        if (xQueueSend(audioQueue, &frame, pdMS_TO_TICKS(1000)) != pdTRUE) {
          setError("Audio consumer stalled"); break;
        }
        received = 0;
      }
    }
    streamConnected = false;
    client.stop();
    xQueueReset(audioQueue);
    vTaskDelay(pdMS_TO_TICKS(250));
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUTTON, INPUT_PULLUP); pinMode(PIN_LED, OUTPUT);
  preferences.begin("radio", false);
  ssid = preferences.getString("ssid", "");
  password = preferences.getString("password", "");
  serverHost = preferences.getString("serverIP", "");
  serverPort = preferences.getInt("port", 5000);
  bool forceAP = preferences.getBool("forceAP", false);
  preferences.putBool("forceAP", false);
  bool configured = preferences.getBool("configured", false);
  preferences.end();
  bool automaticConnection = configured && !forceAP && digitalRead(PIN_BUTTON) != LOW;
  if (automaticConnection) {
    WiFi.mode(WIFI_STA); WiFi.setSleep(false); WiFi.setAutoReconnect(true);
    WiFi.begin(ssid.c_str(), password.c_str());
    uint32_t began = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - began < 20000) {
      digitalWrite(PIN_LED, (millis()/250)%2); delay(50);
    }
  }
  configMode = WiFi.status() != WL_CONNECTED;
  if (configMode) {
    retryWiFi = automaticConnection;
    WiFi.mode(retryWiFi ? WIFI_AP_STA : WIFI_AP);
    if (retryWiFi) {
      WiFi.setSleep(false); WiFi.setAutoReconnect(true);
      WiFi.begin(ssid.c_str(), password.c_str());
    }
    WiFi.softAP("SoundBoxRadio-Setup");
    dns.start(53, "*", WiFi.softAPIP());
    setError("Setup Wi-Fi and server IP at 192.168.4.1");
    Serial.println("Setup: SoundBoxRadio-Setup / http://192.168.4.1");
  } else {
    Serial.println("Receiver: http://" + WiFi.localIP().toString());
    audioQueue = xQueueCreate(QUEUE_FRAMES, sizeof(PcmFrame));
    if (!audioQueue || !setupI2S()) { setError("Audio initialization failed"); }
    else {
      BaseType_t audioCreated = xTaskCreatePinnedToCore(audioTask, "i2s-output", 6144, nullptr, 4, nullptr, 1);
      if (audioCreated != pdPASS) setError("Cannot allocate audio task");
      else if (xTaskCreatePinnedToCore(networkTask, "pcm-network", 8192, nullptr, 2, nullptr, 0) != pdPASS)
        setError("Cannot allocate network task");
    }
  }
  startWeb();
}

void loop() {
  web.handleClient();
  if (configMode) dns.processNextRequest();
  if (retryWiFi) {
    // Recover after a router power failure, including when it was off at boot.
    if (WiFi.status() == WL_CONNECTED) ESP.restart();
    static uint32_t lastRetry = 0;
    if (millis() - lastRetry > 10000) { lastRetry = millis(); WiFi.reconnect(); }
  }
  static bool previous = HIGH, stable = HIGH, longPress = false;
  static uint32_t changed = 0, pressed = 0;
  bool current = digitalRead(PIN_BUTTON);
  if (current != previous) { changed = millis(); previous = current; }
  if (millis() - changed > 30 && current != stable) {
    stable = current;
    if (stable == LOW) { pressed = millis(); longPress = false; }
    else if (!longPress) muted = !muted;
  }
  if (stable == LOW && !longPress && millis() - pressed >= 3000) {
    longPress = true;
    preferences.begin("radio", false); preferences.putBool("forceAP", true); preferences.end();
    ESP.restart();
  }
  digitalWrite(PIN_LED, configMode || !streamConnected ? (millis()/500)%2 : playing);
  delay(3);
}
