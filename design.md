---
title: "AVL Tech Assistant Design"
---

# Intention

AVL Tech Assistant is the interactive query and visualization layer over the UAC's AV/lighting/network asset inventory and cabling data. It lets staff search assets, explore cable connectivity as diagrams, look up rack/floor locations, and cross-reference knowledge base issues, without hand-querying the underlying database. `requirements.md` in this directory is the functional spec (feature-by-feature); this document covers the architecture and the reasoning behind it — read both together.

# System Context

Three services, each its own repo, composed together by `runbook/docker-compose.yml`:

```
Postgres  <-  avl_data/backend (FastAPI CRUD, raw psycopg/SQL, no ORM)
                    ^
                    |  HTTP (AVL_DATA_URL, default http://localhost:8002)
                    |
          avltechassistant/backend (FastAPI, this repo's "backend")
                    ^
                    |  HTTP (API_BASE_URL)
                    |
          avltechassistant/frontend (static HTML/CSS/JS, this repo's "frontend")
```

`avl_data` owns the durable schema and is the only service that writes to Postgres. `avltechassistant/backend` is a **read-mostly aggregation layer**: at startup (and on the "Reload Data" button) it pulls the full assets/cables/network/knowledgebase tables from `avl_data` into in-memory pandas DataFrames (`df_assets`, `df_cables`, `df_knowledgebase`), then serves all queries — search, diagram building, connectivity lookups — out of those DataFrames rather than hitting Postgres per request. This trades staleness (bounded by a manual reload) for query speed and lets diagram/graph computations use plain pandas/Python instead of SQL.

# Why This Stack

- **No ORM anywhere.** `avl_data`'s CRUD routes use raw SQL via `psycopg`; this repo's backend uses pandas DataFrames as its query layer. Both choices keep the data model schema-light — see "Asset Relationship Fields" below, which depends on this.
- **Frontend has no build step.** Per `requirements.md` Section 3, the frontend is plain HTML/CSS/JS — one `index.html`, one `script.js` (~4700 lines, functions closed over a single `DOMContentLoaded` listener), one `style.css`. No framework, no bundler, no TypeScript. This keeps deployment to "serve static files" and avoids a build pipeline for a small internal tool. New UI work should extend `script.js`/`index.html` in place rather than introducing a framework for one feature.
- **Deploy topology mirrors CueCommander-NR's pattern**: edit locally, commit, push, then `runbook.sh restart` (or the relevant service) pulls and redeploys. Nothing runs against production data by default in local development — the `runbook` docker-compose stack targets real infrastructure (hostnames, `.env.production`) and should not be started casually from a dev session.

# Data Model

Flat tables (no relational asset-to-asset foreign keys): Assets, Cables, Network (NICs), Knowledge Base, Licenses. Column-name mapping between the `avl_data` API's snake_case fields and this app's PascalCase display fields lives in `_ASSETS_DB_TO_EXCEL`, `_CABLES_DB_TO_EXCEL`, `_NETWORK_DB_TO_EXCEL`, `_KB_DB_TO_EXCEL` near the top of `backend/main.py`.

## Asset Relationship Fields (recurring pattern)

Several asset fields express a relationship to *another* asset by storing that asset's tag as free text on the child row, resolved at query time — there is no foreign key or join table. Matching is always case-insensitive and whitespace-normalized (`.astype(str).str.strip().str.upper()`), consistent with `normalize_tag_value()`.

| Field | Meaning | Resolved by |
|---|---|---|
| `Rack` | The rack asset this device is mounted in | `get_rack_profile()` (`backend/main.py`) |
| `Location` (when `Category` == `Software`) | The asset this software is installed on — can be a Computer or another Software asset | `_get_installed_on_asset()` / `_get_installed_software_for_asset()` (`backend/main.py`) |

New relationship fields should follow this same shape — a free-text column on the child referencing the parent's tag, resolved with a small helper near the existing ones — rather than introducing a schema migration in `avl_data`. This keeps the read layer schema-agnostic and matches how `Rack` already works.

