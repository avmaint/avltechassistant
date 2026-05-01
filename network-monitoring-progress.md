# Network Monitoring — Work In Progress

Resume point if conversation is interrupted. All tasks reference this file.

## Context

Adding network monitoring to the operational dashboard. Data source is
`data/network.xlsx` (one row per NIC, key = AssetTag + NIC). Monitor column
controls which NICs are actively pinged. CueCommander (Node-RED, `uacts-g001:1880`)
will perform the pings; FastAPI proxies and enriches the results.

CueCommander runs on **macOS** (confirmed via `ipconfig getifaddr en0` exec node).
Ping syntax: `ping -c 3 -t 5 <ip>` (-t is timeout in seconds on macOS).

## Data Notes (network.xlsx)

- 60 rows, columns: AssetTag, NIC, MAC, Static-Reserved, IP, URL, Monitor, RelatedIssueId, Usage, Notes
- 28 rows Monitor=Yes, 26 Monitor=No
- Key is AssetTag+NIC; NIC is blank for single-NIC devices
- **Config exceptions (Monitor=Yes, no IP):** CSWU1, CUMU-G001/USBNIC,
  CUMU-G002/USBNIC, CUMU-G002/builtin, CUMU-E001/USBNIC, CUMU-E001/builtin
- Some IPs are "tbd" (rows 43-44) — those rows have Monitor=NaN, not Yes
- Row 42 has ambiguous AssetTag "ZVIU-D002 or CDLU-D001" — treat as-is
- IPs 192.168.201.x are on a different subnet (VideoHub control network)
- **Do NOT reference uac_network.xlsx** — deprecated in favour of network.xlsx

## Architecture Decision

**Cached ping pattern** (not request-time ping):
- CueCommander background inject (every 30s) pings all monitored IPs
- Results stored in Node-RED flow context
- `GET /api/network/status` reads from cache — fast response
- FastAPI `/dashboard/network` calls CueCommander and enriches with asset names
- Config exceptions (Monitor=Yes/no-IP) reported by FastAPI directly — no CueCommander needed

**Latency threshold for "high latency" alert:** avg > 50 ms

## Task Status

| # | Task | Status |
|---|------|--------|
| 22 | Progress doc | ✅ Done |
| 23 | Backend: load_network_data() + /assets/{tag}/network | ✅ Done |
| 24 | Backend: GET /dashboard/network | ✅ Done |
| 25 | Frontend: Network section in Asset Details | ✅ Done |
| 26 | Frontend: Network panel in Dashboard | ✅ Done |
| 27 | CueCommander: API flow JSON | ⬜ Pending |
| 28 | Tests: network endpoints | ✅ Done |
| 29 | Requirements docs update | ✅ Done |

## Files Changed / To Change

| File | Change |
|------|--------|
| `backend/main.py` | load_network_data(), /assets/{tag}/network, /dashboard/network |
| `frontend/script.js` | Network section in fetchAndRenderAssetDetails; dashboard network panel |
| `frontend/style.css` | Network section styles |
| `frontend/index.html` | No change needed |
| `tests/run_tests.py` | New tests for network endpoints |
| `cuecommander-requirements.md` | REQ-CC-005 (ping API) |
| `feature-op-dashboard.md` | Network panel section |
| `cuecommander-flows/api-network-ping.json` | New — import into CueCommander |

## CueCommander Deployment Instructions

1. Open CueCommander Node-RED UI at `http://uacts-g001:1880`
2. Menu → Import → select `webapp/cuecommander-flows/api-network-ping.json`
3. A new tab "API" will appear with the ping sweep flow
4. Review the "Monitored Targets" function node — update the target list if needed
5. Deploy (red Deploy button)
6. Verify: `curl http://uacts-g001:1880/api/network/status`

## Outstanding Issues

- REQ-CC-001: VideoHub crosspoint API returns stale data (see cuecommander-requirements.md)
- CueCommander has no test suite — add as an outstanding requirement
- Dante audio route monitoring: future work (virtual section, no single asset)
