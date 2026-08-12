/*
  esp8266_scale.ino — production
  อ่านน้ำหนักจาก HX711 ส่งทาง Serial (USB → Pi)
  เปิด USE_WIFI เพื่อสลับไปใช้ UDP บน WiFi

  Wiring (NodeMCU):
    HX711 DT  → D5 (GPIO14)
    HX711 SCK → D6 (GPIO12)
    HX711 VCC → Vin (5V)
    HX711 GND → GND
*/

#include <HX711.h>

#define USE_WIFI

#ifdef USE_WIFI
  #include <ESP8266WiFi.h>
  #include <WiFiUdp.h>
  const char* SSID     = "vivo Y03";
  const char* PASSWORD = "0658635990";
  const int   UDP_PORT = 5005;
  WiFiUDP udp;
#endif

const int DOUT_PIN = 14;  // D5
const int SCK_PIN  = 12;  // D6

// Calibration — ปรับโดยชั่งของที่รู้น้ำหนักแน่นอน หาค่า (raw - tare) / น้ำหนักจริง
float CALIBRATION_FACTOR = 457.4;

HX711 scale;
unsigned long lastSend = 0;
const int SEND_INTERVAL_MS = 100;   // 10Hz

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("scale: init HX711...");

  scale.begin(DOUT_PIN, SCK_PIN);
  scale.set_scale(CALIBRATION_FACTOR);

  Serial.println("scale: tare...");
  scale.tare(10);
  Serial.println("scale: ready");

#ifdef USE_WIFI
  WiFi.begin(SSID, PASSWORD);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.print("\nWiFi IP: ");
  Serial.println(WiFi.localIP());
  udp.begin(UDP_PORT);
#endif
}

void loop() {
  if (millis() - lastSend < SEND_INTERVAL_MS) return;
  lastSend = millis();
  if (!scale.is_ready()) return;

  float grams = scale.get_units(3);
  if (grams < 0) grams = 0;

  char buf[16];
  dtostrf(grams, 6, 1, buf);
  char* p = buf;
  while (*p == ' ') p++;

#ifdef USE_WIFI
  // broadcast — ส่งหาทุกเครื่องใน subnet ไม่ต้องรู้ IP ของ Pi
  IPAddress bcast(255, 255, 255, 255);
  udp.beginPacket(bcast, UDP_PORT);
  udp.print(p); udp.print("\n");
  udp.endPacket();
#else
  Serial.println(p);
#endif
}
