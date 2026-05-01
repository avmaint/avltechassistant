# Internal Routes Table Feature Analysis

## Summary

The current Connectivity Diagram view renders two bottom tables by calling two separate endpoints:

- `/diagram/connections/inputs`
- `/diagram/connections/outputs`

The backend logic behind those tables is shared in [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:671). For outputs, it currently selects every cable row where `SrcTagNorm == target_norm` and does not exclude self-route rows. As a result, internal route cables where:

- `SrcTagNorm == DstTagNorm`
- `Type` contains `"route"`

are included in the outbound table.

The cleaner design is to replace the current split API with a single combined endpoint that returns three datasets:

- `inputs`
- `outputs`
- `internal_routes`

The frontend should then render three bottom tables from one response and stop showing internal routes in the outbound table.

## Current State

### Backend

The main connection-table helper is [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:671).

Its current behavior is:

- input mode: all rows where `DstTagNorm == target_norm`
- output mode: all rows where `SrcTagNorm == target_norm`
- no dedicated classification for internal routes
- no exclusion of internal routes from outbound rows

The existing endpoints are:

- [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:773) `/diagram/connections/inputs`
- [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:785) `/diagram/connections/outputs`

### Frontend

The diagram view is currently wired for exactly two tables:

- container constants in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:18)
- sort-state registration in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:58)
- fetch/render flow in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:1036)
- generic table renderer in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:1842)

The print CSS also only knows about two diagram connection table containers in [frontend/style.css](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/style.css:378).

### Tests

The manual backend suite lives in [tests/run_tests.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/tests/run_tests.py:1). It already contains internal-route-related coverage for route traversal behavior, but it does not cover the bottom connection-table API shape or the requirement that internal routes be separated out of the outbound table.

### Requirements

The current requirements still specify only two bottom tables in [requirements.md](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/requirements.md:76):

- one for input connection details
- one for output connection details

They do not define a dedicated internal-routes table or a combined endpoint contract.

## Proposed Design

### API Design

Replace the two table-specific endpoints with a single endpoint, for example:

- `/diagram/connections?target_tag=<asset>`

Response shape:

```json
{
  "inputs": [],
  "outputs": [],
  "internal_routes": []
}
```

This design is preferable because:

- the frontend makes one request instead of three
- classification rules live in one place
- future table additions stay additive within one payload
- the client and tests validate one coherent contract instead of coordinating multiple calls

### Classification Rules

Connection rows should be classified as follows:

1. `internal_routes`
   - rows where `SrcTagNorm == target_norm`
   - and `DstTagNorm == target_norm`
   - and `Type` contains `"route"` case-insensitively

2. `inputs`
   - rows where `DstTagNorm == target_norm`
   - excluding rows already classified as `internal_routes`

3. `outputs`
   - rows where `SrcTagNorm == target_norm`
   - excluding rows already classified as `internal_routes`

This keeps the categories mutually exclusive and fixes the current defect.

### Table Shapes

The frontend renderer is generic, so each array can have its own columns as long as keys are stable.

Recommended row shape:

- `inputs`
  - `TargetPort`
  - `SourcePort`
  - `Protocol`
  - `CableID`
  - `PartnerAssetTag`
  - `PartnerManufacturer`
  - `PartnerModel`
  - `PartnerUsage`

- `outputs`
  - `TargetPort`
  - `DestinationPort`
  - `Protocol`
  - `CableID`
  - `PartnerAssetTag`
  - `PartnerManufacturer`
  - `PartnerModel`
  - `PartnerUsage`

- `internal_routes`
  - `SourcePort`
  - `DestinationPort`
  - `Protocol`
  - `CableID`
  - `Type`

I do not recommend partner-asset columns for internal routes because the partner is the same device and adds no information.

## Required Code Changes

### Backend

#### 1. Replace the existing helper with a classifier

Refactor [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:671) so that it no longer operates as a two-mode helper. Instead, introduce a single function that:

- validates the target tag once
- computes the internal-route mask once
- builds `inputs`, `outputs`, and `internal_routes`
- returns a single payload object

Suggested internal structure:

- a small helper for `is_internal_route_row(row)` or equivalent DataFrame mask
- one helper for formatting external partner rows
- one helper for formatting internal route rows
- one public endpoint handler returning the combined payload

#### 2. Retire or deprecate the old endpoints

Recommended approach:

- remove frontend usage of `/diagram/connections/inputs`
- remove frontend usage of `/diagram/connections/outputs`
- either delete those endpoints or leave them temporarily as wrappers during transition

For a clean implementation, I would remove them once the frontend and tests are updated.

#### 3. Preserve existing formatting behavior

The new combined endpoint should preserve:

- canonical tag display via `canonical_display_tag`
- JSON-safe cleanup via `clean_dataframe_for_json`
- cable-junction handling for external partner tables where applicable

### Frontend

#### 1. Add a third table container

Update the diagram view markup to include a third sibling container, e.g.:

- `diagramInputConnections`
- `diagramOutputConnections`
- `diagramInternalRoutes`

This change is required wherever the Connectivity Diagram tab DOM is defined.

#### 2. Replace two fetches with one combined fetch

Update the current fetch/render block in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:1036) so that it:

- fetches the new combined endpoint once
- clears all three containers
- renders:
  - `"Input Connections"`
  - `"Output Connections"`
  - `"Internal Routes"`