# Subsystem: Asset Details — Installed Assets

## Overview

Software assets (`Category` == `Software`) record what host they're installed on via their own `Location` field, holding the host asset's tag. A host can be a Computer, or another Software asset — software can be installed on other software (e.g. a language runtime installed inside a container platform, itself installed on a computer). The Asset Details page surfaces this bidirectionally.

## Backend (`backend/main.py`)

- `_get_installed_software_for_asset(target_norm)` — returns every `Category` == `Software` row whose `Location` matches `target_norm`. Used both for a Computer's "what's installed on me" list and, when the subject is itself Software, its own children.
- `_get_installed_on_asset(location_value)` — resolves a Software asset's own `Location` value to the parent asset row (0 or 1 results; `Location` is a single value).
- Both are called unconditionally inside `GET /assets/{asset_tag}/details` and returned as `installed_software` (list) and `installed_on` (list, 0–1 entries) alongside the endpoint's existing fields. The endpoint does not gate on category server-side at all — it always computes both lists cheaply from whatever `Location` values happen to match, regardless of the subject asset's own `Category`. This mirrors how `input_partners`/`output_partners`/`network` are already always computed regardless of whether a given asset has any, and it matters here specifically: see the frontend gating note below for why category can't be trusted to identify "is this a host machine."

## Frontend (`frontend/script.js`, `frontend/index.html`)

- `renderInstalledAssets(asset, installedSoftware, installedOn, container)` renders into `#installedAssetsContainer`, positioned between the Network section and the Partners section in `index.html`.
- **Gating is data-driven, not category-driven, for the host side of the relationship.** The first implementation gated the "Installed Software" table on `asset.Category === 'Computer'`, on the assumption that host machines would carry that category. Production data showed this was wrong: of several hundred assets, only 9 use `Category` = `Computer` — host machines are overwhelmingly categorized by their primary AV function instead (e.g. `CUMU-G001`, a Mac Mini running Docker/ProPresenter/OBS/node/python/etc., is `Category` = `Video`). Gating on `Category === 'Computer'` silently hid a real, backend-confirmed relationship (a real bug caught via user report, not caught by the earlier synthetic-data tests, which happened to label their test host `Category: "Computer"` and so never exercised the mismatch). The corrected rule: show "Installed Software" whenever `installedSoftware.length > 0`, independent of the host's own `Category`. `asset.Category` (case-insensitive) is still checked for exactly one thing — whether this asset is itself `software`, which additionally shows the "Installed On" table (always, even when empty, since a Software asset with no recorded host is still worth flagging) ahead of "Software Installed On This Asset" (same non-empty-gated rule as the host case). Any other category with an empty `installedSoftware` list renders nothing — no heading, no empty-state message (distinct from the empty-but-labeled state used elsewhere, e.g. "No network records found").
- **Takeaway for future category-gated UI in this app:** don't assume a category taxonomy value (`Computer`, etc.) is actually applied consistently across inventory data. Where possible, gate on the presence of the data itself (e.g. a non-empty related list) rather than on a category label describing what an asset "is," since categories here describe primary function/display grouping, not a strict type system.
- Table rows are built via `document.createElement`/`.textContent`/`.dataset`, **not** by interpolating values into an HTML string — this is required, not stylistic: asset fields (tag, manufacturer, etc.) are user-editable inventory data, and the existing `escapeHtml()` helper elsewhere in this file only encodes `&`/`<`/`>`, not `"`. Interpolating its output into a double-quoted HTML attribute (e.g. `data-asset-tag="${escapeHtml(x)}"`) is exploitable by a value containing a `"` — it breaks out of the attribute and can inject a live event-handler attribute. `element.dataset.x = value` / `element.textContent = value` have no such gap because the browser never re-parses the string as markup. Any new table row builder in this file should use DOM construction for the same reason, not follow the `innerHTML` + `escapeHtml()` template-literal pattern used in older sections (e.g. `renderAssetNetwork`) for anything containing editable asset data.
- Reuses the existing `.network-table` CSS class rather than introducing a new one — it's already a generic bordered-table style with no NIC-specific styling baked in.

