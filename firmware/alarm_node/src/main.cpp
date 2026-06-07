// AutoSentry alarm node firmware (ESP32-S3 + SX1262).
//
// Role: sit quietly on battery+mains, listen for a *signed* ALARM broadcast from the hub
// over LoRa, and on a verified ALARM sound the local siren/strobe. Reports health back via
// ACK + periodic heartbeat, and reports mains-loss. A node that loses the hub's heartbeats
// fails *safe* (alerts), never silent (FR-7..10, SR-1/2, FMEA F9/F11).
//
// The wire format and HMAC scheme here MUST stay byte-for-byte identical to the hub codec
// in hub/autosentry/comms/protocol.py (ICD-3). The Python unit tests are the golden vectors.
//
// STATUS: M3 skeleton — protocol constants + parse/verify + siren GPIO + heartbeat timer.
// Radio TX/RX glue and INA219 mains-sense land as M3/M4 fill in the marked TODOs.

#include <Arduino.h>
#include <RadioLib.h>
#include "mbedtls/md.h"

// --- Wire protocol (mirror of protocol.py) ------------------------------------------
// layout: ver(1) type(1) net_id(1) src(1) dst(1) counter(4 LE) payload(n) hmac(8)
static const uint8_t  WIRE_VERSION = PROTO_VERSION;
static const size_t   WIRE_HEADER_LEN = HEADER_LEN;   // 9
static const size_t   WIRE_HMAC_LEN = HMAC_LEN;       // 8 (SHA256 truncated)

enum MsgType : uint8_t {
  MSG_ALARM = 1,
  MSG_ACK = 2,
  MSG_HEARTBEAT = 3,
  MSG_HEARTBEAT_ACK = 4,
  MSG_STATUS = 5,
  MSG_CONFIG = 6,
  MSG_TEST = 7,
};

// --- Node identity / config (provisioned, see docs/SECURITY.md SR-3) ----------------
static const uint8_t NET_ID = 1;
static const uint8_t NODE_ADDR = 1;     // unique per node; set at provisioning
static const uint8_t HUB_ADDR = 0;
static const uint8_t FW_VER = 1;        // reported in STATUS (payloads.StatusPayload.fw_ver)
static const uint8_t CFG_CLEAR = 0x00;  // CONFIG sub-command: silence siren after owner ack

// Pre-shared HMAC key. Injected at provisioning/flash time via a build flag
// (-DAUTOSENTRY_MESH_KEY="..."), never committed (SR-3). The placeholder fallback only lets
// the firmware build for bring-up; the node REFUSES to operate on it (see setup()) so a node
// with no real key fails loudly instead of silently authenticating with a public placeholder.
// Production should provision into NVS/efuse rather than a build flag (see test/README.md).
#ifndef AUTOSENTRY_MESH_KEY
#define AUTOSENTRY_MESH_KEY "REPLACE_AT_PROVISIONING"
#endif
static const uint8_t MESH_KEY[] = AUTOSENTRY_MESH_KEY;
static const size_t  MESH_KEY_LEN = sizeof(MESH_KEY) - 1;

static bool mesh_key_is_placeholder() {
  static const char kPlaceholder[] = "REPLACE_AT_PROVISIONING";
  return sizeof(MESH_KEY) == sizeof(kPlaceholder) &&
         memcmp(MESH_KEY, kPlaceholder, sizeof(MESH_KEY)) == 0;
}

static const uint32_t HEARTBEAT_INTERVAL_MS = 5000;   // matches comms.hb_interval_s
static const uint32_t HUB_TIMEOUT_MS = 20000;         // ~ hb_miss_max * interval -> fail-safe

// --- Radio + state ------------------------------------------------------------------
SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
static uint32_t g_tx_counter = 0;        // our monotonic counter (anti-replay, SR-1)
static uint32_t g_last_hub_rx_ms = 0;    // last time we heard the hub (fail-safe timer)
static uint32_t g_last_hb_ms = 0;
static bool     g_siren_on = false;

// --- HMAC-SHA256 truncated to WIRE_HMAC_LEN (mbedTLS) --------------------------------
static void hmac8(const uint8_t* data, size_t len, uint8_t out[WIRE_HMAC_LEN]) {
  uint8_t full[32];
  const mbedtls_md_info_t* info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  mbedtls_md_hmac(info, MESH_KEY, MESH_KEY_LEN, data, len, full);
  memcpy(out, full, WIRE_HMAC_LEN);
}

// Constant-time compare so a forged tag can't be timed out (SR-1).
static bool tag_equal(const uint8_t* a, const uint8_t* b, size_t n) {
  uint8_t diff = 0;
  for (size_t i = 0; i < n; i++) diff |= (uint8_t)(a[i] ^ b[i]);
  return diff == 0;
}

