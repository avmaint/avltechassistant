# CueCommander Requirements

Requirements for the Node-RED application (CueCommander, `http://uacts-g001:1880`)
to support the UAC Tech Assistant operational dashboard and other integrations.

---

## Existing APIs

### `GET /api/videohub/crosspoints`
Returns the current cross-point state of the BMD VideoHub 40x40 (`2507-0700`).

**Current response shape:**
```json
{ "crosspoints": [ { "input": 1, "output": 1 }, ... ] }
```

**Known issue:** Responses appear to be stale — the flow is not fetching fresh
data from the VideoHub on each request. See REQ-CC-001.

---

## Requirements

### REQ-CC-001 — VideoHub crosspoint API must return live data on every request
**Priority:** High  
**Context:** The dashboard route-comparison feature calls `/api/videohub/crosspoints`
on a 30-second poll. The current implementation appears to return cached state
that does not reflect recent routing changes made via panel or third-party control.

**Requirement:** The Node-RED flow must query the VideoHub (via its TCP control
protocol on port 9990) on each incoming HTTP request, or maintain a live
subscription to VideoHub routing changes and update the response payload
immediately on any change.

**Preferred approach:** Subscribe to the VideoHub TCP control protocol and
maintain a live in-memory state within Node-RED, so HTTP requests are served
from always-current in-memory state rather than triggering a synchronous fetch
per request. This avoids per-request latency while keeping data fresh.

---

### REQ-CC-002 — Dante Audio cross-point API
**Priority:** Medium  
**Context:** Dante audio routing is a distributed network mechanism — there is
no single hardware device managing all routes. The dashboard will show a
"Dante Audio" virtual section that compares defined Dante routes (from the
cables table) against the live Dante network state.

**Requirement:** Expose a REST endpoint that returns all active Dante
transmitter→receiver subscriptions across the network.

**Proposed endpoint:** `GET /api/dante/subscriptions`

**Proposed response shape:**
```json
{
  "subscriptions": [
    {
      "receiver_device": "ZVKU-A001",
      "receiver_channel": "In 1",
      "transmitter_device": "ZVAU-M001",
      "transmitter_channel": "Out 1"
    }
  ]
}
```

**Notes:**
- Dante Controller exposes a command-line API (`DanteController --list-subscriptions`)
  or can be queried via the Audinate Dante API SDK.
- Node-RED can shell out to the CLI or use a Node-RED Dante community node.
- Receiver and transmitter device names must match the asset tags or a stable
  alias used in the cables table — coordinate naming convention.

---

### REQ-CC-003 — Device online/offline status API
**Priority:** Medium  
**Context:** The dashboard will flag in-service assets that are unreachable on
the network.

**Requirement:** Expose a REST endpoint returning the online/offline status of
all managed devices.

**Proposed endpoint:** `GET /api/devices/status`

**Proposed response shape:**
```json
{
  "devices": [
    {
      "asset_tag": "ZVKU-A001",
      "online": true,
      "last_seen": "2026-04-18T14:32:00Z"
    }
  ]
}
```

**Notes:**
- Polling method: ICMP ping or TCP port probe is acceptable.
- Poll interval: 30 seconds is sufficient given dashboard latency tolerance.
- Only network-manageable devices need to be included; determine scope from
  asset data (e.g., assets with an IP address field, or a curated device list
  maintained in CueCommander).

---

### REQ-CC-004 — Wireless microphone battery level API
**Priority:** Medium  
**Context:** The dashboard will display per-channel battery levels and alert on
low/critical battery for wireless microphones.

**Requirement:** Expose a REST endpoint returning battery status for all active
wireless microphone channels.

**Proposed endpoint:** `GET /api/wireless/battery`

**Proposed response shape:**
```json
{
  "channels": [
    {
      "asset_tag": "ZVKU-W001",
      "receiver_tag": "ZVKU-R001",
      "channel": 1,
      "battery_pct": 85,
      "estimated_mins": 240,
      "status": "ok"
    }
  ]
}
```

**Status values:** `ok` | `warning` (< 30%) | `critical` (< 10%) | `unknown`

**Notes:**
- Wireless hardware and protocol TBD — confirm receiver make/model so the
  appropriate Node-RED node or HTTP integration can be selected.

---