#### 3. Add sort-state support for the third table

Extend the constants and `tableSortStates` in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:18) and [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:58) to register the new table ID.

#### 4. Keep the generic renderer

The renderer in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:1842) is already sufficient. No redesign is required as long as the backend emits stable field names.

#### 5. Update print styling

Extend [frontend/style.css](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/style.css:378) so the internal-routes table receives the same print page-break behavior as the existing two tables.

## Required Test Changes

Both new and modified tests are needed.

### Backend API Tests to Add

Add tests in [tests/run_tests.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/tests/run_tests.py:1) for the new combined endpoint:

1. `test_diagram_connections_combined_endpoint_shape`
   - request the new endpoint for a known routed asset such as `ZVKU-A001`
   - verify the response is an object containing:
     - `inputs`
     - `outputs`
     - `internal_routes`
   - verify each is a list

2. `test_internal_routes_excluded_from_outputs`
   - request the new endpoint for an asset known to have internal routes
   - assert no row in `outputs` satisfies:
     - same source/destination asset implicitly represented as internal route
     - or `CableID` matches any cable returned in `internal_routes`

3. `test_internal_routes_present_in_internal_routes_table`
   - verify that the known route cable for `ZVKU-A001` appears in `internal_routes`
   - verify the row has route-oriented fields such as:
     - `SourcePort`
     - `DestinationPort`
     - `CableID`

4. `test_non_routed_asset_returns_empty_internal_routes`
   - choose an asset without internal route rows
   - verify `internal_routes == []`
   - verify `inputs` and `outputs` still behave normally

### Existing Tests to Modify

1. Replace any future reliance on:
   - `/diagram/connections/inputs`
   - `/diagram/connections/outputs`

   with the new combined endpoint.

2. Add a regression check that the three tables are mutually exclusive:
   - a cable ID found in `internal_routes` must not appear in `outputs`
   - if internal routes are also excluded from inputs, it must not appear in `inputs` either

3. Keep the existing route traversal tests.
   These cover different behavior and should remain unchanged except for any shared helper improvements.

### Frontend Verification

There is no automated frontend test harness in the repo, so manual verification should be part of acceptance:

- open Connectivity Diagram for `ZVKU-A001`
- confirm internal route rows appear only in `Internal Routes`
- confirm outbound rows no longer contain those route rows
- confirm all three tables sort correctly
- confirm print view includes the third table with page breaks

## Requirements Updates Needed

The requirements document should be updated in [requirements.md](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/requirements.md:76).

### Replace the current two-table requirement

Current requirement language says:

- two text tables below the connectivity diagram
- one for input connection details
- one for output connection details

It should be revised to:

- three text tables below the connectivity diagram
- one for input connection details
- one for output connection details
- one for internal route details

### Recommended revised requirement language

Suggested replacement text:

> Below the connectivity diagram, three text tables must be displayed for the target device: Input Connections, Output Connections, and Internal Routes. Input and Output tables must list only external connections for the target device. Internal route rows, defined as cables where `SrcTag` equals `DstTag` and `Type` contains `route`, must not appear in the Output Connections table and must instead appear only in the Internal Routes table. All columns in these tables must be sortable by clicking their headers. These tables must be included in the print view, with a page break inserted before each table.

### Add API contract expectation

In the testing or backend behavior sections, add a note that the frontend consumes a combined diagram-connections payload containing:

- `inputs`
- `outputs`
- `internal_routes`

This is useful because it formalizes the new integration contract rather than leaving it implicit in the code.

## Risks and Decisions

### Decision: whether to exclude internal routes from inputs as well

The requested behavior explicitly mentions removing them from outbound and putting them in a third table. From a data-model perspective, the cleaner rule is to exclude them from both inputs and outputs and make the categories mutually exclusive.

I recommend that approach because:

- it avoids duplicated rows across tables
- it makes the table semantics unambiguous
- it simplifies test expectations

If the product intent is different, that decision should be made before implementation.

### Decision: whether to retain legacy endpoints temporarily

For a staged rollout, wrappers could remain for a short time. For a clean implementation in this repo, removing the old endpoints after the frontend update is reasonable because the frontend and tests are local to the same codebase.

### Risk: internal route identification by `Type`

The route classification depends on `Type` containing `"route"`. If spreadsheet data is inconsistent, some internal routes may be missed. That is an existing data-contract risk, not something introduced by the redesign.

## Implementation Sequence

1. Refactor backend connection-table logic into a single combined classifier.
2. Add the new combined endpoint.
3. Remove or deprecate the old split endpoints.
4. Update the frontend to fetch once and render three tables.
5. Add the third container and print styling.
6. Update backend tests for the new payload and regression requirements.
7. Update `requirements.md` to describe the third table and combined payload semantics.
8. Run manual verification against a known routed asset and a non-routed asset.

## Acceptance Criteria

- The Connectivity Diagram view renders three bottom tables: Input Connections, Output Connections, and Internal Routes.
- Internal route rows do not appear in the Output Connections table.
- Internal route rows appear in the Internal Routes table.
- The frontend uses one combined diagram-connections endpoint.
- Automated backend tests validate the new payload shape and the internal-route separation rule.
- `requirements.md` is updated to describe the third table and the exclusion rule.
