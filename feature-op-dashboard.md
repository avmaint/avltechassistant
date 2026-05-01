# Feature: Operational Dashboard

## Purpose

A live operational dashboard that surfaces exceptions and status deviations by
comparing the static configuration stored in the asset/cable data against
real-time telemetry delivered by CueCommander (Node-RED). The goal is fast
situational awareness during setup, rehearsal, and show operations.

---

## Architectural Decisions (Confirmed)

| Decision | Choice | Rationale |
|---|---|---|
| Data delivery | FastAPI proxies CueCommander | Keeps CORS out of browser; route-comparison logic lives in Python next to config data |
| Update model | Browser polls `/dashboard/status` every 30 seconds | Sufficient latency tolerance; simpler than SSE/WebSocket |
| UI target | Mobile-responsive | Technicians may roam with tablets |
| Acknowledgement | Deferred (low priority) | Phase 3 |

**CueCommander base:** `http://uacts-g001:1880` (Node-RED, standard port)

CueCommander's current role is control, not monitoring. Most APIs needed for
this dashboard do not yet exist and will need to be built as new Node-RED flows.
The one exception is the VideoHub cross-point API, which exists today.

---

## Phased Implementation Plan

### Phase 1 — Available Now (no new CueCommander flows required)

#### 1a. Data Completeness Audit (fully static, no CueCommander)
Runs against the asset/cable Excel data loaded into the backend:

- Assets with `InService=Y` but no rack assignment
- Assets with `InService=Y` but no cables (isolated nodes)
- Route cables (`Type == route`) that reference asset tags not in the asset table
- Assets with `InService=Y` and no building/floor/room location data
- Route cables where `SrcPort` or `DstPort` cannot be parsed

#### 1b. VideoHub Cross-point Comparison
Cross-references cables with `Type == route` and `SrcTag == DstTag` against the
live VideoHub routing state from CueCommander.

**Existing script:** `compare_crosspoints.py` — logic will be ported into FastAPI.

**API:** `GET http://uacts-g001:1880/api/videohub/crosspoints`
Returns `{ crosspoints: [ { input: N, output: N }, ... ] }`

**Port format in cables data:**
- `SrcPort` = `in_NN` (input number)
- `DstPort` = `out_NN` (output number)

**Exception types:**
- **Mismatch** — cable record says output N routes to input M, but VideoHub has a different input
- **Output absent** — an output defined in cables has no corresponding cross-point in the live system
- **Undocumented route** — a live cross-point has no matching cable record (future enhancement, requires full VideoHub output enumeration)

**Scope:** Currently scoped to asset `2507-0700` (the VideoHub). Additional routing
devices will be added as more `type == route` cable records are created.

---

### Phase 2 — Requires New CueCommander Flows

#### 2a. Device Online / Offline Status
CueCommander will need a new flow that polls (ICMP ping or SNMP) all managed
devices and exposes the result as a REST endpoint.

**Proposed API shape (to be built in CueCommander):**
```json
GET /api/devices/status
{
  "devices": [
    { "asset_tag": "ZVKU-A001", "online": true,  "last_seen": "2026-04-18T14:32:00Z" },
    { "asset_tag": "ZVKU-A002", "online": false, "last_seen": "2026-04-18T10:01:00Z" }
  ]
}
```

**Backend comparison:** join against asset table; flag `InService=Y` assets that
are offline, and online devices with no asset record.

#### 2b. Wireless Microphone Battery Levels
CueCommander will need flows that query the receiver hardware APIs and aggregate
battery state across all channels.

**Proposed API shape (to be built in CueCommander):**
```json
GET /api/wireless/battery
{
  "channels": [
    { "asset_tag": "ZVKU-W001", "receiver_tag": "ZVKU-R001", "channel": 1,
      "battery_pct": 85, "estimated_mins": 240, "status": "ok" },
    { "asset_tag": "ZVKU-W003", "receiver_tag": "ZVKU-R001", "channel": 3,
      "battery_pct": 8,  "estimated_mins": 22,  "status": "critical" }
  ]
}
```