### REQ-CC-005 — Network ping sweep API
**Priority:** High  
**Context:** The operational dashboard network panel needs to display ping
reachability for all assets where `Monitor=Yes` in `network.xlsx`.
The FastAPI backend proxies results from CueCommander to avoid blocking the
dashboard on 28 simultaneous pings at request time.

**Requirement:** Implement a background ping sweep that runs every 30 seconds
and caches the most recent results. Expose those results via a REST endpoint.

**Proposed endpoint:** `GET /api/network/status`

**Proposed response shape:**
```json
{
  "generated_at": "2026-04-18T14:32:00Z",
  "results": [
    {
      "asset_tag": "ZVKU-A001",
      "nic": "",
      "ip": "192.168.1.10",
      "packets_sent": 3,
      "packets_received": 3,
      "avg_ms": 1.2,
      "loss_pct": 0,
      "status": "ok"
    }
  ]
}
```

**Status values:** `ok` | `high_latency` (avg > 50 ms) | `down` (packet loss > 0) | `unknown`

**Implementation notes:**
- Platform is macOS — use `ping -c 3 -t 5 <ip>` (-t = timeout in seconds)
- Ping in parallel (Function node spawning N exec nodes, or a loop with parallel
  inject) so the 28-target sweep completes in ~5s
- Store results in `flow.set('network_ping_results', ...)` and `flow.set('network_ping_generated_at', ...)`
- HTTP GET handler reads from flow context and returns immediately
- Targets are the `Monitor=Yes` rows from `network.xlsx` that have a non-empty IP

---

### REQ-CC-006 — CueCommander test suite
**Priority:** Medium  
**Context:** CueCommander (Node-RED) has no automated tests. Changes to flows
risk silent regressions.

**Requirement:** Implement a test suite for CueCommander API endpoints.

**Minimum test coverage:**
- `GET /api/videohub/crosspoints` — returns JSON with a `crosspoints` array
- `GET /api/network/status` — returns JSON with a `results` array and `generated_at`
- Each result record in `/api/network/status` has required keys

**Proposed approach:**
- Node-RED `node-red-contrib-unit-test` package, or
- External script (Python or bash) invoked via `npm test` in the CueCommander project directory
- Tests should be runnable in CI without physical hardware (mock/stub mode acceptable)

---

---

### REQ-CC-007 — Klang Mix Normalization API
**Priority:** Medium  
**Context:** The KLANG:konductor exposes a bidirectional OSC state push protocol
(confirmed via packet capture). All 16 mixes × 128 channels can be read by
cycling `SwitchUser` commands and collecting the resulting state dump.

**Requirement:** Implement Node-RED flows in the `vocalnames` project to:

1. Listen for inbound OSC on UDP port 9111 and populate `flow.klang_live_state`
   keyed by `"<mix>:<channel>"`, tracking `name`, `mute`, `visible`, `solo`.
2. On `POST /api/klang/buildconsensus`: orchestrate `ConnectRequest` + `KeepMePosted`
   + `SwitchUser i:1..16` (1s per mix), then compute and store master mix + variance report.
3. Expose `GET /api/klang/status`, `GET /api/klang/reportmixvariances`, `GET /api/klang/reportmastermix`.
4. FastAPI proxies `GET /dashboard/klang` and `POST /dashboard/klang/buildconsensus`.

**Implementation notes:**
- OSC receive port: 9111. Konductor at `192.168.200.146:9110`.
- Consensus: plurality vote per channel×attribute; tie-break by lowest mix number.
- Mute mismatches are `critical`; name/visible/solo mismatches are `warning`.
- Token auth: `X-Api-Token` header from `NODERED_API_TOKEN` env var (default `vn-api-changeme`).
- Protocol details in `feature-klang-normalize.md` in the vocalnames project.

---

## Change Log

| Date       | Change |
|---|---|
| 2026-04-18 | Initial document created |
| 2026-04-18 | REQ-CC-001 added (VideoHub stale data) |
| 2026-04-18 | REQ-CC-002 added (Dante subscriptions) |
| 2026-04-18 | REQ-CC-003 added (device status) |
| 2026-04-18 | REQ-CC-004 added (wireless battery) |
| 2026-04-18 | REQ-CC-005 added (network ping sweep) |
| 2026-04-18 | REQ-CC-006 added (test suite requirement) |
| 2026-04-19 | REQ-CC-007 added (Klang mix normalization) |
