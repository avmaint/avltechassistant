# Web Application Requirements

This document outlines the requirements for the interactive web application.

## 1. Core Functionality

-   **Interactive Data Query:** The application must allow users to query asset and cable data dynamically.
-   **Asset Search:**
    -   Searchable by asset tag, manufacturer, and model.
    -   Results displayed in a tabular format.
    -   Asset tags in the results table are clickable links that navigate to the Asset Details tab for that asset and update the Connectivity Diagram in the background.
    -   Each row in the asset table exposes a "View in Rack" action button that switches to the Location tab and renders the rack profile for that asset.
    -   Pressing Enter in any search input field triggers the search.
    -   "In Service Only" checkbox filters results to only show assets with InService="Y" (checked by default).
-   **Cable Filtering:**
    -   Filterable by a target asset tag or a cable ID.
    -   Filterable by connection direction: in-bound, out-bound, or both.
    -   Filterable by cable type.
    -   Filtered cable data displayed in a tabular format.
-   **Connectivity Diagram Rendering:**
    -   Dynamically generate and display connectivity diagrams based on filtered cable data.
    -   Diagrams should visually represent connections between assets.
    -   The diagramming technique should render the actual diagram, not just DOT code.
    -   Asset tags must be handled case-insensitively to avoid duplicate nodes when casing differs between data sources.
    -   Each node label must include the asset tag, manufacturer, model, and usage fields centered in the body.
    -   **Cable-to-Cable Connections:** When a cable terminates at another cable (for example one row references another row's `Tag` in `SrcTag` or `DstTag`), the splice/junction must be depicted as a small dot (`shape=point`) node. The contributing cable segments remain separate labeled edges and the connection continues through the dot to the next cable segment or final destination asset. This pattern can repeat for multiple intermediate cables.
    -   **Port Label Ordering:** Port labels on each node side are sorted using a natural (numeric-aware) sort so that embedded integers are ordered by value rather than lexicographically — e.g. `2 < 3 < 12 < 23` instead of `12 < 2 < 23 < 3`. This applies to both the DOT renderer and the Cytoscape/ELK renderer.
    -   **Crossing Minimisation (Bidirectional Barycenter):** Port order is refined using the full Sugiyama bidirectional barycenter algorithm. Two forward+backward sweep pairs are run, each followed by a final forward sweep: the forward pass ranks each out-port by the average vertical rank of the in-ports it connects to; the backward pass ranks each in-port by the average rank of the out-ports feeding it. Sweeps are seeded with natural sort and alternate until convergence. Barycenter lookup is junction-transparent: when an edge leads to a cable-splice junction node, the lookup follows through to the real asset endpoint on the other side. Natural sort is used as the tiebreaker within each sweep. This applies in `compute_graph_elements` (Cytoscape/ELK path); the DOT path relies on Graphviz's own crossing minimiser and uses only the natural sort.
    -   **Post-Layout Port Y-Sort (frontend):** After ELK computes node positions but before HTML labels are rendered, a second port-order pass runs in the browser (`layoutstop` handler). All original port lists are snapshotted, then for every real (non-junction, non-phantom) node: `out_ports` are sorted by the average absolute-Y of the connected destination port on each target node; `in_ports` are sorted by the average absolute-Y of the connected source port on each source node. Port Y is computed from the node's actual canvas position and height so that tall nodes with many ports are handled correctly. Unconnected ports sort to the end (stable). This corrects cases where ELK's final node positions differ from the backend's crossing-minimisation assumptions, eliminating forward-edge crossings that the backend sort cannot anticipate.
    -   **Back-Edge Routing (phantom waypoint nodes):** Edges that flow right-to-left against the ELK left-to-right layout direction (detected when the target node's X position is less than the source node's X) cannot be visually routed around node boundaries using Cytoscape bezier weights (which are clamped to [0,1] and cannot reach outside the node span). Instead, each such back-edge is replaced in the `layoutstop` handler with four invisible 1×1 phantom waypoint nodes at the corners of an orthogonal U-shape, connected by five straight segment edges. The U-shape exits the right side of the source node, drops below both nodes, crosses below, and enters the left side of the target node — exactly matching the port positions on each end. Only the final segment carries the arrowhead; the middle segment carries the edge label.
    -   **Back-Edge Lane Assignment:** When multiple back-edges exist between the same node pair (or across the diagram), all would otherwise stack on the same U-shape path. Back-edges are sorted by source-port absolute Y in descending order (bottom port → innermost lane) and assigned lane indices. Lane `i` offsets the right-stub X, left-stub X, and bottom Y each by `i × 22 px` (matching the port row height). The innermost lane (bottom-most source port) has the smallest footprint; successively higher ports fan outward. Sorting descending eliminates crossings between the nested U-shapes: the outer lanes' longer horizontal entry segments run above all inner lanes' vertical stubs, so no two segments intersect. The bottom baseline (`baseBelow`) is computed once as the global maximum node bottom across all back-edges plus 80 px clearance, ensuring every lane clears all node boundaries.
    -   **Phantom Node Styling:** Phantom waypoint nodes carry `is_phantom: true` in their data and are matched only by the `node[?is_phantom]` style rule (1×1 px, fully transparent, no border, `events: no`). The asset-node style rule is scoped to `node[!is_junction][!is_phantom]` to prevent phantom nodes from inheriting `background-color: data(bg_color)` and other asset-only mappings.
    -   **Viewport Fit After Back-Edge Routing:** After all phantom nodes and segment edges are inserted, `cyInstance.fit(30)` is called so the below-nodes U-shape corridor is visible. ELK's own fit covers only the original nodes and would leave the routed segments off-screen.

## 2. User Interface (UI)

-   **Structure:** The application will be a single-page web application.
-   **Navigation:** Separate tabs must be provided for:
    -   Asset Search Results.
    -   Cable Filtering Results (table).
    -   Connectivity Diagram (visual rendering).
    -   Cross-point matrix exploration.
    -   Asset Details.
    -   Location (rack profile).
    -   Signal Path Finder.
    -   Knowledge Base.
-   **Input Controls:**
    -   Text input fields for asset tag, manufacturer, model searches.
    -   Text input field for target asset tag or cable ID for cable filtering.
    -   Dropdown/selection for connection direction (in-bound, out-bound, both).
    -   Text input field for cable type filtering.
    -   Text input field for protocol filtering so users can isolate specific logical paths (e.g., Dante, SDI).
    -   All text input fields support pressing Enter to trigger the associated action button (search, view diagram, view details, etc.).
    -   Multi-select control (located on the Asset Results tab) for asset search results to choose which columns appear in the table (defaulting to Asset Tag, Model, Manufacturer, Description, Usage).
    -   A persistent "Select" checkbox column in the asset table so users can add rows to the diagram/cable view regardless of which columns are displayed; selected assets must always be honored in downstream views even when they are not adjacent to the current target.
    -   A globally accessible "Reload Data" button so users can refresh the asset and cable sources without restarting services. A collapsible "Reload History" panel adjacent to the button displays a timestamped audit log of all reload events for the current server session, including asset/cable/KB record counts and any errors.
    -   Diagram nodes are interactive:
        -   **Left-click**: Makes the clicked node the new target node and refreshes the diagram centered on that node.
        -   **Right-click**: Exposes a context menu with the following options; all changes are reflected immediately in both the cable table and the rendered diagram:
            -   **Hide Node**: Removes the node from the diagram.
            -   **Add Inbound**: Expands all in-bound connections for the node.
            -   **Add Outbound**: Expands all out-bound connections for the node.
            -   **Add inbound for outbound**: Adds the subset of inbound source nodes whose signal is routed to the node's outbound connections via an internal route or passthrough cable (a cable where SrcTag == DstTag == the node and Type contains "route" or "passthrough"). Route cables are traversed directionally: the outbound cable's source port must match the route cable's destination port, and the inbound source port is the route cable's source port. Passthrough cables are traversed bi-directionally: in addition to the normal direction, the outbound cable's source port may also match the passthrough cable's source port, yielding the passthrough cable's destination port as the inbound port (and vice versa).
            -   **Add outbound for inbound**: The mirror of "Add inbound for outbound". Adds the subset of outbound destination nodes whose signal originates from the node's inbound connections via an internal route or passthrough cable. Route cables are traversed directionally; passthrough cables are traversed bi-directionally in the same manner as above.
        -   Nodes display a pointer cursor on hover to indicate they are clickable.
    -   Multi-select controls must allow users to choose which asset fields (Tag, Manufacturer, Model, Usage) appear on node labels and which cable fields (Tag, Type, In-Port→Out-Port, Usage) appear on cable labels. Each list must include every available field from the underlying dataset with the default values pinned to the top (Tag/Manufacturer/Model/Usage for nodes; Tag/Type/In-Port→Out-Port/Usage for cables) and the remaining fields sorted alphabetically. The node label list must also include a virtual **BFRS** option that concatenates Building, Floor, Room, and Sector (non-empty parts only) separated by `/`; this field does not correspond to a single database column and is computed at render time.
    -   Checkboxes must allow users to toggle color-coded treatment of node backgrounds (based on asset Category) and cable link colors (based on Protocol) using industry-appropriate palettes. The "Color Edges by Protocol" option is checked by default to provide visual differentiation of cable types.
    -   The "Exclude Internal Routes" checkbox (checked by default) filters out cables where SrcTag equals DstTag and Type contains "route", preventing internal routing entries from cluttering the diagram.
    -   Passthrough cables (Type contains "passthrough") must be rendered in the diagram with arrows at both ends (`dir=both`) to indicate that the signal path is bi-directional.
    -   A grouping selector must allow users to collapse diagram connections by Protocol or Cable Type; when collapsed, the port labels must show the grouping value (e.g., "dante") instead of individual port names so the diagram stays readable.
    -   The Cross-point tab must provide Source and Target asset tag inputs, a multi-select that controls which cable fields appear in the row/column headers (default Port + Usage), and a protocol dropdown containing only the protocols observed between those two assets. Entering a valid asset tag into either Source or Target must automatically convert the opposite control into a single-select dropdown of only the directly connected assets (based on direction), and a reset button or clearing the text input must restore both controls to standard text entries when needed.
    -   Changing any diagram option must immediately refresh both the cable table and the rendered diagram so the selected labels are reflected without extra button clicks.
-   **Output Display:**
    -   Results for asset search and cable filtering will be displayed in clear, readable tables. Column headers must be sort-able.
    -   Connectivity diagrams will be rendered interactively or as images within the UI. When grouping is enabled, multiple ports of the same Protocol/Type must collapse into a single connection that displays the grouping label and the number of collapsed cables, while keeping inbound/outbound sides distinct.
    -   The asset table must always expose a Select column; any checked assets must automatically be included alongside the typed target when loading the cable table and diagram, even if they have no current adjacency in the rendered graph.
    -   The Cross-point tab must render a matrix with Source ports for rows and Target ports for columns, highlighting each intersecting cell in green when a connection exists for the selected protocol and white otherwise.
    -   Below the connectivity diagram, four text tables must be displayed for the target device: Input Connections, Output Connections, Internal Routes, and Passthroughs. Input and Output tables list only external connections and include the target port, partner port (source for inputs, destination for outputs), protocol, cable ID, and the partner device's asset tag, manufacturer, model, and usage. The "partner" column header reads "Source" in the Input table and "Destination" in the Output table. Internal route rows — cables where `SrcTag` equals `DstTag` and `Type` contains `route` — must not appear in Inputs or Outputs and must appear only in the Internal Routes table (columns: Source Port, Destination Port, Protocol, Usage, Cable ID, Type). Passthrough rows — cables where `SrcTag` equals `DstTag` and `Type` contains `passthrough` — must not appear in Inputs, Outputs, or Internal Routes and must appear only in the Passthroughs table (same columns as Internal Routes). All columns in these tables must be sortable by clicking their headers. These tables must be included in the print view, with a page break inserted before each table. The frontend retrieves all four tables via a single combined endpoint (`/diagram/connections?target_tag=<tag>`) returning `{ inputs, outputs, internal_routes, passthroughs }`.
    -   **Asset Details Tab:**
        -   Provides an input field for an Asset Tag and a button to "View Details".
        -   Displays all fields from the asset table for the target device in a table-based layout with logical grouping:
            -   **Basic Information** (displayed as multiple tables):
                -   Row 1: Asset Tag, Type, Category, InService
                -   Row 2: Manufacturer, Model, SN
                -   Row 3: AcqYear, EOLYear, Usage, Desc
            -   **Location**: Building, Floor, Room, Sector, Location, Rack, RackU, RackHeight (single table spanning horizontally)
            -   **Financial**: Qty, Unit, AcqValue, PurchaseDate, PurcForm, Invoice, and any other fields not in Basic/Location/Disposition (single table spanning horizontally)
            -   **Disposition**: Disposition fields only displayed in a table format if Disposition is not "N"
        -   Below the property tables, sections render in this order: **Network**, **Installed Assets** (see below), **Input/Output Partners**, **Knowledge Base Issues**, **Manuals**, **Licenses**.
        -   Displays a **Network** table of NIC records for the asset (NIC, IP, MAC, Monitor, Type, Usage, Services, Notes), matching the data shown on the dedicated Network tab (see Section 8).
        -   **Installed Assets:** Assets of `Category` = `Software` record what they are installed on via their own `Location` field (holding the asset tag of the host). The host's own `Category` is **not** used to decide whether to show this section — host machines are commonly categorized by AV function (`Video`, `Audio`, etc.) rather than `Computer` (only 9 of several hundred assets in production actually carry `Category` = `Computer`), so gating on the host's category hides real installed-software relationships. Instead:
            -   An **Installed Software** table is shown whenever at least one `Category` = `Software` asset's `Location` matches this asset's tag — regardless of this asset's own `Category`. Columns: Asset Tag (clickable, navigates like a partner link), Manufacturer, Model, Description, and Usage. If nothing matches, the section is omitted entirely (no heading, no empty-state message) *unless* this asset is itself Software (see next point).
            -   If the subject asset's `Category` is `Software`, an additional **Installed On** table is always shown (even when empty, with an explanatory message) — the single asset (any category) referenced by this asset's own `Location` field — followed by **Software Installed On This Asset**, using the same matching/columns as Installed Software. This is necessary because software can be installed on other software (e.g. a runtime installed inside a container platform installed on a computer), so a software asset can appear as both the "installed" item in one table and the "host" in another.
            -   Backend: `GET /assets/{asset_tag}/details` includes `installed_software` (list) and `installed_on` (list, 0 or 1 entries) fields alongside the existing `asset`/`input_partners`/`output_partners`/`network`/`licenses` fields, computed the same way regardless of the asset's category — the frontend applies the display rule above.
        -   Shows a distinct list of all input partners (AssetTag, Manufacturer, Model, Usage). Each partner item must be clickable.
        -   Shows a distinct list of all output partners (AssetTag, Manufacturer, Model, Usage). Each partner item must be clickable.
        -   Clicking an input or output partner in the list should update both the Asset Details view and the Connectivity Diagram tab with the selected partner's AssetTag. The Asset Details tab remains active while the Connectivity Diagram is updated in the background, allowing users to seamlessly navigate through connected assets while keeping both views synchronized.
        -   Displays a table of all relevant issues from `data/knowledgebase.xlsx` where the target asset's tag is present in the `AppliesToAssetTag` column. This table should include `IssueID`, `Title`, `Category`, and `Subcategory`, and be sortable by column headers. The `IssueID` values are clickable and navigate to the Knowledge Base tab with the clicked issue automatically loaded.
    -   **Knowledge Base Tab:**
        -   Provides search controls for IssueID, Asset Tags, and freeform text search. Asset Tags must be presented as both a free-text input (single tag) and a multi-select dropdown populated with all unique asset tags associated with active knowledge base issues (rows where the `Active` column equals "Yes"). Selecting multiple tags from the dropdown must match issues associated with any of the selected tags (OR semantics). The free-text tag field and the multi-select are combined as a single OR tag filter group. All criterion groups (IssueID, tags, freeform) also combine with OR, so an issue matching any supplied criterion is returned.
        -   Pressing Enter in any text search field triggers the search, as does clicking the Search button.
        -   Freeform text search searches across all fields in the knowledge base, ignoring whitespace, case, and punctuation.
        -   The tag dropdown options are refreshed automatically after a successful data reload; previously selected values that still exist are preserved.
        -   Search results are sorted by Category, Subcategory, and SortOrder.
        -   Each issue is displayed as an expandable section showing the IssueID and Title when collapsed.
        -   When expanded, the issue displays all fields including Symptom, Trigger Conditions, Likely Cause, Recovery Steps, and other relevant information.
        -   Fields support markdown formatting for rich text display.
        -   If only one issue is found in the search results, it is automatically expanded.
        -   Clicking an IssueID in the Asset Details tab navigates to the Knowledge Base tab and automatically searches for and displays that issue.
        -   Asset tags listed in the "Applies to Asset Tag" field are clickable and behave the same as clicking asset tags elsewhere - they update both the Asset Details view and the Connectivity Diagram in the background, then switch to the Asset Details tab.
        -   Each expanded issue must display a `See Also` section after `Applies to Asset Tag` and before `Tags` when related issues exist. The section lists unique related issues by issue ID and title. Each entry is clickable and loads that issue in the Knowledge Base tab. Related-issue display is bidirectional: if issue A references issue B in `SeeAlso`, issue B also displays issue A even if the reverse is not explicitly in the source data. Unknown IDs are silently omitted.
    -   When printing from the browser, only the connectivity diagram should appear to produce clean hard copies.
    -   **Location Tab:**
        -   Provides an asset tag search field (defaulting to the current target asset) and a "View Location" button.
        -   Displays the most specific available floor plan image above the rack profile. Floor plan images are PNG files named `floorplan_<building>_<floor>_r<room>.png` (room-level), `floorplan_<building>_<floor>.png` (floor-level), or `floorplan_<building>.png` (building-level), where building and floor values are lowercased from the asset's Building and Floor fields. The backend resolves the best match in order from most to least specific; if no file exists for any level, no image is shown. The image label includes the Sector when present (e.g., "B1 / F2 / 202 / Sector 5").
        -   For an asset that resides in a rack, renders an SVG rack elevation profile showing all devices in that rack. The target asset is highlighted in amber; devices above the rack's standard height are highlighted in red. Devices are colored by face (front = blue, rear = green).
        -   Rack devices use RackU notation (e.g., `F23`, `R10`) supporting subdivision suffixes (e.g., `F30-5-4-4`) to place half/partial-width devices correctly.
        -   Clicking any device tile in the rack profile navigates to the Asset Details tab for that device.
        -   A "Print Rack" button triggers a print-mode view that isolates the rack profile for clean hard copy output.
        -   When the active asset changes (via Connectivity Diagram or Asset Details), the Location tab updates automatically in the background.
    -   **Signal Path Finder Tab:**
        -   Provides source and target asset tag inputs and a configurable max-hops limit (default 10).
        -   Uses breadth-first search over the cable graph to find the shortest directed cable path between two assets.
        -   Displays a summary (found/not found, hop count) and a detailed table of each hop (from, to, cable tag, type, protocol, source port, destination port).
    -   **Diagram Export:**
        -   "Export SVG" button downloads the current connectivity diagram as an SVG file named `diagram-<target>.svg`.
        -   "Export PNG" button renders the SVG to a canvas and downloads a PNG named `diagram-<target>.png`.
    -   **URL Hash State:**
        -   The current target asset tag is encoded in the browser URL hash (`#tag=<value>`) whenever a diagram is loaded, enabling bookmark and share links.
        -   On page load, if a `#tag=` hash is present, the diagram is automatically loaded for that tag.
        -   Browser back/forward navigation via the hash is supported.
## 3. Technology Stack

-   **Frontend:** HTML, CSS, JavaScript (lightweight, no heavy frameworks required unless specified).
-   **Backend:** Python with FastAPI.
-   **Data Processing:** Pandas library for handling Excel data.
-   **Diagramming:** Graphviz DOT language generated by backend, rendered by a suitable frontend library (e.g., Viz.js) or server-side.

## 4. Data Sources

-   `uac_assets.xlsx`: Contains asset inventory information. Key location fields: Building, Floor, Room, Sector, Location, Rack, RackU, RackHeight.
    -   **Sector**: Optional integer 1–16 representing position within a room divided into a 4×4 grid, numbered left-to-right then top-to-bottom (1 = NW corner, 4 = NE corner, 13 = SW corner, 16 = SE corner). Displayed alongside Building/Floor/Room throughout the application wherever location data appears.
-   `uac_cables.xlsx`: Contains cable connectivity details.
-   `uac_knowledgebase.xlsx`: Contains knowledge base issues linked to assets.
-   `glossary.xlsx`: AV terminology definitions. Sheet `glossary`, columns: Topic, Term, SeeAlso, Definition.

## 4a. Glossary API

-   **`GET /glossary`**: Returns all glossary entries as a JSON array. Each entry contains `topic`, `term`, `see_also`, and `definition` string fields. All string values have leading/trailing whitespace stripped.
    -   Optional query parameter `topic` (string): when supplied, returns only entries whose topic matches case-insensitively.
    -   An unknown `topic` value returns an empty list (not an error).
-   **`GET /glossary/topics`**: Returns `{ "topics": [...] }` — all unique, non-blank topic values sorted case-insensitively.

## 5. Deployment

-   The entire web application (frontend and backend) will reside in a subdirectory named `webapp` within the main project.
-   Backend will run on port `9000`.

## 6. Testing

-   Provide a test suite that exercises key back-end endpoints and reports clearly logged PASS/FAIL results so developers can diagnose regressions quickly.
-   Test suite needs to allow terminal-driven test exedcution (e.g., `python3 tests/run_tests.py`)

## 7. Current Known Issues / Bugs / TODOs

-   Some nodes support an in-bound and out-bound connection on the same port (for example Floor Boxes). The diagram currently only renders such ports twice but makes all connections to only one side. Put the inbound connection on the left side, and the out-bound on the right. (Or top and Bottom depnding on diagram orientation)

## 8. Network Tab

-   **Network Tab:** A dedicated "Network" tab provides two search modes and displays full NIC detail for any asset.
-   **Asset Tag Lookup:**
    -   An asset tag input field and Lookup button fetch and display the network records for that asset.
    -   Performing a lookup sets the global asset tag so other tabs update accordingly.
    -   Pressing Enter in the asset tag field triggers the lookup.
    -   When switching to the Network tab while a global asset tag is already set, the tab automatically loads that asset's network data.
    -   When `setGlobalTargetAsset` is called (from any tab) while the Network tab is active, the network details refresh automatically.
-   **IP / MAC Address Search:**
    -   A second input field accepts an IP address (partial or full) or a MAC address.
    -   Detection rules: if the query contains `.` it is treated as an IP address; if it contains `:` or `-` it is treated as a MAC address.
    -   MAC address matching normalises both the query and the database values to colon-separated lowercase before comparing, so inconsistent use of `:` vs `-` in the database does not affect results.
    -   IP matching is a substring search (partial octets accepted).
    -   Pressing Enter in the address field triggers the search.
    -   If exactly one asset matches, its full network details are displayed directly and the global asset tag is set.
    -   If multiple assets match, a summary table is shown listing asset tag, manufacturer, model, all IP addresses, and all MAC addresses for each asset. Clicking an asset tag in the table displays that asset's full network details and sets the global asset tag.
-   **Backend endpoint:** `GET /network/search?q={query}` implements the address search and returns a list of matching assets with `asset_tag`, `manufacturer`, `model`, `mac_addresses`, `ip_addresses`, and `nics` fields.

## 9. Pending Enhancements

-   Add support for multiple diagram layouts (e.g., hierarchical, radial) to improve readability for complex connectivity.
-   Provide a context menu on the individual diagram lines to hide. The node context menu should also provide a reshow option with a sublist of available lines that can be readded to the diagram.
-   Allow the input list to be a comma-separated list of asset tags to support. This would allow users to explore connectivity between multiple assets simultaneously without needing to perform separate queries for each one.
-   Some nodes have a large number of connections (e.g., the 2507-0700 has 20+ cables). The diagram can become cluttered and difficult to read. Implementing a more sophisticated layout algorithm or allowing users to selectively collapse/expand groups of connections would improve readability, collapsing should be done be grouping cables of the same type or protocol (to be implemented). When showing a collapsed group, replace the port labels with the grouping value. For example if the collapsed line represented the dante connections, show the labels as dante. Be sure to keep the inbound and outbound labels distinct.
-   Add a diagram option to layout the diagram top-to-bottom or left-to-right.
-   Add a new field to the cable data for "Protocol" (e.g., SDI, HDMI, Ethernet) and refactor the existing Type field to be specific about the cable type and not conflate it with the protocol. This would allow users to filter and label cables based on the protocol they carry, which is often more relevant for understanding connectivity than the physical cable type alone. For example, a cable could be labeled as "Type: Cat6, Protocol: Ethernet" to provide clearer information about its function in the system.
-   On the "Cable and Diagram Viewer" pane , change the cable type filter to a protocol filter and ensure it is case in-sensitive.
-   Add a hover text for the cables that displays the cableid.
-   Add context menu options for the nodes for hide-inbound, and hide-outbound.
-   Add a new tab called "Cross-point" This tab should have two entry fields, "Source" and "Target" which accept valid asset tags. The body of this tab should be a cross-point matrix with source ports as the rows, and target ports as the columns. There should be a drop-down multi-select list which determines which fields to show as the row and column headers, with the default being a concatenation of port and usage. There should be a selection box where the protocol type can be specified; the list should be populated with the subset of protocols that exists between Source and Target. Highlight the intersection cell in green if there is a connection, white otherwise.
-   The "Diagram Options" UI panel should be with the Diagram Tab, not global.
-   Add a select field to the Asset Table. The selected items from that table should all be included in the diagram and cable table views. This is in addition to what ever assets or cables are included via the text entry field
-   Add a column selection multi-select dropdown list to the "Asset Results" table. The selected columns will be the columns displayed in the table. The pre-selected defaults will be the asset Tag, Make, Manufacturer, Description and Usage. There is another enhancement for there to be a select checkbox, that should always be visible and usable.\