# Subsystem: Operational Dashboard

## Overview

The Dashboard tab (default tab on load) compares the static asset/cable/network data this app already owns against real-time telemetry from CueCommander (Node-RED, `CUECOMMANDER_BASE`, default `http://cumu-g001.local:1880`), polling `GET /dashboard/{crosspoint,network,klang}` every 30s. See `requirements.md` Section 9 for the functional spec of each panel; this section covers the shared architecture and one real bug it produced.

## Backend Pattern: Independent Panel Degradation

Each of the three panels (`crosspoint`, `network`, `klang`) is fetched and computed independently within its own `try`/`except`; a CueCommander-reachability failure in one panel doesn't take down the others. Each panel reports its own `status` (`ok`/`warning`/`critical`/`unavailable`/`pending`) and, when `unavailable`, an `error` string explaining why — this is deliberate so the dashboard is still useful when only some of CueCommander's flows are up. `GET /dashboard/*` never proxies a CueCommander error as an HTTP error itself; it always returns 200 with the degraded panel(s) inline.

## Crosspoint Panel: Adapter Registry

`GET /dashboard/crosspoint` groups route cables (`SrcTag == DstTag`, `Type == "route"`) by the routing device's asset tag, then dispatches each group through `_ROUTE_ADAPTER_FOR_ASSET` (asset tag → adapter name) to a function registered via the `@_route_adapter("name")` decorator. Adding support for a new routing device type (a Dante controller, an HDMI matrix, etc.) means registering a new adapter function and adding its asset tag(s) to the lookup — the panel-assembly loop itself doesn't need to change. A device with route cables but no registered adapter still gets a panel (`status: "pending"`), not silent omission, so gaps in monitoring coverage stay visible.

## Network Panel: This App Is the Source of Truth for Targets

Unlike the crosspoint and Klang panels (which only *read* from CueCommander), the network panel *pushes* state to it: every `GET /dashboard/network` call first pushes the current `Monitor=Yes` target list to CueCommander (`POST /api/network/status`'s targets, fire-and-forget — failures are silently ignored since the read half of the same call will just report `unavailable` if CueCommander is genuinely down) before reading back ping results. CueCommander never calls this app to ask what to monitor; it only ever receives pushes. This means the network table (`data/network.xlsx`) is the single place target configuration is edited — CueCommander has no independent notion of which devices to ping.

## Klang Panel: Proxy Only, Logic Lives in CueCommander-NR

`/dashboard/klang*` are thin proxies (`_fetch_nodered_json`/`_post_nodered_json`) to CueCommander's vocalnames HTTP API — no OSC, no consensus logic, and no Konductor communication happens in this codebase. See CueCommander-NR's own `design.md` ("Subsystem: Klang (Personal Monitoring) — Mix Consistency Dashboard") for the actual sweep/consensus/setvariance implementation.

### Known Hazard: an undocumented feature is an untested feature

This panel (and the crosspoint/network panels alongside it) existed in production, fully built, with zero mention in this file or `requirements.md` prior to 2026-07-28 — the only trace was a standalone planning doc (`feature-op-dashboard.md`) that predates the Klang panel entirely and was never updated once it shipped. The consequence was concrete, not hypothetical: `POST /dashboard/klang/setvariance` had a real bug (silently dropped every OSC send while always reporting success — see CueCommander-NR `requirements.md` KL-06/07/08) that shipped and went unnoticed, in part because there was no test anywhere — in this repo or CueCommander-NR's — that exercised the endpoint at all. A feature that isn't in the requirements doc doesn't get requirements-driven test coverage. When a feature ships, its planning doc's content belongs folded into `requirements.md`/`design.md` and the planning doc retired, not left to accumulate alongside the real docs as a second, drifting source of truth.

# Current Known Limitations

See `requirements.md` Section 7 (Known Issues) and Section 10 (Pending Enhancements) for the live list — kept there rather than duplicated here since it changes per-feature, not architecturally.