**Thresholds (configurable):**
- Warning: < 30%
- Critical: < 10%

---

### Phase 3 — Future / Low Priority

- **Temperature monitoring** — once hardware exposes thermal data
- **Exception acknowledgement** — operators suppress known/intentional deviations
- **Undocumented live routes** — full cross-point audit (not just comparing defined cables)

---

## Backend API Design

### `GET /dashboard/status`

Aggregates all available data sources and returns a single structured response.
Sources that are unavailable (CueCommander unreachable, Phase 2 not built yet)
return a `null` payload with an `unavailable` status — the dashboard renders
what it can without erroring.

```json
{
  "generated_at": "2026-04-18T14:32:05Z",
  "panels": {
    "data_completeness": {
      "status": "warning",
      "exceptions": [
        { "severity": "warning", "category": "no_rack", "asset_tag": "ZVKU-B001",
          "message": "In-service asset has no rack assignment" },
        ...
      ]
    },
    "crosspoint": {
      "status": "ok" | "warning" | "critical" | "unavailable",
      "source": "uacts-g001:1880",
      "exceptions": [
        { "severity": "warning", "cable_tag": "RTE-0042",
          "asset_tag": "2507-0700", "output": 3,
          "expected_input": 2, "actual_input": 5,
          "message": "Output 3: expected input 2, got input 5" },
        ...
      ]
    },
    "device_status": {
      "status": "unavailable",
      "exceptions": []
    },
    "battery": {
      "status": "unavailable",
      "exceptions": []
    }
  }
}
```

### `GET /dashboard/status/crosspoint` *(optional per-panel refresh)*

Returns only the crosspoint panel. Useful if a panel needs independent refresh.

---

## Frontend Dashboard Tab

### Layout
```
┌─────────────────────────────────────────────────────┐
│ Dashboard           Last updated: 14:32:05  [↺ now] │
│ Auto-refresh: [ON]                                   │
├─────────────────────────────────────────────────────┤
│ ● CRITICAL  Battery: ZVKU-W003 (8%, ~22 min)        │
├─────────────────────────────────────────────────────┤
│ ▼ WARNING (3)                                       │
│   Route mismatch: RTE-0042  Output 3 → expected     │
│     in_02, live in_05                   [Details]   │
│   No rack: ZVKU-B001                    [Details]   │
│   Offline: ZVKU-A002 (last seen 4h ago) [Details]   │
├─────────────────────────────────────────────────────┤
│ ● OK  Data completeness · VideoHub · (Battery N/A)  │
└─────────────────────────────────────────────────────┘
```

- Panels collapsed by default except those with active exceptions
- **[Details]** click sets the global target asset and navigates to the
  relevant tab (cable tag → Cable Filter; asset tag → Asset Details)
- Mobile: single-column stack, large touch targets
- `unavailable` panels shown as greyed-out with a tooltip explaining why

---

## Remaining Questions

1. **Other routing devices:** Are there other cross-point routing matrices beyond
   the VideoHub (e.g., audio matrix, Dante controller, HDMI switcher)?
   Each would need its own CueCommander API and cable `Type == route` records.

2. **VideoHub scope:** The existing script is hard-coded to asset `2507-0700`.
   Is that the only VideoHub, or will there be multiple routing devices of the
   same type? (Affects how the backend parameterises the comparison.)

3. **Device status scope:** Which devices should be polled for online/offline?
   All `InService=Y` assets, or a curated subset (e.g., only networked devices)?
   Is there already a field in the asset data that marks a device as
   network-manageable?

4. **Wireless mic hardware:** What receiver hardware/protocol is in use?
   (Shure Wireless Workbench API, ULX-D/QLX-D Dante, Lectrosonics Venue,
   Sennheiser WSM?) This determines what CueCommander flows need to be built.

5. **CueCommander accessibility:** Is `uacts-g001` reachable from the same
   host that runs the FastAPI backend, or do they run on different machines/VLANs?

6. **Dashboard tab placement:** Should Dashboard be the first tab (leftmost,
   default on load) since it's the primary operational view, or should the
   current Asset Search default be preserved?