// --- Anti-replay: per-source last-counter table (mirror of protocol.py ReplayWindow) -
// Reject any counter <= the last accepted one for that source (SR-1). Broadcast ALARM
// repeats share one counter, so they de-dupe here and the siren sounds exactly once.
struct LastSeen { uint8_t src; uint32_t counter; bool used; };
static LastSeen g_seen[8];

static bool replay_ok(uint8_t src, uint32_t counter) {
  int free_idx = -1;
  for (int i = 0; i < 8; i++) {
    if (g_seen[i].used && g_seen[i].src == src) {
      if (counter <= g_seen[i].counter) return false;  // replay/duplicate -> drop
      g_seen[i].counter = counter;
      return true;
    }
    if (!g_seen[i].used && free_idx < 0) free_idx = i;
  }
  if (free_idx >= 0) { g_seen[free_idx].src = src; g_seen[free_idx].counter = counter;
                       g_seen[free_idx].used = true; }
  return true;  // first frame heard from this source
}

// Verify + parse a received frame. Returns true and fills fields on success.
static bool decode_frame(const uint8_t* raw, size_t n,
                         uint8_t& type, uint8_t& src, uint8_t& dst, uint32_t& counter,
                         const uint8_t*& payload, size_t& payload_len) {
  if (n < WIRE_HEADER_LEN + WIRE_HMAC_LEN) return false;
  size_t body_len = n - WIRE_HMAC_LEN;
  uint8_t tag[WIRE_HMAC_LEN];
  hmac8(raw, body_len, tag);
  if (!tag_equal(tag, raw + body_len, WIRE_HMAC_LEN)) return false;  // forged/corrupt -> drop
  if (raw[0] != WIRE_VERSION) return false;
  type = raw[1];
  // raw[2] = net_id
  src  = raw[3];
  dst  = raw[4];
  counter = (uint32_t)raw[5] | ((uint32_t)raw[6] << 8) |
            ((uint32_t)raw[7] << 16) | ((uint32_t)raw[8] << 24);  // little-endian
  payload = raw + WIRE_HEADER_LEN;
  payload_len = body_len - WIRE_HEADER_LEN;
  return raw[2] == NET_ID;
}

// Build + sign a frame into buf; returns total length.
static size_t encode_frame(uint8_t* buf, uint8_t type, uint8_t dst,
                           const uint8_t* payload, size_t payload_len) {
  uint32_t c = ++g_tx_counter;
  buf[0] = WIRE_VERSION;
  buf[1] = type;
  buf[2] = NET_ID;
  buf[3] = NODE_ADDR;
  buf[4] = dst;
  buf[5] = (uint8_t)(c & 0xFF);
  buf[6] = (uint8_t)((c >> 8) & 0xFF);
  buf[7] = (uint8_t)((c >> 16) & 0xFF);
  buf[8] = (uint8_t)((c >> 24) & 0xFF);
  if (payload_len) memcpy(buf + WIRE_HEADER_LEN, payload, payload_len);
  size_t body_len = WIRE_HEADER_LEN + payload_len;
  hmac8(buf, body_len, buf + body_len);
  return body_len + WIRE_HMAC_LEN;
}

// --- Outputs ------------------------------------------------------------------------
static void set_siren(bool on) {
  g_siren_on = on;
  digitalWrite(PIN_SIREN, on ? HIGH : LOW);
  digitalWrite(PIN_STROBE, on ? HIGH : LOW);
}

static void send_frame(uint8_t type, uint8_t dst, const uint8_t* payload, size_t len) {
  uint8_t buf[64];
  size_t total = encode_frame(buf, type, dst, payload, len);
  radio.transmit(buf, total);   // TODO(M3): handle TX errors
  // transmit() leaves the SX1262 in TX/standby — go back to RX immediately so the node is
  // never deaf to a follow-up ALARM, CONFIG-clear, or hub heartbeat between heartbeats (C2).
  radio.startReceive();
}

// ACK / HEARTBEAT_ACK must echo the acknowledged frame's counter as a 4-byte LE payload, so
// the hub's _observe() (which checks len(payload) >= 4 and decode_ref()) can match it to the
// command it sent (ICD-3, FR-8). An empty ACK is silently dropped hub-side.
static void send_ack(uint8_t type, uint32_t ref_counter) {
  uint8_t ref[4] = {
    (uint8_t)(ref_counter & 0xFF), (uint8_t)((ref_counter >> 8) & 0xFF),
    (uint8_t)((ref_counter >> 16) & 0xFF), (uint8_t)((ref_counter >> 24) & 0xFF),
  };
  send_frame(type, HUB_ADDR, ref, sizeof(ref));
}

static bool mains_present() {
  // TODO(M4): read INA219 / mains-sense GPIO; HIGH = mains present.
  return digitalRead(PIN_MAINS_SENSE) == HIGH;
}

// --- Inbound handling ---------------------------------------------------------------
static void handle_frame(const uint8_t* raw, size_t n) {
  uint8_t type, src, dst; uint32_t counter;
  const uint8_t* payload; size_t payload_len;
  if (!decode_frame(raw, n, type, src, dst, counter, payload, payload_len)) return;  // drop
  if (!replay_ok(src, counter)) return;  // replayed/duplicate frame -> drop (SR-1)
  // Only a fresh, authenticated hub frame proves the hub is alive — a replayed one must
  // not reset the fail-safe timer (else an attacker could mask a real outage, SR-2).
  if (src == HUB_ADDR) g_last_hub_rx_ms = millis();

  const bool for_us = (dst == NODE_ADDR || dst == BROADCAST_ADDR);
  if (!for_us) return;

  switch (type) {
    case MSG_ALARM:
      set_siren(true);
      send_ack(MSG_ACK, counter);   // confirm receipt, echoing the hub's counter (FR-8)
      break;
    case MSG_TEST:
      send_ack(MSG_ACK, counter);
      break;
    case MSG_HEARTBEAT:
      send_ack(MSG_HEARTBEAT_ACK, counter);
      break;
    case MSG_CONFIG:
      if (payload_len >= 1 && payload[0] == CFG_CLEAR) set_siren(false);  // owner-ack silence
      send_ack(MSG_ACK, counter);
      break;
    default:
      break;
  }
}

// --- Arduino entry points -----------------------------------------------------------
void setup() {
  Serial.begin(115200);
  pinMode(PIN_SIREN, OUTPUT);
  pinMode(PIN_STROBE, OUTPUT);
  pinMode(PIN_MAINS_SENSE, INPUT_PULLUP);
  set_siren(false);

  // SR-3 / pillar 5: a node flashed without a real mesh key must not run — otherwise it
  // would HMAC every frame with a publicly-known placeholder, defeating authentication.
  // Fail loud (blink the strobe + log), never silently "work".
  if (mesh_key_is_placeholder()) {
    while (true) {
      Serial.println("FATAL: mesh key not provisioned (placeholder). Reflash with "
                     "-DAUTOSENTRY_MESH_KEY; refusing to operate (SR-3).");
      digitalWrite(PIN_STROBE, HIGH); delay(250);
      digitalWrite(PIN_STROBE, LOW);  delay(250);
    }
  }

  int st = radio.begin(915.0);   // TODO: region band from provisioning (915 US / 868 EU)
  if (st != RADIOLIB_ERR_NONE) {
    Serial.printf("LoRa init failed: %d\n", st);
  }
  radio.startReceive();
  g_last_hub_rx_ms = millis();
}

void loop() {
  uint8_t buf[64];
  int len = radio.readData(buf, sizeof(buf));
  if (len > 0) handle_frame(buf, (size_t)len);

  const uint32_t now = millis();

  // Periodic liveness (FR-9) + health (FR-8/10). HEARTBEAT carries uptime_s and STATUS
  // carries battery/mains — both layouts mirror payloads.py byte-for-byte (ICD-3 §4).
  if (now - g_last_hb_ms >= HEARTBEAT_INTERVAL_MS) {
    g_last_hb_ms = now;
    const uint32_t uptime_s = now / 1000;
    uint8_t hb[4] = {(uint8_t)(uptime_s & 0xFF), (uint8_t)((uptime_s >> 8) & 0xFF),
                     (uint8_t)((uptime_s >> 16) & 0xFF), (uint8_t)((uptime_s >> 24) & 0xFF)};
    send_frame(MSG_HEARTBEAT, HUB_ADDR, hb, sizeof(hb));

    const uint16_t battery_mv = 0;  // TODO(M4): read INA219
    uint8_t status[5] = {(uint8_t)(battery_mv & 0xFF), (uint8_t)((battery_mv >> 8) & 0xFF),
                         (uint8_t)(mains_present() ? 0 : 1),  // on_battery (FR-10)
                         (uint8_t)(g_siren_on ? 1 : 0), FW_VER};
    send_frame(MSG_STATUS, HUB_ADDR, status, sizeof(status));
    radio.startReceive();
  }

  // Fail-safe: lost the hub for too long -> assume tamper/jam, sound the alarm (SR-2, OS-6).
  if (now - g_last_hub_rx_ms >= HUB_TIMEOUT_MS && !g_siren_on) {
    set_siren(true);
  }
}
