const API_BASE_URL = (() => {
    const searchParams = new URLSearchParams(window.location.search);
    const paramValue = searchParams.get("apiBase") || searchParams.get("api");
    if (paramValue) return paramValue.replace(/\/$/, "");
    const meta = document.querySelector('meta[name="api-base-url"]');
    if (meta && meta.content) return meta.content.replace(/\/$/, "");
    if (window.API_BASE_URL) return String(window.API_BASE_URL).replace(/\/$/, "");
    return `http://${window.location.hostname}:9000`;
})();

const DEFAULT_NODE_FIELDS = ["tag", "manufacturer", "model", "usage"];
const DEFAULT_EDGE_FIELDS = ["tag", "type", "ports", "usage"];
const DEFAULT_CROSSPOINT_FIELDS = ["port", "usage"];
const ASSET_TABLE_DEFAULT_COLUMNS = ["AssetTag", "Model", "Manufacturer", "Desc", "Usage"];
const DIAGRAM_INPUT_CONNECTIONS_CONTAINER_ID = "diagramInputConnections";
const DIAGRAM_OUTPUT_CONNECTIONS_CONTAINER_ID = "diagramOutputConnections";
const DIAGRAM_INTERNAL_ROUTES_CONTAINER_ID = "diagramInternalRoutes";
const DIAGRAM_PASSTHROUGHS_CONTAINER_ID = "diagramPassthroughs";

// Asset Details Tab Constants
const ASSET_DETAILS_TAB_ID = "assetDetails";
const ASSET_DETAILS_INPUT_ID = "assetDetailsTagInput";
const ASSET_DETAILS_VIEW_BUTTON_ID = "viewAssetDetailsBtn";
const ASSET_DETAILS_CONTAINER_ID = "assetDetailsContainer";
const ASSET_PROPERTIES_CONTAINER_ID = "assetProperties";
const INPUT_PARTNERS_LIST_ID = "inputPartnersList";
const OUTPUT_PARTNERS_LIST_ID = "outputPartnersList";
const KNOWLEDGE_BASE_ISSUES_TABLE_ID = "knowledgeBaseIssuesTable";
const ASSET_MANUALS_CONTAINER_ID = "assetManualsContainer";
const ASSET_LICENSES_CONTAINER_ID = "assetLicensesContainer";

const FALLBACK_FIELD_LABELS = {
    tag: "Tag",
    manufacturer: "Manufacturer",
    model: "Model",
    usage: "Usage",
    type: "Type",
    ports: "In-Port → Out-Port",
    port: "Port",
    protocol: "Protocol",
    notes: "Notes",
    AssetTag: "Asset Tag",
    Desc: "Description",
    TargetPort: "Target Port",
    SourcePort: "Source Port",
    DestinationPort: "Destination Port",
    CableID: "Cable ID",
    PartnerAssetTag: "Partner Asset Tag",
    PartnerManufacturer: "Partner Manufacturer",
    PartnerModel: "Partner Model",
    PartnerUsage: "Partner Usage"
};
let nodeFieldDefaults = [...DEFAULT_NODE_FIELDS];
let edgeFieldDefaults = [...DEFAULT_EDGE_FIELDS];
let crosspointHeaderDefaults = [...DEFAULT_CROSSPOINT_FIELDS];
let assetColumnDefaults = [...ASSET_TABLE_DEFAULT_COLUMNS];
let assetTableData = [];
let _assetSearchExtraParams = {};

// Store sort state for tables
const tableSortStates = {
    assetResults: {
        column: null,
        direction: 'asc' // 'asc' or 'desc'
    },
    cableResults: {
        column: null,
        direction: 'asc'
    },
    [DIAGRAM_INPUT_CONNECTIONS_CONTAINER_ID]: {
        column: null,
        direction: 'asc'
    },
    [DIAGRAM_OUTPUT_CONNECTIONS_CONTAINER_ID]: {
        column: null,
        direction: 'asc'
    },
    [DIAGRAM_INTERNAL_ROUTES_CONTAINER_ID]: {
        column: null,
        direction: 'asc'
    },
    [DIAGRAM_PASSTHROUGHS_CONTAINER_ID]: {
        column: null,
        direction: 'asc'
    },
    knowledgeBaseIssuesTable: {
        column: null,
        direction: 'asc'
    },
    klangVariances: {
        column: "mix",
        direction: 'asc'
    }
};

// Global target asset — set when any asset tag is clicked anywhere in the UI
let globalTargetAsset = null;

// Store active asset tags for diagram filtering
let activeDiagramAssetTags = [];
let availableDiagramAssetTags = [];
const hiddenNodes = new Set();
const hiddenCables = new Set(); // Cable IDs hidden by route-traversal filtering
const allKnownDiagramAssetTags = new Set();
const adjacencyOutMap = new Map();
const adjacencyInMap = new Map();
const expansionResultLog = new Map(); // node+direction -> includesNewNodes boolean
// Records each hidden node's neighbors (both in and out) at the moment it was
// hidden, while the adjacency maps are still complete. This is the only reliable
// source for re-exposing hidden nodes, because subsequent fetches may drop a
// hidden node's cables from the adjacency maps entirely.
const hiddenNodeNeighbors = new Map(); // hiddenTag -> Set of neighbor tags
const selectedAssetTags = new Set();
let currentDiagramCableData = []; // Cables currently shown in the diagram

function showLoadingSpinner(container, message = "Loading…") {
    if (!container) return;
    container.innerHTML = `<div class="loading-spinner">${message}</div>`;
}

function showEmptyState(container, message = "No results found.", icon = "📭") {
    if (!container) return;
    container.innerHTML = `<div class="empty-state"><span class="empty-state-icon">${icon}</span>${message}</div>`;
}

document.addEventListener("DOMContentLoaded", () => {
    console.log("DOMContentLoaded event fired."); // Added log
    // --- Tab Switching Logic ---
    const tabButtons = document.querySelectorAll(".tab-button");
    const tabContents = document.querySelectorAll(".tab-content");

    tabButtons.forEach(button => {
        button.addEventListener("click", () => {
            tabButtons.forEach(btn => btn.classList.remove("active"));
            tabContents.forEach(content => content.classList.remove("active"));

            button.classList.add("active");
            document.getElementById(button.dataset.tab).classList.add("active");

            if (button.dataset.tab === "crosspointViewer" && globalTargetAsset) {
                if (crosspointSourceInput && !crosspointSourceInput.value.trim()) {
                    crosspointSourceInput.value = globalTargetAsset;
                    handleAssetInputChange("source", globalTargetAsset);
                }
            }

            if (button.dataset.tab === "networkViewer" && globalTargetAsset) {
                fetchAndRenderNetworkDetails(globalTargetAsset);
            }
        });
    });

    // --- Asset Search Logic ---
    const assetTagSearch = document.getElementById("assetTagSearch");
    const manufacturerSearch = document.getElementById("manufacturerSearch");
    const modelSearch = document.getElementById("modelSearch");
    const inServiceOnlyCheckbox = document.getElementById("inServiceOnlyCheckbox");
    const assetColumnSelect = document.getElementById("assetColumnSelect");
    const searchAssetsBtn = document.getElementById("searchAssetsBtn");
    const assetTableContainer = document.getElementById("assetTableContainer");

    const performAssetSearch = async () => {
        const params = new URLSearchParams();
        if (assetTagSearch.value) params.append("asset_tag", assetTagSearch.value);
        if (manufacturerSearch.value) params.append("manufacturer", manufacturerSearch.value);
        if (modelSearch.value) params.append("model", modelSearch.value);
        const inServiceValue = inServiceOnlyCheckbox ? inServiceOnlyCheckbox.checked : true;
        params.append("in_service_only", inServiceValue.toString());
        for (const [key, val] of Object.entries(_assetSearchExtraParams)) {
            if (val !== undefined && val !== null && val !== "") params.append(key, val);
        }
        _assetSearchExtraParams = {};

        showLoadingSpinner(assetTableContainer, "Searching assets…");
        document.querySelector('.tab-button[data-tab="assetResults"]').click();

        try {
            const response = await fetch(`${API_BASE_URL}/assets/search?${params.toString()}`);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const data = await response.json();
            assetTableData = Array.isArray(data) ? data : [];
            renderAssetTable();
        } catch (error) {
            console.error("Error fetching assets:", error);
            assetTableContainer.innerHTML = `<div class="empty-state"><span class="empty-state-icon">⚠️</span>Error loading assets: ${error.message}</div>`;
        }
    };

    searchAssetsBtn.addEventListener("click", performAssetSearch);

    // Add Enter key support for asset search inputs
    [assetTagSearch, manufacturerSearch, modelSearch].forEach(input => {
        input.addEventListener("keypress", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                performAssetSearch();
            }
        });
    });

    function navigateToAssetSearch(params) {
        assetTagSearch.value = params.asset_tag || "";
        manufacturerSearch.value = params.manufacturer || "";
        modelSearch.value = params.model || "";
        if (inServiceOnlyCheckbox && "in_service_only" in params) {
            inServiceOnlyCheckbox.checked = params.in_service_only;
        }
        const knownInputs = new Set(["asset_tag", "manufacturer", "model", "in_service_only"]);
        _assetSearchExtraParams = {};
        for (const [key, val] of Object.entries(params)) {
            if (!knownInputs.has(key)) _assetSearchExtraParams[key] = val;
        }
        performAssetSearch();
    }

    // --- Cable and Diagram Viewer Logic ---
    const targetTagFilter = document.getElementById("targetTagFilter");
    const directionFilter = document.getElementById("directionFilter");
    const cableTypeFilter = document.getElementById("cableTypeFilter");
    const protocolFilter = document.getElementById("protocolFilter");
    const viewDiagramBtn = document.getElementById("viewDiagramBtn");
    const reloadDataBtn = document.getElementById("reloadDataBtn");
    const reloadStatus = document.getElementById("reloadStatus");
    const cableTableContainer = document.getElementById("cableTableContainer");
    const diagramRenderArea = document.getElementById("diagramRenderArea");
    const nodeContextMenu = document.getElementById("nodeContextMenu");
    const diagramStatus = document.getElementById("diagramStatus");
    const nodeFieldsSelect = document.getElementById("nodeFieldsSelect");
    const edgeFieldsSelect = document.getElementById("edgeFieldsSelect");
    const crosspointHeaderFields = document.getElementById("crosspointHeaderFields");
    const crosspointProtocolSelect = document.getElementById("crosspointProtocolSelect");
    const crosspointSourceInput = document.getElementById("crosspointSource");
    const crosspointTargetInput = document.getElementById("crosspointTarget");
    const crosspointSourceSelect = document.getElementById("crosspointSourceSelect");
    const crosspointTargetSelect = document.getElementById("crosspointTargetSelect");
    const viewCrosspointBtn = document.getElementById("viewCrosspointBtn");
    const resetCrosspointBtn = document.getElementById("resetCrosspointBtn");
    const crosspointMatrixContainer = document.getElementById("crosspointMatrixContainer");
    const crosspointStatus = document.getElementById("crosspointStatus");
    const colorNodesCheckbox = document.getElementById("colorNodesByCategory");
    const colorEdgesCheckbox = document.getElementById("colorEdgesByProtocol");
    const collapseStrategySelect = document.getElementById("collapseStrategySelect");
    const excludeInternalRoutesCheckbox = document.getElementById("excludeInternalRoutes");
    const includePhysicalRoutesCheckbox  = document.getElementById("includePhysicalRoutes");
    const includeLogicalRoutesCheckbox   = document.getElementById("includeLogicalRoutes");
    const includePassthroughsCheckbox    = document.getElementById("includePassthroughs");

    // Asset Details tab elements
    const assetDetailsTagInput = document.getElementById(ASSET_DETAILS_INPUT_ID);
    const viewAssetDetailsBtn = document.getElementById(ASSET_DETAILS_VIEW_BUTTON_ID);
    const assetPropertiesContainer = document.getElementById(ASSET_PROPERTIES_CONTAINER_ID);
    const inputPartnersList = document.getElementById(INPUT_PARTNERS_LIST_ID);
    const outputPartnersList = document.getElementById(OUTPUT_PARTNERS_LIST_ID);
    const knowledgeBaseIssuesTableContainer = document.getElementById(KNOWLEDGE_BASE_ISSUES_TABLE_ID);

    const performViewAssetDetails = async () => {
        const targetAssetTag = assetDetailsTagInput.value.trim();
        if (!targetAssetTag) {
            alert("Please enter an Asset Tag to view details.");
            return;
        }
        await fetchAndRenderAssetDetails(targetAssetTag);
    };

    viewAssetDetailsBtn.addEventListener("click", performViewAssetDetails);

    // Add Enter key support for asset details input
    if (assetDetailsTagInput) {
        assetDetailsTagInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                performViewAssetDetails();
            }
        });
    }

    // Knowledge Base tab elements
    const kbIssueIdSearch = document.getElementById("kbIssueIdSearch");
    const kbTagSearch = document.getElementById("kbTagSearch");
    const kbActiveIssueTags = document.getElementById("kbActiveIssueTags");
    const kbFreeformSearch = document.getElementById("kbFreeformSearch");
    const searchKnowledgeBaseBtn = document.getElementById("searchKnowledgeBaseBtn");
    const kbResultsContainer = document.getElementById("kbResultsContainer");

    async function loadKBTagOptions() {
        if (!kbActiveIssueTags) return;
        const prevSelected = new Set(
            Array.from(kbActiveIssueTags.selectedOptions).map(o => o.value)
        );
        try {
            const resp = await fetch(`${API_BASE_URL}/knowledgebase/tags`);
            if (!resp.ok) return;
            const data = await resp.json();
            kbActiveIssueTags.innerHTML = '';
            (data.tags || []).forEach(opt => {
                const el = document.createElement("option");
                el.value = opt.value;
                el.textContent = opt.label;
                if (prevSelected.has(opt.value)) el.selected = true;
                kbActiveIssueTags.appendChild(el);
            });
        } catch (e) {
            console.error("Error loading KB tag options:", e);
        }
    }

    loadKBTagOptions();

    const performKBSearch = async () => {
        const issueId = kbIssueIdSearch.value.trim();
        const tag = kbTagSearch.value.trim();
        const freeform = kbFreeformSearch.value.trim();
        const selectedTags = kbActiveIssueTags
            ? Array.from(kbActiveIssueTags.selectedOptions).map(o => o.value)
            : [];

        if (!issueId && !tag && !freeform && selectedTags.length === 0) {
            alert("Please enter at least one search criterion.");
            return;
        }

        const params = new URLSearchParams();
        if (issueId) params.append("issue_id", issueId);
        if (tag) params.append("tag", tag);
        selectedTags.forEach(t => params.append("tag", t));
        if (freeform) params.append("freeform", freeform);

        showLoadingSpinner(kbResultsContainer, "Searching knowledge base…");

        try {
            const response = await fetch(`${API_BASE_URL}/knowledgebase/search?${params.toString()}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            const issues = await response.json();
            renderKBResults(issues);
        } catch (error) {
            console.error("Error fetching knowledge base results:", error);
            showEmptyState(kbResultsContainer, `Error: ${error.message}`, "⚠️");
        }
    };

    searchKnowledgeBaseBtn.addEventListener("click", performKBSearch);

    // Enter key support for text inputs (multi-select uses native selection, no auto-submit)
    [kbIssueIdSearch, kbTagSearch, kbFreeformSearch].forEach(input => {
        if (input) {
            input.addEventListener("keypress", (e) => {
                if (e.key === "Enter") {
                    e.preventDefault();
                    performKBSearch();
                }
            });
        }
    });

    function setCrosspointInputValue(side, value) {
        const input = side === "source" ? crosspointSourceInput : crosspointTargetInput;
        const select = side === "source" ? crosspointSourceSelect : crosspointTargetSelect;
        if (input) {
            input.value = value;
        }
        if (select && !select.classList.contains("hidden")) {
            select.value = value;
        }
    }

    function setCrosspointControlMode(side, mode, optionsList) {
        const input = side === "source" ? crosspointSourceInput : crosspointTargetInput;
        const select = side === "source" ? crosspointSourceSelect : crosspointTargetSelect;
        if (!input || !select) return;
        if (mode === "select" && (assetTagOptions.length || (optionsList && optionsList.length))) {
            populateAssetSelect(select, side === "source" ? "Select Source Asset" : "Select Target Asset", optionsList);
            const resolved = resolveAssetDisplay(input.value);
            if (resolved) {
                select.value = resolved;
            } else {
                select.value = "";
            }
            input.classList.add("hidden");
            select.classList.remove("hidden");
        } else {
            input.classList.remove("hidden");
            select.classList.add("hidden");
        }
    }

    function resetCrosspointInputs(clearValues = false) {
        setCrosspointControlMode("source", "text");
        setCrosspointControlMode("target", "text");
        if (crosspointSourceSelect) {
            populateAssetSelect(crosspointSourceSelect, "Select Source Asset");
            crosspointSourceSelect.value = "";
        }
        if (crosspointTargetSelect) {
            populateAssetSelect(crosspointTargetSelect, "Select Target Asset");
            crosspointTargetSelect.value = "";
        }
        if (clearValues) {
            if (crosspointSourceInput) crosspointSourceInput.value = "";
            if (crosspointTargetInput) crosspointTargetInput.value = "";
            lastCrosspointQuery = null;
        }
    }

    function getCrosspointValue(side) {
        const input = side === "source" ? crosspointSourceInput : crosspointTargetInput;
        const select = side === "source" ? crosspointSourceSelect : crosspointTargetSelect;
        if (select && !select.classList.contains("hidden") && select.value) {
            return select.value.trim();
        }
        return input ? input.value.trim() : "";
    }

    function setCrosspointStatus(message, level = "info") {
        if (!crosspointStatus) return;
        if (!message) {
            crosspointStatus.textContent = "";
            crosspointStatus.className = "status-message hidden";
            return;
        }
        const levelClass = {
            info: "status-info",
            success: "status-success",
            warn: "status-warn",
            error: "status-error"
        }[level] || "status-info";
        crosspointStatus.className = `status-message ${levelClass}`;
        crosspointStatus.textContent = message;
    }

    function populateCrosspointProtocolOptions(options, selectedValue) {
        if (!crosspointProtocolSelect) {
            return;
        }
        const fallbackOptions = options && options.length ? options : [{ value: "", label: "All Protocols" }];
        crosspointProtocolSelect.innerHTML = "";
        fallbackOptions.forEach(option => {
            const opt = document.createElement("option");
            opt.value = option.value ?? "";
            opt.textContent = option.label || option.value || "All Protocols";
            crosspointProtocolSelect.appendChild(opt);
        });
        if (selectedValue) {
            crosspointProtocolSelect.value = selectedValue;
        } else {
            crosspointProtocolSelect.selectedIndex = 0;
        }
    }

    function renderCrosspointMatrix(data) {
        if (!crosspointMatrixContainer) {
            return;
        }
        const rows = Array.isArray(data?.rows) ? data.rows : [];
        const columns = Array.isArray(data?.columns) ? data.columns : [];
        const matrix = Array.isArray(data?.matrix) ? data.matrix : [];
        if (!rows.length || !columns.length) {
            crosspointMatrixContainer.innerHTML = "<p>No connections found between the selected assets.</p>";
            return;
        }
        const table = document.createElement("table");
        table.className = "crosspoint-table";
        const thead = document.createElement("thead");
        const headerRow = document.createElement("tr");
        const cornerCell = document.createElement("th");
        cornerCell.className = "row-header";
        cornerCell.textContent = `${data?.source_tag || "Source"} → ${data?.target_tag || "Target"}`;
        headerRow.appendChild(cornerCell);
        columns.forEach(col => {
            const th = document.createElement("th");
            th.textContent = col.label || col.port || "";
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = document.createElement("tbody");
        rows.forEach((row, rowIndex) => {
            const tr = document.createElement("tr");
            const rowHeader = document.createElement("td");
            rowHeader.className = "row-header";
            rowHeader.textContent = row.label || row.port || "";
            tr.appendChild(rowHeader);
            columns.forEach((col, colIndex) => {
                const td = document.createElement("td");
                const hasConnection = Boolean(matrix[rowIndex]?.[colIndex]);
                td.className = `crosspoint-cell ${hasConnection ? "has-connection" : "no-connection"}`;
                td.textContent = hasConnection ? "✔" : "";
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        crosspointMatrixContainer.innerHTML = "";
        crosspointMatrixContainer.appendChild(table);
    }

    function normalizeAssetTagValue(value) {
        if (!value) return "";
        return String(value).trim();
    }

    function getSelectedAssetColumns() {
        const columns = getSelectedOptions(assetColumnSelect, assetColumnDefaults);
        const baseColumns = columns.length ? columns : [...assetColumnDefaults];
        const set = new Set(baseColumns);
        set.add("AssetTag");
        return Array.from(set);
    }

    function renderAssetTable() {
        if (!assetTableContainer) return;
        if (!assetTableData || assetTableData.length === 0) {
            showEmptyState(assetTableContainer, "No assets matched your search.", "🔍");
            return;
        }

        const columnsToShow = getSelectedAssetColumns();
        const currentSortState = tableSortStates.assetResults;
        const sortedData = [...assetTableData];
        if (currentSortState.column) {
            sortedData.sort((a, b) => {
                const valA = a[currentSortState.column] ?? "";
                const valB = b[currentSortState.column] ?? "";
                let comparison = 0;
                if (valA > valB) comparison = 1;
                else if (valA < valB) comparison = -1;
                return currentSortState.direction === 'desc' ? comparison * -1 : comparison;
            });
        }

        const table = document.createElement("table");
        const thead = document.createElement("thead");
        const headerRow = document.createElement("tr");

        const selectHeader = document.createElement("th");
        selectHeader.textContent = "Select";
        const selectAllCheckbox = document.createElement("input");
        selectAllCheckbox.type = "checkbox";
        const selectableRows = sortedData.filter(row => normalizeAssetTagValue(row.AssetTag));
        const allVisibleSelected = selectableRows.length > 0 && selectableRows.every(row => selectedAssetTags.has(normalizeAssetTagValue(row.AssetTag)));
        const someVisibleSelected = selectableRows.some(row => selectedAssetTags.has(normalizeAssetTagValue(row.AssetTag)));
        selectAllCheckbox.checked = allVisibleSelected;
        selectAllCheckbox.indeterminate = !allVisibleSelected && someVisibleSelected;
        selectAllCheckbox.addEventListener("change", () => handleSelectAllAssets(selectAllCheckbox.checked, selectableRows));
        selectHeader.appendChild(selectAllCheckbox);
        headerRow.appendChild(selectHeader);

        columnsToShow.forEach(column => {
            const th = document.createElement("th");
            th.textContent = humanizeFieldLabel(column) || column;
            th.dataset.column = column;
            th.classList.add('sortable');
            headerRow.appendChild(th);
        });
        const actionsHeader = document.createElement("th");
        actionsHeader.textContent = "Actions";
        headerRow.appendChild(actionsHeader);
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = document.createElement("tbody");
        sortedData.forEach(rowData => {
            const assetTagValue = normalizeAssetTagValue(rowData.AssetTag);
            const tr = document.createElement("tr");
            const checkboxCell = document.createElement("td");
            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.disabled = !assetTagValue;
            checkbox.checked = assetTagValue ? selectedAssetTags.has(assetTagValue) : false;
            checkbox.addEventListener("change", () => handleAssetCheckboxChange(assetTagValue, checkbox.checked));
            checkboxCell.appendChild(checkbox);
            tr.appendChild(checkboxCell);

            columnsToShow.forEach(column => {
                const td = document.createElement("td");
                td.textContent = rowData[column] ?? "";

                // Make AssetTag column clickable
                if (column === "AssetTag" && assetTagValue) {
                    td.style.cursor = "pointer";
                    td.style.color = "#0066cc";
                    td.style.textDecoration = "underline";
                    td.addEventListener("click", () => {
                        setGlobalTargetAsset(assetTagValue);
                        document.querySelector('.tab-button[data-tab="assetDetails"]').click();
                    });
                }

                tr.appendChild(td);
            });

            // Actions column
            const actionsTd = document.createElement("td");
            const hasRack = assetTagValue && rowData.Rack && String(rowData.Rack).trim() !== "" && String(rowData.Rack).trim().toUpperCase() !== "NAN";
            if (hasRack) {
                const rackBtn = document.createElement("button");
                rackBtn.textContent = "View in Rack";
                rackBtn.className = "action-link-btn";
                rackBtn.addEventListener("click", () => {
                    document.querySelector('.tab-button[data-tab="locationViewer"]').click();
                    fetchAndRenderRackProfile(assetTagValue).catch(e => console.error("rack profile error:", e));
                });
                actionsTd.appendChild(rackBtn);
            }
            tr.appendChild(actionsTd);

            tbody.appendChild(tr);
        });
        table.appendChild(tbody);

        assetTableContainer.innerHTML = "";
        assetTableContainer.appendChild(table);

        headerRow.querySelectorAll("th.sortable").forEach(header => {
            header.addEventListener("click", () => {
                const column = header.dataset.column;
                let direction = 'asc';
                if (tableSortStates.assetResults.column === column && tableSortStates.assetResults.direction === 'asc') {
                    direction = 'desc';
                }
                tableSortStates.assetResults = { column, direction };
                renderAssetTable();
            });
        });
    }

    function handleAssetCheckboxChange(tag, checked) {
        const normalized = normalizeAssetTagValue(tag);
        if (!normalized) return;
        if (checked) {
            selectedAssetTags.add(normalized);
        } else {
            selectedAssetTags.delete(normalized);
        }
        renderAssetTable();
    }

    function handleSelectAllAssets(checked, rows) {
        rows.forEach(row => {
            const tag = normalizeAssetTagValue(row.AssetTag);
            if (!tag) return;
            if (checked) {
                selectedAssetTags.add(tag);
            } else {
                selectedAssetTags.delete(tag);
            }
        });
        renderAssetTable();
    }

    async function fetchConnectedAssetTags(tag, direction) {
        const params = new URLSearchParams();
        params.append("tag", tag);
        params.append("direction", direction);
        const response = await fetch(`${API_BASE_URL}/assets/linked?${params.toString()}`);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP ${response.status}`);
        }
        const data = await response.json();
        const peers = Array.isArray(data?.peers) ? data.peers : [];
        return {
            peers,
            canonicalTag: data?.tag || "",
        };
    }

    async function updateOppositeOptions(side, tagValue) {
        const otherSide = side === "source" ? "target" : "source";
        const direction = side === "source" ? "outbound" : "inbound";
        const result = await fetchConnectedAssetTags(tagValue, direction);
        if (result.canonicalTag) {
            setCrosspointInputValue(side, result.canonicalTag);
        }
        if (result.peers.length) {
            setCrosspointControlMode(otherSide, "select", result.peers);
        } else {
            setCrosspointControlMode(otherSide, "text");
        }
    }

    initializeDiagramFieldSelects();
    const assetTagsReadyPromise = initializeAssetTagSelects();
    initializeAssetColumnSelect();

    const refreshDiagramAfterOptionChange = () => {
        if (!(currentFilters.targetTag || currentFilters.cableId)) {
            return;
        }
        fetchAndRenderDiagramAndCables(
            currentFilters.targetTag,
            currentFilters.direction,
            currentFilters.cableType,
            currentFilters.protocol,
            currentFilters.cableId
        ).catch(error => {
            console.error("Error refreshing diagram after field change:", error);
        });
    };

    if (nodeFieldsSelect) {
        nodeFieldsSelect.addEventListener("change", refreshDiagramAfterOptionChange);
    }
    if (edgeFieldsSelect) {
        edgeFieldsSelect.addEventListener("change", refreshDiagramAfterOptionChange);
    }
    if (colorNodesCheckbox) {
        colorNodesCheckbox.addEventListener("change", refreshDiagramAfterOptionChange);
    }
    if (colorEdgesCheckbox) {
        colorEdgesCheckbox.addEventListener("change", refreshDiagramAfterOptionChange);
    }
    if (collapseStrategySelect) {
        collapseStrategySelect.addEventListener("change", refreshDiagramAfterOptionChange);
    }
    if (excludeInternalRoutesCheckbox) {
        excludeInternalRoutesCheckbox.addEventListener("change", refreshDiagramAfterOptionChange);
    }
    if (assetColumnSelect) {
        assetColumnSelect.addEventListener("change", () => renderAssetTable());
    }

    let baseTargetTag = "";
    let contextMenuTargetTag = null;
    let currentFilters = { targetTag: "", cableId: "", direction: "both", cableType: "", protocol: "" };
    const nodeExpansionMap = new Map(); // tag -> Set('in','out')
    let lastCrosspointQuery = null;
    let assetTagOptions = [];
    const assetTagLookup = new Map();


    const performDiagramView = async () => {
        console.log("View Diagram & Cables button clicked.");
        const targetInputValue = targetTagFilter.value.trim();

        if (!targetInputValue) {
            alert("Please enter a Target Asset Tag or Cable ID.");
            return;
        }

        const targetTag = targetInputValue;
        const cableId = "";

        baseTargetTag = targetInputValue;
        updateUrlHash(targetInputValue);
        hiddenNodes.clear();
        hiddenCables.clear();
        hiddenNodeNeighbors.clear();
        allKnownDiagramAssetTags.clear();
        expansionResultLog.clear();

        currentFilters = {
            targetTag: targetTag,
            cableId: cableId, // Pass the identified cable ID
            direction: directionFilter.value,
            cableType: cableTypeFilter.value,
            protocol: protocolFilter ? protocolFilter.value.trim() : ""
        };

        initializeExpansionMap(baseTargetTag, currentFilters.direction);

        await fetchAndRenderDiagramAndCables(
            currentFilters.targetTag,
            currentFilters.direction,
            currentFilters.cableType,
            currentFilters.protocol,
            currentFilters.cableId, // Pass cableId as a new argument
            true // reset active assets on a fresh request
        );

        // Switch to diagram tab after loading (user explicitly requested to view it)
        document.querySelector('.tab-button[data-tab="diagramViewer"]').click();
    };

    viewDiagramBtn.addEventListener("click", performDiagramView);

    // --- Diagram Export ---
    const exportSvgBtn = document.getElementById("exportSvgBtn");
    const exportPngBtn = document.getElementById("exportPngBtn");

    // ── Cytoscape instance ────────────────────────────────────────────────────
    let cyInstance = null;

    function destroyCy() {
        if (cyInstance) { cyInstance.destroy(); cyInstance = null; }
    }

    function buildCytoscapeStyle() {
        return [
            // Non-junction asset nodes: opaque background + high z-index so edges
            // passing through or behind the node are always hidden beneath it.
            {
                selector: 'node[!is_junction][!is_phantom]',
                style: {
                    'shape': 'rectangle',
                    'background-color': 'data(bg_color)',
                    'background-opacity': 1,
                    'z-index': 10,
                    'label': '',
                    'width': 'data(node_width)',
                    'height': 'data(node_height)',
                    'border-width': 1.5,
                    'border-color': '#0052cc',
                    'padding': '0px',
                    'cursor': 'pointer',
                }
            },
            {
                selector: 'node[!is_junction][!is_phantom]:selected',
                style: {
                    'border-width': 3,
                    'border-color': '#0040aa',
                    'border-style': 'dashed',
                }
            },
            // Junction splice dots
            {
                selector: 'node[?is_junction]',
                style: {
                    'shape': 'ellipse',
                    'width': 12,
                    'height': 12,
                    'background-color': '#555',
                    'label': '',
                    'border-width': 0,
                    'padding': '0px',
                }
            },
            // Invisible waypoint nodes used to route back-edges around node boundaries.
            // Use 1x1 (not 0x0) so Cytoscape can compute valid edge-boundary intersections.
            {
                selector: 'node[?is_phantom]',
                style: {
                    'width': 1,
                    'height': 1,
                    'border-width': 0,
                    'background-opacity': 0,
                    'label': '',
                    'padding': '0px',
                    'z-index': 1,
                    'events': 'no',
                }
            },
            {
                selector: 'edge',
                style: {
                    'width': 2,
                    'line-color': 'data(color)',
                    'target-arrow-color': 'data(color)',
                    'target-arrow-shape': 'triangle',
                    'source-arrow-color': 'data(color)',
                    'source-arrow-shape': 'none',
                    'curve-style': 'straight',
                    'z-index': 0,
                    'label': 'data(label)',
                    'font-size': '9px',
                    'font-family': '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                    'color': '#333',
                    'text-rotation': 'autorotate',
                    'text-margin-y': -8,
                    'text-wrap': 'ellipsis',
                    'text-max-width': '200px',
                    'text-background-color': '#fff',
                    'text-background-opacity': 0.85,
                    'text-background-padding': '2px',
                }
            },
            {
                selector: 'edge[?bidirectional]',
                style: { 'source-arrow-shape': 'triangle' }
            },
        ];
    }

    // Build the HTML content for a non-junction node's overlay
    function buildNodeHtml(data) {
        const esc = s => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        const inPorts  = data.in_ports  || [];
        const outPorts = data.out_ports || [];
        const hasPorts = inPorts.length > 0 || outPorts.length > 0;
        const fields   = data.fields    || {};
        const tag      = data.display_tag || data.id;

        const inHtml = inPorts.map(p =>
            `<div class="cy-port cy-port-in">${esc(p)}</div>`).join('');
        const outHtml = outPorts.map(p =>
            `<div class="cy-port cy-port-out">${esc(p)}</div>`).join('');

        // Center column: tag (bold) + remaining fields
        const fieldKeys = Object.keys(fields);
        const tagVal    = fields['tag'] || tag;
        const otherVals = fieldKeys.filter(k => k !== 'tag').map(k => fields[k]).filter(Boolean);
        const centerHtml = `<div class="cy-node-tag">${esc(tagVal)}</div>`
            + otherVals.map(v => `<div class="cy-node-field">${esc(v)}</div>`).join('');

        return `<div class="cy-node-html" style="width:${data.node_width}px;height:${data.node_height}px;background:${esc(data.bg_color)};">`
            + (hasPorts ? `<div class="cy-port-col cy-in-col">${inHtml}</div>` : '')
            + `<div class="cy-center-col">${centerHtml}</div>`
            + (hasPorts ? `<div class="cy-port-col cy-out-col">${outHtml}</div>` : '')
            + '</div>';
    }

    function renderCytoscape(graphData) {
        destroyCy();
        diagramRenderArea.innerHTML = '';

        if (!graphData || (!graphData.nodes.length && !graphData.edges.length)) {
            diagramRenderArea.innerHTML = '<p style="padding:16px;color:#666;">No assets found to display.</p>';
            return;
        }

        cyInstance = cytoscape({
            container: diagramRenderArea,
            elements: {
                nodes: graphData.nodes,
                edges: graphData.edges,
            },
            style: buildCytoscapeStyle(),
            layout: {
                name: 'elk',
                animate: false,
                elk: {
                    algorithm: 'layered',
                    'elk.direction': 'RIGHT',
                    'elk.layered.spacing.nodeNodeBetweenLayers': '260',
                    'elk.spacing.nodeNode': '60',
                    // Crossing minimisation: LAYER_SWEEP with TWO_SIDED greedy switching
                    // is the most thorough option short of an ILP solver.
                    'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
                    'elk.layered.crossingMinimization.greedySwitchType': 'TWO_SIDED',
                    // thoroughness controls the number of optimisation passes across all
                    // Sugiyama phases. Default is 7; 25 gives noticeably better results
                    // on mid-sized graphs at the cost of a slightly longer layout time.
                    'elk.thoroughness': '25',
                    // NETWORK_SIMPLEX minimises dummy nodes / edge length (better layer
                    // assignment leads to fewer crossings downstream).
                    'elk.layered.layering.strategy': 'NETWORK_SIMPLEX',
                    // BRANDES_KOEPF with BALANCED alignment centres nodes on their
                    // neighbours, reducing visual zig-zag.
                    'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
                    'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
                },
            },
            minZoom: 0.1,
            maxZoom: 4,
            wheelSensitivity: 0.3,
        });

        // After ELK layout: register HTML overlays and snap edge endpoints to ports.
        // ELK provides bend-point waypoints (obstacle avoidance) but Cytoscape still
        // calculates start/end attachment via its own boundary intersection. We override
        // those attachment points using the exact port x/y coordinates from node data,
        // which were computed in the backend to match the HTML overlay port row positions.
        cyInstance.one('layoutstop', function () {
            // Reorder out_ports / in_ports on each real node so that ports whose
            // edges connect to higher targets (smaller Y) sort higher in the port
            // list.  This minimises straight-edge crossings without moving nodes.
            // Must run before nodeHtmlLabel (which renders the port rows) and
            // before endpoint-snapping (which indexes ports by position).
            //
            // Uses actual port Y (not node centre) as the sort key so that tall
            // nodes with many ports are handled correctly.  All Y values are
            // computed from a pre-sort snapshot so the ordering of one node does
            // not affect another node's sort key mid-pass.
            (function sortPortsByTargetY() {
                const ROW_H = 22;
                function portY(node, portId, portList) {
                    const nodeH   = node.data('node_height') || 100;
                    const idx     = portList.indexOf(portId);
                    if (idx < 0) return node.position('y');
                    const yFromTop = nodeH / 2 - portList.length * ROW_H / 2
                                   + idx * ROW_H + ROW_H / 2;
                    return node.position('y') - nodeH / 2 + yFromTop;
                }

                // Snapshot port lists before any mutation.
                const origOut = {}, origIn = {};
                cyInstance.nodes('[!is_junction][!is_phantom]').forEach(function (node) {
                    origOut[node.id()] = node.data('out_ports') || [];
                    origIn[node.id()]  = node.data('in_ports')  || [];
                });

                const outTargetYs = {};
                const inSourceYs  = {};

                cyInstance.edges().forEach(function (edge) {
                    const d   = edge.data();
                    const src = cyInstance.getElementById(d.source);
                    const tgt = cyInstance.getElementById(d.target);
                    if (!src.length || !tgt.length) return;
                    if (src.data('is_phantom') || tgt.data('is_phantom')) return;
                    if (src.data('is_junction') || tgt.data('is_junction')) return;

                    if (d.src_port) {
                        // Sort src's out_ports by the actual Y of the dest port on tgt
                        const tY = d.dst_port
                            ? portY(tgt, d.dst_port, origIn[tgt.id()] || [])
                            : tgt.position('y');
                        if (!outTargetYs[d.source]) outTargetYs[d.source] = {};
                        const b = outTargetYs[d.source];
                        if (!b[d.src_port]) b[d.src_port] = [];
                        b[d.src_port].push(tY);
                    }
                    if (d.dst_port) {
                        // Sort tgt's in_ports by the actual Y of the source port on src
                        const sY = d.src_port
                            ? portY(src, d.src_port, origOut[src.id()] || [])
                            : src.position('y');
                        if (!inSourceYs[d.target]) inSourceYs[d.target] = {};
                        const b = inSourceYs[d.target];
                        if (!b[d.dst_port]) b[d.dst_port] = [];
                        b[d.dst_port].push(sY);
                    }
                });

                function avgY(arr) {
                    return arr && arr.length
                        ? arr.reduce((s, v) => s + v, 0) / arr.length
                        : Infinity;
                }

                cyInstance.nodes('[!is_junction][!is_phantom]').forEach(function (node) {
                    const id = node.id();

                    const out = origOut[id];
                    if (out && out.length > 1) {
                        const m = outTargetYs[id] || {};
                        node.data('out_ports', [...out].sort((a, b) => avgY(m[a]) - avgY(m[b])));
                    }

                    const inp = origIn[id];
                    if (inp && inp.length > 1) {
                        const m = inSourceYs[id] || {};
                        node.data('in_ports', [...inp].sort((a, b) => avgY(m[a]) - avgY(m[b])));
                    }
                });
            }());

            if (typeof cyInstance.nodeHtmlLabel === 'function') {
                cyInstance.nodeHtmlLabel([{
                    query: 'node[!is_junction][!is_phantom]',
                    halign: 'center',
                    valign: 'center',
                    halignBox: 'center',
                    valignBox: 'center',
                    tpl: buildNodeHtml,
                }]);
            }

            // Snap edge endpoints to port row positions.
            // Cytoscape source-endpoint/target-endpoint percentages are CENTRE-RELATIVE,
            // scaled to node dimensions:
            //   "50%  0%"  = right edge, vertically centred  (source)
            //   "-50% 0%"  = left edge,  vertically centred  (target)
            //   y% is (yFromTop/nodeH * 100) - 50, converting from top-based to centre-based.
            const PORT_ROW_H_EP = 22;
            function portEndpointY(idx, total, nodeH) {
                const yFromTop = nodeH / 2 - total * PORT_ROW_H_EP / 2 + idx * PORT_ROW_H_EP + PORT_ROW_H_EP / 2;
                return (yFromTop / nodeH * 100 - 50).toFixed(1);
            }

            cyInstance.edges().forEach(function (edge) {
                const d = edge.data();

                if (d.src_port) {
                    const srcNode = cyInstance.getElementById(d.source);
                    if (srcNode.length && !srcNode.data('is_junction')) {
                        const outPorts = srcNode.data('out_ports') || [];
                        const idx = outPorts.indexOf(d.src_port);
                        if (idx >= 0) {
                            const yPct = portEndpointY(idx, outPorts.length, srcNode.data('node_height'));
                            edge.style('source-endpoint', '50% ' + yPct + '%');
                        }
                    }
                }

                if (d.dst_port) {
                    const dstNode = cyInstance.getElementById(d.target);
                    if (dstNode.length && !dstNode.data('is_junction')) {
                        const inPorts = dstNode.data('in_ports') || [];
                        const idx = inPorts.indexOf(d.dst_port);
                        if (idx >= 0) {
                            const yPct = portEndpointY(idx, inPorts.length, dstNode.data('node_height'));
                            edge.style('target-endpoint', '-50% ' + yPct + '%');
                        }
                    }
                }
            });

            // Back-edges (target is left of source in the LR layout) cannot be routed
            // around node boundaries using Cytoscape bezier control-point weights, because
            // weights in [0,1] keep every control point within the source–target horizontal
            // span (i.e. between the two node edges, not outside them).
            //
            // Solution: replace each back-edge with 4 invisible phantom waypoint nodes at
            // the 4 orthogonal corners of the U-shape, plus 5 straight-line segment edges.
            // All positions are computed in absolute canvas coordinates post-layout.
            //
            //   wp1  (srcRight+M, srcPortY) → exits right of source node at port Y
            //   wp2  (srcRight+M, belowY)   → bottom-right corner
            //   wp3  (tgtLeft-M,  belowY)   → bottom-left corner
            //   wp4  (tgtLeft-M,  tgtPortY) → enters left of target node at port Y

            function portAbsY(node, portId, portList) {
                const nodeH = node.data('node_height') || 100;
                const idx   = portList.indexOf(portId);
                if (idx < 0) return node.position('y');
                const yFromTop = nodeH / 2 - portList.length * PORT_ROW_H_EP / 2
                               + idx * PORT_ROW_H_EP + PORT_ROW_H_EP / 2;
                return node.position('y') - nodeH / 2 + yFromTop;
            }

            const backEdgesToRoute = [];
            cyInstance.edges().forEach(function (edge) {
                const d   = edge.data();
                const src = cyInstance.getElementById(d.source);
                const tgt = cyInstance.getElementById(d.target);
                if (!src.length || !tgt.length) return;
                if (src.data('is_junction') || tgt.data('is_junction')) return;
                if (tgt.position('x') < src.position('x'))
                    backEdgesToRoute.push({ edge, src, tgt, d });
            });

            const BACK_MARGIN  = 50;
            const BACK_BELOW   = 80;
            const LANE_SPACING = PORT_ROW_H_EP; // 22px — matches port grid

            // Pre-compute each edge's source port Y so we can sort and assign lanes.
            // Sorting top→bottom gives innermost U to the top-most source port,
            // which keeps the nested U-shapes from crossing each other.
            backEdgesToRoute.forEach(function (be) {
                const outPorts = be.src.data('out_ports') || [];
                be.srcPortY    = portAbsY(be.src, be.d.src_port, outPorts);
                be.inPorts     = be.tgt.data('in_ports') || [];
                be.tgtPortY    = portAbsY(be.tgt, be.d.dst_port, be.inPorts);
                be.outPorts    = outPorts;
                be.srcRight    = be.src.position('x') + (be.src.data('node_width')  || 200) / 2;
                be.tgtLeft     = be.tgt.position('x') - (be.tgt.data('node_width')  || 200) / 2;
            });
            backEdgesToRoute.sort((a, b) => b.srcPortY - a.srcPortY);

            // Global base — innermost lane must clear ALL source/target node bottoms.
            const baseBelow = backEdgesToRoute.reduce(function (maxY, be) {
                return Math.max(
                    maxY,
                    be.src.position('y') + (be.src.data('node_height') || 100) / 2,
                    be.tgt.position('y') + (be.tgt.data('node_height') || 100) / 2
                );
            }, -Infinity) + BACK_BELOW;

            backEdgesToRoute.forEach(function ({ edge, src, tgt, d, srcPortY, tgtPortY, outPorts, inPorts, srcRight, tgtLeft }, laneIndex) {
                const laneOff = laneIndex * LANE_SPACING;
                const rightX  = srcRight + BACK_MARGIN + laneOff;
                const leftX   = tgtLeft  - BACK_MARGIN - laneOff;
                const belowY  = baseBelow              + laneOff;

                const eid    = d.id;
                const shared = {
                    color:    d.color,
                    cable_id: d.cable_id,
                    src_port: d.src_port,
                    dst_port: d.dst_port,
                    protocol: d.protocol,
                    type:     d.type,
                };

                edge.remove();

                cyInstance.add([
                    { group: 'nodes', data: { id: `__bkwp__${eid}_1`, is_phantom: true }, position: { x: rightX, y: srcPortY } },
                    { group: 'nodes', data: { id: `__bkwp__${eid}_2`, is_phantom: true }, position: { x: rightX, y: belowY   } },
                    { group: 'nodes', data: { id: `__bkwp__${eid}_3`, is_phantom: true }, position: { x: leftX,  y: belowY   } },
                    { group: 'nodes', data: { id: `__bkwp__${eid}_4`, is_phantom: true }, position: { x: leftX,  y: tgtPortY } },
                ]);

                cyInstance.add([
                    { group: 'edges', data: { id: `__bkseg__${eid}_1`, source: d.source,            target: `__bkwp__${eid}_1`, label: '',           ...shared } },
                    { group: 'edges', data: { id: `__bkseg__${eid}_2`, source: `__bkwp__${eid}_1`, target: `__bkwp__${eid}_2`, label: '',           ...shared } },
                    { group: 'edges', data: { id: `__bkseg__${eid}_3`, source: `__bkwp__${eid}_2`, target: `__bkwp__${eid}_3`, label: d.label || '', ...shared } },
                    { group: 'edges', data: { id: `__bkseg__${eid}_4`, source: `__bkwp__${eid}_3`, target: `__bkwp__${eid}_4`, label: '',           ...shared } },
                    { group: 'edges', data: { id: `__bkseg__${eid}_5`, source: `__bkwp__${eid}_4`, target: d.target,           label: '',           ...shared } },
                ]);

                // Snap first segment's source to the out-port on the right edge
                const seg1 = cyInstance.getElementById(`__bkseg__${eid}_1`);
                if (d.src_port) {
                    const idx = outPorts.indexOf(d.src_port);
                    if (idx >= 0)
                        seg1.style('source-endpoint', '50% ' + portEndpointY(idx, outPorts.length, src.data('node_height')) + '%');
                }

                // Snap last segment's target to the in-port on the left edge
                const seg5 = cyInstance.getElementById(`__bkseg__${eid}_5`);
                if (d.dst_port) {
                    const idx = inPorts.indexOf(d.dst_port);
                    if (idx >= 0)
                        seg5.style('target-endpoint', '-50% ' + portEndpointY(idx, inPorts.length, tgt.data('node_height')) + '%');
                }

                // Arrow only on the final segment
                ['1', '2', '3', '4'].forEach(function (n) {
                    cyInstance.getElementById(`__bkseg__${eid}_${n}`).style({
                        'target-arrow-shape': 'none',
                        'source-arrow-shape': 'none',
                    });
                });
                seg5.style({ 'target-arrow-shape': 'triangle', 'source-arrow-shape': 'none' });
            });

            if (backEdgesToRoute.length > 0) cyInstance.fit(30);
        });

        cyInstance.on('tap', 'node', async function(evt) {
            const node = evt.target;
            if (node.data('is_junction') || node.data('is_phantom')) return;
            const tag = node.data('id');

            targetTagFilter.value = tag;
            baseTargetTag = tag;
            hiddenNodes.clear();
            hiddenCables.clear();
            hiddenNodeNeighbors.clear();
            allKnownDiagramAssetTags.clear();
            expansionResultLog.clear();
            currentFilters = {
                targetTag: tag, cableId: '',
                direction: directionFilter.value,
                cableType: cableTypeFilter.value,
                protocol: protocolFilter ? protocolFilter.value.trim() : '',
            };
            initializeExpansionMap(baseTargetTag, currentFilters.direction);
            await fetchAndRenderDiagramAndCables(
                currentFilters.targetTag, currentFilters.direction,
                currentFilters.cableType, currentFilters.protocol,
                currentFilters.cableId, true
            );
        });

        cyInstance.on('cxttap', 'node', function(evt) {
            const node = evt.target;
            if (node.data('is_junction')) return;
            const tag = node.data('id');
            const renderedPos = evt.renderedPosition;
            const rect = diagramRenderArea.getBoundingClientRect();
            showContextMenu(tag, renderedPos.x + rect.left, renderedPos.y + rect.top);
        });

        cyInstance.on('tap', function(evt) {
            if (evt.target === cyInstance) hideContextMenu();
        });

        cyInstance.on('mouseover', 'edge', function(evt) {
            const d = evt.target.data();
            const lines = [];
            if (d.cable_id) lines.push(`Cable: ${d.cable_id}`);
            if (d.src_port || d.dst_port) lines.push(`Ports: ${d.src_port || '—'} → ${d.dst_port || '—'}`);
            if (d.protocol) lines.push(`Protocol: ${d.protocol}`);
            if (d.type)     lines.push(`Type: ${d.type}`);
            if (lines.length) diagramRenderArea.title = lines.join('\n');
        });
        cyInstance.on('mouseout', 'edge', function() { diagramRenderArea.title = ''; });
    }

    // Build the export SVG: cytoscape-svg renders the structural base
    // (node boxes + edges), then node text is injected on top from model
    // data, since the on-screen text lives in HTML overlays the canvas
    // renderer never sees.  Returns the SVG as a plain string.
    function generateDiagramSvg() {
        if (!cyInstance) return null;

        // ── Strategy: use cy.svg() for the structural base (colored boxes +
        //   edges) then inject <text> elements on top.  With {full:true,
        //   scale:1} the plugin draws content translated by (-bb.x1, -bb.y1),
        //   where bb is the bounding box of all elements — so the injected
        //   text must be wrapped in a <g> with that same translation.
        const PORT_ROW_H = 22;
        const PORT_FS    = 9;
        const TAG_FS     = 10;

        function xe(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;')
                .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }
        function f(n) { return n.toFixed(2); }

        function portAbsY(pos, nodeH, idx, count) {
            const yFromTop = nodeH / 2 - count * PORT_ROW_H / 2
                           + idx * PORT_ROW_H + PORT_ROW_H / 2;
            return pos.y - nodeH / 2 + yFromTop;
        }

        // ── Get base SVG from cytoscape-svg plugin ─────────────────────────
        let baseSvg = '';
        try {
            // scale:1 keeps the output in model units (no devicePixelRatio).
            baseSvg = cyInstance.svg({ full: true, bg: '#ffffff', scale: 1 }) || '';
        } catch (e) {
            console.warn('[SVG export] cy.svg() failed:', e);
        }

        // ── Build text injections ──────────────────────────────────────────
        const textLines = [];
        const realNodes = cyInstance.nodes('[!is_junction][!is_phantom]');

        realNodes.forEach(function (node) {
            const data = node.data();
            const pos  = node.position();
            const nw   = +data.node_width  || 200;
            const nh   = +data.node_height || 100;

            const inPorts  = data.in_ports  || [];
            const outPorts = data.out_ports || [];

            inPorts.forEach(function (p, i) {
                const py = portAbsY(pos, nh, i, inPorts.length);
                textLines.push(
                    `<text x="${f(pos.x - nw/2 + 4)}" y="${f(py)}" dy="0.35em" ` +
                    `text-anchor="start" font-family="Arial,sans-serif" ` +
                    `font-size="${PORT_FS}" fill="#222222">${xe(p)}</text>`
                );
            });
            outPorts.forEach(function (p, i) {
                const py = portAbsY(pos, nh, i, outPorts.length);
                textLines.push(
                    `<text x="${f(pos.x + nw/2 - 4)}" y="${f(py)}" dy="0.35em" ` +
                    `text-anchor="end" font-family="Arial,sans-serif" ` +
                    `font-size="${PORT_FS}" fill="#222222">${xe(p)}</text>`
                );
            });

            const fields    = data.fields || {};
            const tagVal    = fields['tag'] || data.display_tag || data.id || '';
            const otherVals = Object.keys(fields)
                .filter(function (k) { return k !== 'tag'; })
                .map(function (k) { return fields[k]; })
                .filter(function (v) { return v != null && v !== ''; })
                .slice(0, 3);

            const lineH  = TAG_FS * 1.5;
            const blockH = (1 + otherVals.length) * lineH;
            const startY = pos.y - blockH / 2 + lineH / 2;

            textLines.push(
                `<text x="${f(pos.x)}" y="${f(startY)}" dy="0.35em" ` +
                `text-anchor="middle" font-family="Arial,sans-serif" ` +
                `font-size="${TAG_FS}" font-weight="bold" fill="#1a1a1a">${xe(tagVal)}</text>`
            );
            otherVals.forEach(function (v, fi) {
                textLines.push(
                    `<text x="${f(pos.x)}" y="${f(startY + lineH * (fi + 1))}" dy="0.35em" ` +
                    `text-anchor="middle" font-family="Arial,sans-serif" ` +
                    `font-size="${(TAG_FS * 0.85).toFixed(1)}" fill="#555555">${xe(String(v))}</text>`
                );
            });
        });

        // ── Fallback: build SVG from scratch if cy.svg() returned nothing ──
        if (!baseSvg) {
            const PAD = 40;
            const bb2 = cyInstance.nodes('[!is_phantom]').boundingBox();
            if (!isFinite(bb2.x1)) return null;
            const W2 = Math.ceil(bb2.w + 2 * PAD);
            const H2 = Math.ceil(bb2.h + 2 * PAD);
            const ox2 = -bb2.x1 + PAD;
            const oy2 = -bb2.y1 + PAD;
            const adjusted = textLines.map(function (t) {
                return t
                    .replace(/x="(-?\d+\.\d+)"/g, function (_, v) {
                        return `x="${(parseFloat(v) + ox2).toFixed(2)}"`;
                    })
                    .replace(/y="(-?\d+\.\d+)"/g, function (_, v) {
                        return `y="${(parseFloat(v) + oy2).toFixed(2)}"`;
                    });
            });
            const nodeRects = [];
            cyInstance.nodes('[!is_junction][!is_phantom]').forEach(function (node) {
                const d = node.data();
                const p = node.position();
                const nw = +d.node_width || 200;
                const nh = +d.node_height || 100;
                nodeRects.push(
                    `<rect x="${(p.x - nw/2 + ox2).toFixed(2)}" y="${(p.y - nh/2 + oy2).toFixed(2)}" ` +
                    `width="${nw}" height="${nh}" fill="${xe(d.bg_color || '#e3f2fd')}" ` +
                    `stroke="#0052cc" stroke-width="1.5" rx="2"/>`
                );
            });
            return [
                `<svg xmlns="http://www.w3.org/2000/svg" width="${W2}" height="${H2}" viewBox="0 0 ${W2} ${H2}">`,
                `<rect x="0" y="0" width="${W2}" height="${H2}" fill="#ffffff"/>`,
                nodeRects.join(''),
                adjusted.join(''),
                '</svg>',
            ].join('');
        }

        // The plugin draws content translated by (-bb.x1, -bb.y1) where bb is
        // the bounding box of all elements (phantoms included).  Wrap the text
        // in a <g> with the identical transform so coordinates line up.
        const bb = cyInstance.mutableElements().boundingBox();
        const textGroup =
            `<g transform="translate(${f(-bb.x1)},${f(-bb.y1)})">` +
            textLines.join('') + '</g>';
        return baseSvg.replace(/<\/svg>\s*$/, textGroup + '</svg>');
    }

    // Render the SVG to a canvas for PNG export.
    // Uses a data: URL (not a blob URL) so Safari doesn't taint the canvas.
    function captureDiagramCanvas() {
        if (!cyInstance) return Promise.reject(new Error('No diagram loaded.'));
        cyInstance.fit(30);
        return new Promise(function (resolve, reject) {
            requestAnimationFrame(function () {
                const svgStr = generateDiagramSvg();
                if (!svgStr) { reject(new Error('No diagram data.')); return; }
                // btoa path handles non-ASCII via percent-encoding → latin-1 roundtrip
                const dataUrl = 'data:image/svg+xml;base64,' +
                    btoa(unescape(encodeURIComponent(svgStr)));
                const img = new Image();
                img.onload = function () {
                    const w     = img.naturalWidth  || img.width  || 800;
                    const h     = img.naturalHeight || img.height || 600;
                    const SCALE = 2;   // 2x raster so small text stays crisp
                    const out = document.createElement('canvas');
                    out.width  = w * SCALE;
                    out.height = h * SCALE;
                    const ctx = out.getContext('2d');
                    ctx.fillStyle = '#ffffff';
                    ctx.fillRect(0, 0, out.width, out.height);
                    ctx.drawImage(img, 0, 0, out.width, out.height);
                    resolve(out);
                };
                img.onerror = function () { reject(new Error('SVG render failed.')); };
                img.src = dataUrl;
            });
        });
    }

    if (exportPngBtn) {
        exportPngBtn.addEventListener('click', function () {
            captureDiagramCanvas().then(function (canvas) {
                canvas.toBlob(function (blob) {
                    const url = URL.createObjectURL(blob);
                    const a   = document.createElement('a');
                    a.href     = url;
                    a.download = 'diagram-' + (baseTargetTag || 'export') + '.png';
                    a.click();
                    URL.revokeObjectURL(url);
                });
            }).catch(function (err) { alert(err.message); });
        });
    }

    if (exportSvgBtn) {
        exportSvgBtn.addEventListener('click', function () {
            if (!cyInstance) { alert('No diagram loaded.'); return; }
            cyInstance.fit(30);
            requestAnimationFrame(function () {
                const svgStr = generateDiagramSvg();
                if (!svgStr) { alert('No diagram data.'); return; }
                const blob = new Blob([svgStr], { type: 'image/svg+xml;charset=utf-8' });
                const url  = URL.createObjectURL(blob);
                const a    = document.createElement('a');
                a.href     = url;
                a.download = 'diagram-' + (baseTargetTag || 'export') + '.svg';
                a.click();
                URL.revokeObjectURL(url);
            });
        });
    }

    // Diagram expand / fullscreen toggle
    (function () {
        const btn  = document.getElementById('diagramExpandBtn');
        const wrap = btn && btn.closest('.diagram-canvas-wrap');
        if (!btn || !wrap) return;

        const ICON_EXPAND = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14"><path d="M0 0v5h1.5V1.5H5V0H0zm9 0v1.5h3.5V5H14V0H9zM0 9v5h5v-1.5H1.5V9H0zm12.5 3.5H9V14h5V9h-1.5v3.5z" fill="currentColor"/></svg>`;
        const ICON_RESTORE = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14"><path d="M5 0H3.5v3.5H0V5h5V0zm4 0v5h5V3.5H9.5V0H9zM0 9v1.5h3.5V14H5V9H0zm9 0v5h1.5V10.5H14V9H9z" fill="currentColor"/></svg>`;
        btn.innerHTML = ICON_EXPAND;

        function setExpanded(on) {
            wrap.classList.toggle('diagram-fullscreen', on);
            btn.innerHTML   = on ? ICON_RESTORE : ICON_EXPAND;
            btn.title       = on ? 'Restore diagram' : 'Expand to full window';
            btn.setAttribute('aria-label', on ? 'Restore diagram' : 'Expand diagram');
            if (cyInstance) {
                cyInstance.resize();
                if (on) cyInstance.fit(30);
            }
        }

        btn.addEventListener('click', function () {
            setExpanded(!wrap.classList.contains('diagram-fullscreen'));
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && wrap.classList.contains('diagram-fullscreen')) {
                setExpanded(false);
            }
        });
    }());

    // Add Enter key support for diagram viewer inputs
    [targetTagFilter, cableTypeFilter, protocolFilter].forEach(input => {
        if (input) {
            input.addEventListener("keypress", (e) => {
                if (e.key === "Enter") {
                    e.preventDefault();
                    performDiagramView();
                }
            });
        }
    });

    const performViewCrosspoint = async () => {
        const sourceTag = getCrosspointValue("source");
        const targetTag = getCrosspointValue("target");
        if (!sourceTag || !targetTag) {
            alert("Please enter both Source and Target asset tags.");
            return;
        }
        lastCrosspointQuery = { source: sourceTag, target: targetTag };
        await fetchAndRenderCrosspointMatrix(sourceTag, targetTag);
    };

    if (viewCrosspointBtn) {
        viewCrosspointBtn.addEventListener("click", performViewCrosspoint);
    }

    // Add Enter key support for crosspoint inputs
    if (crosspointSourceInput) {
        crosspointSourceInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                performViewCrosspoint();
            }
        });
    }
    if (crosspointTargetInput) {
        crosspointTargetInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                performViewCrosspoint();
            }
        });
    }

    if (resetCrosspointBtn) {
        resetCrosspointBtn.addEventListener("click", () => {
            resetCrosspointInputs(true);
            if (crosspointMatrixContainer) {
                crosspointMatrixContainer.innerHTML = "";
            }
            setCrosspointStatus("", "info");
        });
    }

    if (crosspointSourceInput) {
        crosspointSourceInput.addEventListener("input", () => {
            handleAssetInputChange("source", crosspointSourceInput.value.trim());
        });
    }
    if (crosspointTargetInput) {
        crosspointTargetInput.addEventListener("input", () => {
            handleAssetInputChange("target", crosspointTargetInput.value.trim());
        });
    }
    if (crosspointSourceSelect) {
        crosspointSourceSelect.addEventListener("change", () => handleAssetSelectChange("source"));
    }
    if (crosspointTargetSelect) {
        crosspointTargetSelect.addEventListener("change", () => handleAssetSelectChange("target"));
    }

    const handleCrosspointOptionChange = async () => {
        if (!lastCrosspointQuery) {
            return;
        }
        await fetchAndRenderCrosspointMatrix(lastCrosspointQuery.source, lastCrosspointQuery.target, true);
    };

    if (crosspointHeaderFields) {
        crosspointHeaderFields.addEventListener("change", handleCrosspointOptionChange);
    }
    if (crosspointProtocolSelect) {
        crosspointProtocolSelect.addEventListener("change", handleCrosspointOptionChange);
    }

    // --- Reload Data Button Logic ---
    const reloadHistoryPanel = document.getElementById("reloadHistoryPanel");
    const reloadHistoryContent = document.getElementById("reloadHistoryContent");

    async function fetchAndRenderReloadHistory() {
        if (!reloadHistoryContent) return;
        try {
            const resp = await fetch(`${API_BASE_URL}/data/reload-history`);
            const entries = await resp.json();
            if (!entries || entries.length === 0) {
                reloadHistoryContent.innerHTML = "<em>No reloads recorded this session.</em>";
                return;
            }
            const rows = entries.map(e => {
                const statusBadge = e.status === "ok"
                    ? `<span style="color:var(--color-success)">✔ ok</span>`
                    : `<span style="color:var(--color-danger)">✘ error</span>`;
                const counts = e.status === "ok"
                    ? `${e.assets} assets / ${e.cables} cables / ${e.network} network / ${e.issues} issues`
                    : escapeHtml(e.error || "");
                return `<tr><td>${escapeHtml(e.timestamp)}</td><td>${statusBadge}</td><td>${counts}</td></tr>`;
            }).join("");
            reloadHistoryContent.innerHTML = `<table class="reload-history-table"><thead><tr><th>Time</th><th>Status</th><th>Counts</th></tr></thead><tbody>${rows}</tbody></table>`;
        } catch (err) {
            reloadHistoryContent.innerHTML = `<em>Could not load history: ${escapeHtml(err.message)}</em>`;
        }
    }

    reloadDataBtn.addEventListener('click', async () => {
        reloadDataBtn.disabled = true;
        reloadStatus.textContent = 'Reloading data...';
        try {
            const response = await fetch(`${API_BASE_URL}/data/reload`, { method: 'POST' });
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${response.status}`);
            }
            const payload = await response.json();
            reloadStatus.textContent = `Reloaded ${payload.assets || 0} assets / ${payload.cables || 0} cables`;
            loadKBTagOptions();
            fetchAndRenderReloadHistory();
        } catch (error) {
            console.error('Error reloading data:', error);
            reloadStatus.textContent = `Reload failed: ${error.message}`;
            fetchAndRenderReloadHistory();
        } finally {
            reloadDataBtn.disabled = false;
        }
    });

    if (reloadHistoryPanel) {
        reloadHistoryPanel.addEventListener("toggle", () => {
            if (reloadHistoryPanel.open) fetchAndRenderReloadHistory();
        });
    }


    document.addEventListener('click', () => hideContextMenu());

    nodeContextMenu.addEventListener('click', async (event) => {
        const action = event.target.dataset.action;
        const targetTag = contextMenuTargetTag;
        if (!action || !targetTag) {
            return;
        }
        event.stopPropagation();
        hideContextMenu();
        if (action === 'hide') {
            await handleHideNode(targetTag);
        } else if (action === 'add-in') {
            await handleAddConnections(targetTag, 'in');
        } else if (action === 'add-out') {
            await handleAddConnections(targetTag, 'out');
        } else if (action === 'add-inbound-for-outbound') {
            await handleAddConnectedViaRoute(targetTag, 'inbound_for_outbound');
        } else if (action === 'add-outbound-for-inbound') {
            await handleAddConnectedViaRoute(targetTag, 'outbound_for_inbound');
        }
    });


    // Function to fetch and render diagram and cables based on filters and active assets
    async function fetchAndRenderDiagramAndCables(targetTag, direction, cableType, protocol, cableId = "", resetActiveAssets = false, forceIncludeTags = new Set()) {
        const prevAvailableSnapshot = [...availableDiagramAssetTags];
        const expansionEntries = Array.from(nodeExpansionMap.entries());
        const selectedAssetsList = Array.from(selectedAssetTags)
            .map(tag => (tag || "").trim())
            .filter(Boolean);
        const additionalAssetsSet = new Set(
            expansionEntries
                .map(([tag]) => tag)
                .filter(tag => tag && tag !== baseTargetTag)
        );
        selectedAssetsList.forEach(tag => {
            if (tag !== baseTargetTag) {
                additionalAssetsSet.add(tag);
            }
        });
        const additionalAssetsList = Array.from(additionalAssetsSet);
        const additionalAssets = additionalAssetsList.join(',');
        const expansionParam = expansionEntries
            .map(([tag, dirSet]) => {
                const hasIn = dirSet.has('in');
                const hasOut = dirSet.has('out');
                let dirValue = 'both';
                if (hasIn && !hasOut) dirValue = 'in';
                else if (!hasIn && hasOut) dirValue = 'out';
                return `${tag}:${dirValue}`;
            })
            .join(';');
        const selectedNodeFields = getSelectedOptions(nodeFieldsSelect, nodeFieldDefaults);
        const selectedEdgeFields = getSelectedOptions(edgeFieldsSelect, edgeFieldDefaults);
        const colorNodesEnabled = colorNodesCheckbox ? colorNodesCheckbox.checked : false;
        const colorEdgesEnabled = colorEdgesCheckbox ? colorEdgesCheckbox.checked : false;
        const collapseStrategy = collapseStrategySelect ? collapseStrategySelect.value : "none";
        const excludeInternalRoutes   = excludeInternalRoutesCheckbox  ? excludeInternalRoutesCheckbox.checked  : true;
        const includePhysicalRoutes   = includePhysicalRoutesCheckbox  ? includePhysicalRoutesCheckbox.checked  : true;
        const includeLogicalRoutes    = includeLogicalRoutesCheckbox   ? includeLogicalRoutesCheckbox.checked   : false;
        const includePassthroughs     = includePassthroughsCheckbox    ? includePassthroughsCheckbox.checked    : false;
        const combinedForceInclude = forceIncludeTags instanceof Set ? new Set(forceIncludeTags) : new Set();
        selectedAssetsList.forEach(tag => combinedForceInclude.add(tag));

        // --- Fetch Cable Data (also used to derive node list) ---
        const cableParams = new URLSearchParams();
        if (targetTag) cableParams.append("target_tag", targetTag);
        if (cableId) cableParams.append("cable_id", cableId); // Pass the cable ID
        cableParams.append("direction", direction);
        if (cableType) cableParams.append("cable_type", cableType);
        if (protocol) cableParams.append("protocol", protocol);
        cableParams.append("node_fields", selectedNodeFields.join(','));
        cableParams.append("edge_fields", selectedEdgeFields.join(','));
        cableParams.append("exclude_internal_routes", excludeInternalRoutes ? "true" : "false");
        cableParams.append("include_physical_routes", includePhysicalRoutes ? "true" : "false");
        cableParams.append("include_logical_routes",  includeLogicalRoutes  ? "true" : "false");
        cableParams.append("include_passthroughs",    includePassthroughs   ? "true" : "false");

        if (additionalAssets) {
            cableParams.append("additional_asset_tags", additionalAssets);
        }
        if (expansionParam) {
            cableParams.append("expansions", expansionParam);
        }
        if (hiddenCables.size > 0) {
            cableParams.append("hidden_cable_ids", Array.from(hiddenCables).join(','));
        }
        let cableData = [];
        let backendAssetTags = [];
        try {
            const cableResponse = await fetch(`${API_BASE_URL}/cables/filter?${cableParams.toString()}`);
            if (!cableResponse.ok) {
                const errorData = await cableResponse.json().catch(() => ({}));
                const message = errorData.detail || `HTTP error! status: ${cableResponse.status}`;
                diagramRenderArea.innerHTML = `<p style="color: red;">${message}</p>`;
                cableTableContainer.innerHTML = `<p style="color: red;">${message}</p>`;
                setDiagramStatus(`Error loading cables: ${message}`, "error");
                return { availableChanged: false }; // Stop further processing
            }
            const responsePayload = await cableResponse.json();
            if (Array.isArray(responsePayload)) {
                cableData = responsePayload;
            } else if (responsePayload && typeof responsePayload === 'object') {
                cableData = responsePayload.cables || [];
                backendAssetTags = responsePayload.asset_tags || [];
                baseTargetTag = responsePayload.primary_target || targetTag || cableId || "";
            } else {
                cableData = [];
            }
            currentDiagramCableData = cableData;
            renderTable(cableData, cableTableContainer, 'cableResults'); // Pass table ID
        } catch (error) {
            console.error("Error fetching cable data:", error);
            const errMsg = `Error loading cable data: ${error.message}`;
            cableTableContainer.innerHTML = `<p style="color: red;">${errMsg}</p>`;
            diagramRenderArea.innerHTML = `<p style="color: red;">${errMsg}</p>`;
            setDiagramStatus(errMsg, "error");
            return { availableChanged: false }; // Exit if cable data fetch fails
        }

        // Rebuild adjacency maps for neighbor lookups.
        adjacencyOutMap.clear();
        adjacencyInMap.clear();
        cableData.forEach(cable => {
            const src = cable.SrcTag ? cable.SrcTag.trim() : "";
            const dst = cable.DstTag ? cable.DstTag.trim() : "";
            if (!src || !dst) return;
            if (!adjacencyOutMap.has(src)) adjacencyOutMap.set(src, new Set());
            if (!adjacencyInMap.has(dst)) adjacencyInMap.set(dst, new Set());
            adjacencyOutMap.get(src).add(dst);
            adjacencyInMap.get(dst).add(src);
        });

        // Build the available and active asset tag lists based on backend response/cable results.
        const discoveredAssetTags = new Set(backendAssetTags);
        cableData.forEach(cable => {
            if (cable.SrcTag) discoveredAssetTags.add(cable.SrcTag.trim());
            if (cable.DstTag) discoveredAssetTags.add(cable.DstTag.trim());
        });
        if (targetTag) {
            discoveredAssetTags.add(targetTag);
        }
        additionalAssetsList.forEach(tag => {
            if (tag) {
                discoveredAssetTags.add(tag);
            }
        });
        selectedAssetsList.forEach(tag => discoveredAssetTags.add(tag));

        // Ensure any explicitly-unhidden nodes are always discoverable,
        // even if the backend didn't return their cables this fetch.
        combinedForceInclude.forEach(tag => { if (tag) discoveredAssetTags.add(tag); });

        const sortedDiscoveredTags = Array.from(discoveredAssetTags).filter(Boolean).sort();
        const newlyDiscovered = [];
        sortedDiscoveredTags.forEach(tag => {
            if (!allKnownDiagramAssetTags.has(tag)) {
                allKnownDiagramAssetTags.add(tag);
                newlyDiscovered.push(tag);
            }
        });
        availableDiagramAssetTags = [...sortedDiscoveredTags];

        if (resetActiveAssets) {
            hiddenNodes.clear();
            hiddenCables.clear();
            allKnownDiagramAssetTags.clear();
            expansionResultLog.clear();
        }
        hiddenNodes.delete(baseTargetTag);

        newlyDiscovered.forEach(tag => hiddenNodes.delete(tag));
        activeDiagramAssetTags = sortedDiscoveredTags.filter(tag => !hiddenNodes.has(tag));
        if (!activeDiagramAssetTags.includes(baseTargetTag) && sortedDiscoveredTags.includes(baseTargetTag)) {
            activeDiagramAssetTags.push(baseTargetTag);
        }
        selectedAssetsList.forEach(tag => {
            if (!tag) return;
            hiddenNodes.delete(tag);
            if (!activeDiagramAssetTags.includes(tag)) {
                activeDiagramAssetTags.push(tag);
            }
        });
        if (activeDiagramAssetTags.length === 0 && sortedDiscoveredTags.length > 0) {
            activeDiagramAssetTags = [...sortedDiscoveredTags];
        }

        // --- Fetch Graphviz SVG ---
        const dotParams = new URLSearchParams();
        dotParams.append("target_tag", targetTag);
        dotParams.append("direction", direction);
        if (cableType) dotParams.append("cable_type", cableType);
        if (protocol) dotParams.append("protocol", protocol);
        dotParams.append("node_fields", selectedNodeFields.join(','));
        dotParams.append("edge_fields", selectedEdgeFields.join(','));
        dotParams.append("color_nodes_by_category", colorNodesEnabled ? "true" : "false");
        dotParams.append("color_edges_by_protocol", colorEdgesEnabled ? "true" : "false");
        dotParams.append("exclude_internal_routes", excludeInternalRoutes ? "true" : "false");
        dotParams.append("include_physical_routes", includePhysicalRoutes ? "true" : "false");
        dotParams.append("include_logical_routes",  includeLogicalRoutes  ? "true" : "false");
        dotParams.append("include_passthroughs",    includePassthroughs   ? "true" : "false");
        if (collapseStrategy && collapseStrategy !== "none") {
            dotParams.append("collapse_strategy", collapseStrategy);
        }
        // Always send visible_asset_tags, it's the source of truth for the graph
        if (activeDiagramAssetTags.length > 0) {
            dotParams.append("visible_asset_tags", activeDiagramAssetTags.join(','));
        }
        if (additionalAssets) {
            dotParams.append("additional_asset_tags", additionalAssets);
        }
        if (expansionParam) {
            dotParams.append("expansions", expansionParam);
        }
        if (hiddenCables.size > 0) {
            dotParams.append("hidden_cable_ids", Array.from(hiddenCables).join(','));
        }

        try {
            const graphResponse = await fetch(`${API_BASE_URL}/graph/json?${dotParams.toString()}`);
            if (!graphResponse.ok) {
                const errorData = await graphResponse.json().catch(() => ({}));
                const message = errorData.detail || `HTTP error! status: ${graphResponse.status}`;
                destroyCy();
                diagramRenderArea.innerHTML = `<p style="color: red;">${message}</p>`;
                setDiagramStatus(message, "error");
                return { availableChanged: false };
            }
            const graphData = await graphResponse.json();
            renderCytoscape(graphData);
            hideContextMenu();
        } catch (error) {
            console.error("Error fetching or rendering diagram:", error);
            const errMsg = `Error loading diagram: ${error.message}`;
            destroyCy();
            diagramRenderArea.innerHTML = `<p style="color: red;">${errMsg}</p>`;
            setDiagramStatus(errMsg, "error");
            return { availableChanged: false };
        }

        // --- Fetch and render connection tables (inputs, outputs, internal routes) ---
        const diagramInputConnectionsContainer = document.getElementById(DIAGRAM_INPUT_CONNECTIONS_CONTAINER_ID);
        const diagramOutputConnectionsContainer = document.getElementById(DIAGRAM_OUTPUT_CONNECTIONS_CONTAINER_ID);
        const diagramInternalRoutesContainer = document.getElementById(DIAGRAM_INTERNAL_ROUTES_CONTAINER_ID);
        const diagramPassthroughsContainer = document.getElementById(DIAGRAM_PASSTHROUGHS_CONTAINER_ID);

        if (diagramInputConnectionsContainer) diagramInputConnectionsContainer.innerHTML = '';
        if (diagramOutputConnectionsContainer) diagramOutputConnectionsContainer.innerHTML = '';
        if (diagramInternalRoutesContainer) diagramInternalRoutesContainer.innerHTML = '';
        if (diagramPassthroughsContainer) diagramPassthroughsContainer.innerHTML = '';

        if (targetTag && !cableId) { // Only fetch for asset tags, not cable IDs
            try {
                const connResponse = await fetch(`${API_BASE_URL}/diagram/connections?target_tag=${encodeURIComponent(targetTag)}`);
                if (connResponse.ok) {
                    const connData = await connResponse.json();
                    const sourceLabels = { PartnerAssetTag: "Source Asset Tag", PartnerManufacturer: "Source Manufacturer", PartnerModel: "Source Model", PartnerUsage: "Source Usage" };
                    const destLabels   = { PartnerAssetTag: "Destination Asset Tag", PartnerManufacturer: "Destination Manufacturer", PartnerModel: "Destination Model", PartnerUsage: "Destination Usage" };
                    renderConnectionsTable(connData.inputs || [], diagramInputConnectionsContainer, DIAGRAM_INPUT_CONNECTIONS_CONTAINER_ID, "Input Connections", sourceLabels);
                    renderConnectionsTable(connData.outputs || [], diagramOutputConnectionsContainer, DIAGRAM_OUTPUT_CONNECTIONS_CONTAINER_ID, "Output Connections", destLabels);
                    renderConnectionsTable(connData.internal_routes || [], diagramInternalRoutesContainer, DIAGRAM_INTERNAL_ROUTES_CONTAINER_ID, "Internal Routes");
                    renderConnectionsTable(connData.passthroughs || [], diagramPassthroughsContainer, DIAGRAM_PASSTHROUGHS_CONTAINER_ID, "Passthroughs");
                }
            } catch (error) {
                console.error("Error fetching connection tables:", error);
                if (diagramInputConnectionsContainer) diagramInputConnectionsContainer.innerHTML = `<p style="color: red;">Error loading connections: ${error.message}</p>`;
            }

            // Update location tab in background
            fetchAndRenderRackProfile(targetTag).catch(e => console.error("rack profile error:", e));
        }

        const availableChanged = prevAvailableSnapshot.length !== availableDiagramAssetTags.length ||
            prevAvailableSnapshot.some((tag, idx) => tag !== availableDiagramAssetTags[idx]);
        if (availableChanged || newlyDiscovered.length > 0) {
            clearDiagramStatus();
        }
        return { availableChanged, newlyDiscoveredCount: newlyDiscovered.length };
    }

    async function fetchAndRenderCrosspointMatrix(sourceTag, targetTag) {
        if (!crosspointMatrixContainer) {
            return;
        }
        const headerFields = getSelectedOptions(crosspointHeaderFields, crosspointHeaderDefaults);
        const params = new URLSearchParams();
        params.append("source_tag", sourceTag);
        params.append("target_tag", targetTag);
        if (headerFields.length) {
            params.append("header_fields", headerFields.join(','));
        }
        const selectedProtocol = crosspointProtocolSelect ? crosspointProtocolSelect.value : "";
        if (selectedProtocol) {
            params.append("protocol", selectedProtocol);
        }
        setCrosspointStatus("Loading cross-point matrix...", "info");
        try {
            const response = await fetch(`${API_BASE_URL}/crosspoint/matrix?${params.toString()}`);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP ${response.status}`);
            }
            const data = await response.json();
            populateCrosspointProtocolOptions(data.protocols, data.protocol || "");
            renderCrosspointMatrix(data);
            setCrosspointStatus("", "info");
        } catch (error) {
            console.error("Error loading cross-point matrix:", error);
            if (crosspointMatrixContainer) {
                crosspointMatrixContainer.innerHTML = `<p style="color: red;">${error.message}</p>`;
            }
            setCrosspointStatus(`Failed to load cross-point data: ${error.message}`, "error");
        }
    }
    function attachNodeContextMenuHandlers() {
        // No-op: node interaction is now handled by Cytoscape event listeners
        // set up inside renderCytoscape(). This stub is kept so that any
        // remaining call sites do not error.
    }

    function showContextMenu(tag, clientX, clientY) {
        contextMenuTargetTag = tag;
        nodeContextMenu.style.display = 'flex';
        const { offsetWidth, offsetHeight } = nodeContextMenu;
        let left = clientX;
        let top = clientY;
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        if (left + offsetWidth > viewportWidth) {
            left = viewportWidth - offsetWidth - 10;
        }
        if (top + offsetHeight > viewportHeight) {
            top = viewportHeight - offsetHeight - 10;
        }
        left = Math.max(10, left);
        top = Math.max(10, top);
        nodeContextMenu.style.left = `${left}px`;
        nodeContextMenu.style.top = `${top}px`;
    }

    function hideContextMenu() {
        nodeContextMenu.style.display = 'none';
        contextMenuTargetTag = null;
    }

    async function handleHideNode(tag) {
        if (!(currentFilters.targetTag || currentFilters.cableId)) return;
        const normalizedTag = tag.trim();
        if (normalizedTag === baseTargetTag) {
            alert("Cannot hide the primary target asset.");
            return;
        }
        // Snapshot this node's neighbors NOW while adjacency maps are still
        // complete. Once we re-fetch with the node hidden the backend may stop
        // returning its cables, wiping its edges from the adjacency maps.
        // This snapshot is the only reliable record for re-exposing it later.
        const neighbors = new Set();
        const inbound = adjacencyInMap.get(normalizedTag);
        if (inbound) inbound.forEach(n => neighbors.add(n));
        const outbound = adjacencyOutMap.get(normalizedTag);
        if (outbound) outbound.forEach(n => neighbors.add(n));
        hiddenNodeNeighbors.set(normalizedTag, neighbors);

        hiddenNodes.add(normalizedTag);

        await fetchAndRenderDiagramAndCables(
            currentFilters.targetTag,
            currentFilters.direction,
            currentFilters.cableType,
            currentFilters.protocol,
            currentFilters.cableId
        );
        clearDiagramStatus();
    }

    async function handleAddConnections(tag, direction) {
        if (!(currentFilters.targetTag || currentFilters.cableId)) return;
        if (!tag) return;
        const normalizedTag = tag.trim();
        if (!normalizedTag) return;
        const wasHidden = hiddenNodes.delete(normalizedTag);
        const neighborsToUnhide = new Set();

        // Forward lookup: live adjacency maps for current visible neighbours
        if (direction === 'both' || direction === 'in') {
            const inboundNeighbors = adjacencyInMap.get(normalizedTag);
            if (inboundNeighbors) inboundNeighbors.forEach(n => neighborsToUnhide.add(n));
        }
        if (direction === 'both' || direction === 'out') {
            const outboundNeighbors = adjacencyOutMap.get(normalizedTag);
            if (outboundNeighbors) outboundNeighbors.forEach(n => neighborsToUnhide.add(n));
        }

        // Reverse lookup via snapshot: find any hidden node that listed the
        // clicked node as a neighbour when it was hidden. This is the fix —
        // after hiding, the backend drops the node's cables from subsequent
        // responses so the live adjacency maps no longer contain its edges.
        // The snapshot recorded at hide-time is the only reliable data source.
        hiddenNodeNeighbors.forEach((neighborSet, hiddenTag) => {
            if (neighborSet.has(normalizedTag)) {
                neighborsToUnhide.add(hiddenTag);
            }
        });

        neighborsToUnhide.forEach(n => {
            hiddenNodes.delete(n);
            hiddenNodeNeighbors.delete(n); // clean up snapshot once unhidden
        });
        const nodesToReactivate = new Set([normalizedTag, ...neighborsToUnhide]);
        nodesToReactivate.add(baseTargetTag);
        nodesToReactivate.forEach(tagValue => {
            if (!tagValue) return;
            if (!activeDiagramAssetTags.includes(tagValue)) {
                activeDiagramAssetTags.push(tagValue);
            }
        });

        const updated = addExpansionDirection(normalizedTag, direction);
        // Pass the freshly-unhidden nodes as forceIncludeTags so they are
        // guaranteed to appear in sortedDiscoveredTags and reach activeDiagramAssetTags,
        // even if the backend doesn't return their cables in this specific fetch.
        const forceInclude = new Set([normalizedTag, ...neighborsToUnhide]);
        const result = await fetchAndRenderDiagramAndCables(
            currentFilters.targetTag,
            currentFilters.direction,
            currentFilters.cableType,
            currentFilters.protocol,
            currentFilters.cableId,
            false,
            forceInclude
        );
        const discovered = result?.newlyDiscoveredCount || 0;
        const key = `${normalizedTag}::${direction}`;
        const hasNewBefore = expansionResultLog.get(key) || false;
        if (!updated && !wasHidden && discovered === 0 && !hasNewBefore) {
            setDiagramStatus(`No additional ${direction === 'in' ? 'in-bound' : 'out-bound'} connections were found for ${normalizedTag}.`, "warn");
        } else {
            clearDiagramStatus();
            if (discovered > 0) {
                expansionResultLog.set(key, true);
            }
        }
    }

    async function handleAddConnectedViaRoute(tag, mode) {
        if (!(currentFilters.targetTag || currentFilters.cableId)) return;
        const displayTag = tag.trim();
        if (!displayTag) return;
        const tagLower = displayTag.toLowerCase();

        // Fetch all cables for this node including internal route cables.
        const params = new URLSearchParams();
        params.append("target_tag", displayTag);
        params.append("direction", "both");
        params.append("exclude_internal_routes", "false");
        params.append("include_logical_routes", "true");
        params.append("include_physical_routes", "true");
        params.append("include_passthroughs", "true");

        let allCables = [];
        try {
            const resp = await fetch(`${API_BASE_URL}/cables/filter?${params.toString()}`);
            if (!resp.ok) {
                setDiagramStatus(`Failed to fetch route data for ${displayTag}.`, "error");
                return;
            }
            const payload = await resp.json();
            allCables = Array.isArray(payload) ? payload : (payload.cables || []);
        } catch (e) {
            console.error("Error fetching route cables:", e);
            setDiagramStatus(`Error fetching route data for ${displayTag}: ${e.message}`, "error");
            return;
        }

        // Internal route/passthrough cables: SrcTag == DstTag == this node.
        const routeCables = allCables.filter(c => {
            const src = (c.SrcTag || '').trim().toLowerCase();
            const dst = (c.DstTag || '').trim().toLowerCase();
            const type = (c.Type || '').toLowerCase();
            return src === tagLower && dst === tagLower &&
                   (type.includes('route') || type.includes('passthrough'));
        });

        // All external inbound cables (arrive at this node from elsewhere).
        const allInbound = allCables.filter(c => {
            const src = (c.SrcTag || '').trim().toLowerCase();
            const dst = (c.DstTag || '').trim().toLowerCase();
            return dst === tagLower && src !== tagLower;
        });

        // All external outbound cables (leave this node for elsewhere).
        const allOutbound = allCables.filter(c => {
            const src = (c.SrcTag || '').trim().toLowerCase();
            const dst = (c.DstTag || '').trim().toLowerCase();
            return src === tagLower && dst !== tagLower;
        });

        // Cable IDs currently shown in the diagram — used to restrict the "anchor" side
        // of the traversal to only connections the user can actually see.
        const shownCableIds = new Set(
            currentDiagramCableData.map(c => (c.Tag || '').trim()).filter(Boolean)
        );

        const tagsToAdd = new Set();
        // relevantCableIds: cable IDs that are the specific route-identified connections.
        // All other cables between newly added nodes and this node will be hidden.
        const relevantCableIds = new Set();

        if (mode === 'inbound_for_outbound') {
            // Anchor: outbound cables that are currently shown in the diagram.
            const visibleOutbound = allOutbound.filter(
                c => shownCableIds.has((c.Tag || '').trim())
            );
            const outboundSrcPorts = new Set(
                visibleOutbound.map(c => (c.SrcPort || '').trim().toLowerCase()).filter(Boolean)
            );
            const relevantInboundPorts = new Set();
            routeCables.forEach(r => {
                const isPassthrough = (r.Type || '').toLowerCase().includes('passthrough');
                const srcPort = (r.SrcPort || '').trim().toLowerCase();
                const dstPort = (r.DstPort || '').trim().toLowerCase();
                // Normal direction: outbound SrcPort matches route DstPort → yield route SrcPort
                if (outboundSrcPorts.has(dstPort) && srcPort) relevantInboundPorts.add(srcPort);
                // Reverse direction for passthroughs (signal is bi-directional)
                if (isPassthrough && outboundSrcPorts.has(srcPort) && dstPort) relevantInboundPorts.add(dstPort);
            });
            allInbound.forEach(c => {
                const dstPort = (c.DstPort || '').trim().toLowerCase();
                const srcTag = (c.SrcTag || '').trim();
                if (relevantInboundPorts.has(dstPort) && srcTag && srcTag.toUpperCase() !== 'NAN') {
                    tagsToAdd.add(srcTag);
                    if (c.Tag) relevantCableIds.add(c.Tag.trim());
                }
            });
        } else {
            // outbound_for_inbound:
            // Anchor: inbound cables that are currently shown in the diagram.
            const visibleInbound = allInbound.filter(
                c => shownCableIds.has((c.Tag || '').trim())
            );
            const inboundDstPorts = new Set(
                visibleInbound.map(c => (c.DstPort || '').trim().toLowerCase()).filter(Boolean)
            );
            const relevantOutboundPorts = new Set();
            routeCables.forEach(r => {
                const isPassthrough = (r.Type || '').toLowerCase().includes('passthrough');
                const srcPort = (r.SrcPort || '').trim().toLowerCase();
                const dstPort = (r.DstPort || '').trim().toLowerCase();
                // Normal direction: inbound DstPort matches route SrcPort → yield route DstPort
                if (inboundDstPorts.has(srcPort) && dstPort) relevantOutboundPorts.add(dstPort);
                // Reverse direction for passthroughs (signal is bi-directional)
                if (isPassthrough && inboundDstPorts.has(dstPort) && srcPort) relevantOutboundPorts.add(srcPort);
            });
            allOutbound.forEach(c => {
                const srcPort = (c.SrcPort || '').trim().toLowerCase();
                const dstTag = (c.DstTag || '').trim();
                if (relevantOutboundPorts.has(srcPort) && dstTag && dstTag.toUpperCase() !== 'NAN') {
                    tagsToAdd.add(dstTag);
                    if (c.Tag) relevantCableIds.add(c.Tag.trim());
                }
            });
        }

        // Expansion direction: inbound sources need their outbound expanded (to reveal the
        // cable going to the route device); outbound destinations need inbound expanded.
        const expansionDir = mode === 'inbound_for_outbound' ? 'out' : 'in';

        // For each newly added node, fetch ALL its cables in the expansion direction and
        // hide every one except the route-identified cable(s). This covers cables from
        // third-party nodes (e.g. 2308-1124 → 2601-2800) that aren't in the route-device's
        // allCables set and would otherwise slip through.
        if (relevantCableIds.size > 0) {
            for (const newTag of tagsToAdd) {
                const fetchParams = new URLSearchParams({
                    target_tag: newTag,
                    direction: expansionDir,
                    exclude_internal_routes: 'true'
                });
                try {
                    const resp = await fetch(`${API_BASE_URL}/cables/filter?${fetchParams.toString()}`);
                    if (resp.ok) {
                        const payload = await resp.json();
                        const newNodeCables = Array.isArray(payload) ? payload : (payload.cables || []);
                        newNodeCables.forEach(c => {
                            const cableId = (c.Tag || '').trim();
                            if (cableId && !relevantCableIds.has(cableId)) {
                                hiddenCables.add(cableId);
                            }
                        });
                    }
                } catch (e) {
                    console.error(`Error fetching cables for ${newTag}:`, e);
                }
            }
        }

        const label = mode === 'inbound_for_outbound' ? 'inbound' : 'outbound';

        if (tagsToAdd.size === 0) {
            const hint = routeCables.length === 0
                ? ` (${displayTag} has no internal route or passthrough cables — right-click the patch panel or matrix switcher that contains the route)`
                : '';
            setDiagramStatus(`No ${label} connections found via routes for ${displayTag}.${hint}`, "warn");
            return;
        }

        // Unhide any of the found nodes that were previously hidden.
        tagsToAdd.forEach(t => {
            hiddenNodes.delete(t);
            hiddenNodeNeighbors.delete(t);
        });

        tagsToAdd.forEach(t => {
            addExpansionDirection(t, expansionDir);
            if (!activeDiagramAssetTags.includes(t)) {
                activeDiagramAssetTags.push(t);
            }
        });

        await fetchAndRenderDiagramAndCables(
            currentFilters.targetTag,
            currentFilters.direction,
            currentFilters.cableType,
            currentFilters.protocol,
            currentFilters.cableId,
            false,
            tagsToAdd
        );
        clearDiagramStatus();
    }

    function initializeExpansionMap(targetTag, direction) {
        nodeExpansionMap.clear();
        addExpansionDirection(targetTag, direction);
    }

    function addExpansionDirection(tag, direction) {
        const normalizedTag = tag ? tag.trim() : "";
        if (!normalizedTag) return false;
        if (!nodeExpansionMap.has(normalizedTag)) {
            nodeExpansionMap.set(normalizedTag, new Set());
        }
        const dirSet = nodeExpansionMap.get(normalizedTag);
        const prevSize = dirSet.size;
        if (direction === 'both') {
            dirSet.add('in');
            dirSet.add('out');
        } else if (direction === 'in') {
            dirSet.add('in');
        } else if (direction === 'out') {
            dirSet.add('out');
        } else {
            dirSet.add('in');
            dirSet.add('out');
        }
        return dirSet.size !== prevSize;
    }

    function setDiagramStatus(message, level = "info") {
        if (!diagramStatus) return;
        if (!message) {
            diagramStatus.textContent = "";
            diagramStatus.className = "status-message hidden";
            return;
        }
        const levelClass = {
            info: "status-info",
            success: "status-success",
            warn: "status-warn",
            error: "status-error"
        }[level] || "status-info";
        diagramStatus.className = `status-message ${levelClass}`;
        diagramStatus.textContent = message;
    }

    function clearDiagramStatus() {
        setDiagramStatus("");
    }

    function setCrosspointStatus(message, level = "info") {
        if (!crosspointStatus) return;
        if (!message) {
            crosspointStatus.textContent = "";
            crosspointStatus.className = "status-message hidden";
            return;
        }
        const levelClass = {
            info: "status-info",
            success: "status-success",
            warn: "status-warn",
            error: "status-error"
        }[level] || "status-info";
        crosspointStatus.className = `status-message ${levelClass}`;
        crosspointStatus.textContent = message;
    }

    function populateCrosspointProtocolOptions(options, selectedValue) {
        if (!crosspointProtocolSelect) {
            return;
        }
        const fallbackOptions = options && options.length ? options : [{ value: "", label: "All Protocols" }];
        crosspointProtocolSelect.innerHTML = "";
        fallbackOptions.forEach(option => {
            const opt = document.createElement("option");
            opt.value = option.value ?? "";
            opt.textContent = option.label || option.value || "All Protocols";
            crosspointProtocolSelect.appendChild(opt);
        });
        if (selectedValue) {
            crosspointProtocolSelect.value = selectedValue;
        } else {
            crosspointProtocolSelect.selectedIndex = 0;
        }
    }

    function renderCrosspointMatrix(data) {
        if (!crosspointMatrixContainer) {
            return;
        }
        const rows = Array.isArray(data?.rows) ? data.rows : [];
        const columns = Array.isArray(data?.columns) ? data.columns : [];
        const matrix = Array.isArray(data?.matrix) ? data.matrix : [];
        if (!rows.length || !columns.length) {
            crosspointMatrixContainer.innerHTML = "<p>No connections found between the selected assets.</p>";
            return;
        }
        const table = document.createElement("table");
        table.className = "crosspoint-table";
        const thead = document.createElement("thead");
        const headerRow = document.createElement("tr");
        const cornerCell = document.createElement("th");
        cornerCell.className = "row-header";
        cornerCell.textContent = `${data?.source_tag || "Source"} → ${data?.target_tag || "Target"}`;
        headerRow.appendChild(cornerCell);
        columns.forEach(col => {
            const th = document.createElement("th");
            th.textContent = col.label || col.port || "";
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = document.createElement("tbody");
        rows.forEach((row, rowIndex) => {
            const tr = document.createElement("tr");
            const rowHeader = document.createElement("td");
            rowHeader.className = "row-header";
            rowHeader.textContent = row.label || row.port || "";
            tr.appendChild(rowHeader);
            columns.forEach((col, colIndex) => {
                const td = document.createElement("td");
                const hasConnection = Boolean(matrix[rowIndex]?.[colIndex]);
                td.className = `crosspoint-cell ${hasConnection ? "has-connection" : "no-connection"}`;
                td.textContent = hasConnection ? "✔" : "";
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        crosspointMatrixContainer.innerHTML = "";
        crosspointMatrixContainer.appendChild(table);
    }

    async function initializeDiagramFieldSelects() {
        if (!nodeFieldsSelect || !edgeFieldsSelect) {
            return;
        }
        try {
            const response = await fetch(`${API_BASE_URL}/diagram/options`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            const nodePayload = payload?.node || {};
            const edgePayload = payload?.edge || {};
            const crosspointPayload = payload?.crosspoint || {};

            nodeFieldDefaults = Array.isArray(nodePayload.defaults) && nodePayload.defaults.length
                ? [...nodePayload.defaults]
                : [...DEFAULT_NODE_FIELDS];
            edgeFieldDefaults = Array.isArray(edgePayload.defaults) && edgePayload.defaults.length
                ? [...edgePayload.defaults]
                : [...DEFAULT_EDGE_FIELDS];
            crosspointHeaderDefaults = Array.isArray(crosspointPayload.defaults) && crosspointPayload.defaults.length
                ? [...crosspointPayload.defaults]
                : [...DEFAULT_CROSSPOINT_FIELDS];

            const nodeOptions = Array.isArray(nodePayload.options) && nodePayload.options.length
                ? nodePayload.options
                : buildFallbackOptions(nodeFieldDefaults);
            const edgeOptions = Array.isArray(edgePayload.options) && edgePayload.options.length
                ? edgePayload.options
                : buildFallbackOptions(edgeFieldDefaults);
            const crosspointOptions = Array.isArray(crosspointPayload.options) && crosspointPayload.options.length
                ? crosspointPayload.options
                : buildFallbackOptions(crosspointHeaderDefaults);

            populateFieldSelect(nodeFieldsSelect, nodeOptions, nodeFieldDefaults);
            populateFieldSelect(edgeFieldsSelect, edgeOptions, edgeFieldDefaults);
            if (crosspointHeaderFields) {
                populateFieldSelect(crosspointHeaderFields, crosspointOptions, crosspointHeaderDefaults);
            }
        } catch (error) {
            console.error("Error loading diagram field options:", error);
            populateFieldSelect(nodeFieldsSelect, buildFallbackOptions(nodeFieldDefaults), nodeFieldDefaults);
            populateFieldSelect(edgeFieldsSelect, buildFallbackOptions(edgeFieldDefaults), edgeFieldDefaults);
            if (crosspointHeaderFields) {
                populateFieldSelect(crosspointHeaderFields, buildFallbackOptions(crosspointHeaderDefaults), crosspointHeaderDefaults);
            }
        }
    }

    async function initializeAssetTagSelects() {
        if (!crosspointSourceSelect || !crosspointTargetSelect) {
            console.log("initializeAssetTagSelects: Crosspoint select elements not found.");
            return;
        }
        try {
            console.log("initializeAssetTagSelects: Fetching asset tags from API.");
            const response = await fetch(`${API_BASE_URL}/assets/tags`);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP ${response.status}`);
            }
            const data = await response.json();
            assetTagOptions = Array.isArray(data.tags) ? data.tags : [];
            console.log(`initializeAssetTagSelects: Fetched ${assetTagOptions.length} asset tags.`);
        } catch (error) {
            console.error("Error loading asset tags:", error);
            assetTagOptions = [];
        }
        assetTagLookup.clear();
        assetTagOptions.forEach(tag => {
            if (!tag) return;
            assetTagLookup.set(tag.trim().toUpperCase(), tag);
        });
        console.log(`initializeAssetTagSelects: Populated assetTagLookup with ${assetTagLookup.size} entries.`);
        populateAssetSelect(crosspointSourceSelect, "Select Source Asset");
        populateAssetSelect(crosspointTargetSelect, "Select Target Asset");
        if (crosspointSourceInput && crosspointSourceInput.value.trim()) {
            handleAssetInputChange("source", crosspointSourceInput.value.trim());
        }
        if (crosspointTargetInput && crosspointTargetInput.value.trim()) {
            handleAssetInputChange("target", crosspointTargetInput.value.trim());
        }
    }

    async function initializeAssetColumnSelect() {
        if (!assetColumnSelect) {
            return;
        }
        try {
            const response = await fetch(`${API_BASE_URL}/assets/columns`);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP ${response.status}`);
            }
            const payload = await response.json();
            const columnOptions = Array.isArray(payload?.columns) && payload.columns.length
                ? payload.columns
                : buildFallbackOptions(assetColumnDefaults);
            assetColumnDefaults = Array.isArray(payload?.defaults) && payload.defaults.length
                ? payload.defaults
                : [...ASSET_TABLE_DEFAULT_COLUMNS];
            populateFieldSelect(assetColumnSelect, columnOptions, assetColumnDefaults);
        } catch (error) {
            console.error("Error loading asset column metadata:", error);
            populateFieldSelect(assetColumnSelect, buildFallbackOptions(assetColumnDefaults), assetColumnDefaults);
        }
    }

    function populateFieldSelect(selectElement, options, defaults) {
        if (!selectElement) {
            return;
        }
        selectElement.innerHTML = "";
        const seen = new Set();
        options.forEach(option => {
            if (!option || !option.value || seen.has(option.value)) {
                return;
            }
            const opt = document.createElement("option");
            opt.value = option.value;
            opt.textContent = option.label || humanizeFieldLabel(option.value);
            opt.selected = option.selected ?? defaults.includes(option.value);
            selectElement.appendChild(opt);
            seen.add(option.value);
        });
        // Ensure all defaults exist even if backend omitted them for some reason
        defaults.forEach(value => {
            if (seen.has(value)) {
                return;
            }
            const opt = document.createElement("option");
            opt.value = value;
            opt.textContent = humanizeFieldLabel(value);
            opt.selected = true;
            selectElement.appendChild(opt);
            seen.add(value);
        });
    }

    function buildFallbackOptions(fields) {
        return fields.map(value => ({
            value,
            label: humanizeFieldLabel(value),
            selected: true
        }));
    }

    function populateAssetSelect(selectElement, placeholderText, optionsList) {
        if (!selectElement) return;
        const sourceList = Array.isArray(optionsList) && optionsList.length ? optionsList : assetTagOptions;
        selectElement.innerHTML = "";
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = placeholderText || "Select Asset";
        selectElement.appendChild(placeholder);
        sourceList.forEach(tag => {
            const opt = document.createElement("option");
            opt.value = tag;
            opt.textContent = tag;
            selectElement.appendChild(opt);
        });
    }

    function resolveAssetDisplay(value) {
        console.log(`resolveAssetDisplay: value=${value}`);
        if (!value) return null;
        const normalized = value.trim().toUpperCase();
        const resolved = assetTagLookup.get(normalized);
        console.log(`resolveAssetDisplay: normalized=${normalized}, resolved=${resolved}`);
        return resolved || null;
    }

    async function handleAssetInputChange(side, value) {
        console.log(`handleAssetInputChange: side=${side}, value=${value}`);
        if (!value) {
            console.log("handleAssetInputChange: value is empty, resetting inputs.");
            resetCrosspointInputs(false);
            return;
        }
        await assetTagsReadyPromise;
        const otherSide = side === "source" ? "target" : "source";
        const display = resolveAssetDisplay(value);
        console.log(`handleAssetInputChange: resolved display for ${value} is ${display}`);
        if (!display) {
            console.log(`handleAssetInputChange: ${value} is not a complete asset tag, setting other side to text mode.`);
            setCrosspointControlMode(otherSide, "text");
            return;
        }
        setCrosspointInputValue(side, display);
        setCrosspointControlMode(otherSide, "select");
        try {
            await updateOppositeOptions(side, display);
        } catch (error) {
            console.error("Error updating cross-point dropdown:", error);
            setCrosspointControlMode(otherSide, "text");
        }
    }

    function handleAssetSelectChange(side) {
        const select = side === "source" ? crosspointSourceSelect : crosspointTargetSelect;
        if (!select) return;
        const value = select.value;
        if (!value) {
            resetCrosspointInputs(false);
            return;
        }
        setCrosspointInputValue(side, value);
        updateOppositeOptions(side, value).catch(error => {
            console.error("Error updating cross-point dropdown:", error);
        });
    }

    function setCrosspointControlMode(side, mode, optionsList) {
        const input = side === "source" ? crosspointSourceInput : crosspointTargetInput;
        const select = side === "source" ? crosspointSourceSelect : crosspointTargetSelect;
        if (!input || !select) return;
        if (mode === "select" && (assetTagOptions.length || (optionsList && optionsList.length))) {
            populateAssetSelect(select, side === "source" ? "Select Source Asset" : "Select Target Asset", optionsList);
            const resolved = resolveAssetDisplay(input.value);
            if (resolved) {
                select.value = resolved;
            } else {
                select.value = "";
            }
            input.classList.add("hidden");
            select.classList.remove("hidden");
        } else {
            input.classList.remove("hidden");
            select.classList.add("hidden");
        }
    }

    function resetCrosspointInputs(clearValues = false) {
        setCrosspointControlMode("source", "text");
        setCrosspointControlMode("target", "text");
        if (crosspointSourceSelect) {
            populateAssetSelect(crosspointSourceSelect, "Select Source Asset");
            crosspointSourceSelect.value = "";
        }
        if (crosspointTargetSelect) {
            populateAssetSelect(crosspointTargetSelect, "Select Target Asset");
            crosspointTargetSelect.value = "";
        }
        if (clearValues) {
            if (crosspointSourceInput) crosspointSourceInput.value = "";
            if (crosspointTargetInput) crosspointTargetInput.value = "";
            lastCrosspointQuery = null;
        }
    }

    function getCrosspointValue(side) {
        const input = side === "source" ? crosspointSourceInput : crosspointTargetInput;
        const select = side === "source" ? crosspointSourceSelect : crosspointTargetSelect;
        if (select && !select.classList.contains("hidden") && select.value) {
            return select.value.trim();
        }
        return input ? input.value.trim() : "";
    }

    function humanizeFieldLabel(value) {
        if (!value) return "";
        if (FALLBACK_FIELD_LABELS[value]) {
            return FALLBACK_FIELD_LABELS[value];
        }
        const spaced = value.replace(/_/g, " ").replace(/\s+/g, " ").trim();
        return spaced.split(" ").map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
    }

    function getSelectedOptions(selectElement, fallback = []) {
        if (!selectElement) return [...fallback];
        const values = Array.from(selectElement.selectedOptions).map(opt => opt.value);
        return values.length ? values : [...fallback];
    }

    // --- Utility: Render Connections Table ---
    function humanizeConnectionsFieldLabel(value) {
        if (!value) return "";
        if (FALLBACK_FIELD_LABELS[value]) {
            return FALLBACK_FIELD_LABELS[value];
        }
        const spaced = value.replace(/([A-Z])/g, ' $1').trim();
        return spaced.charAt(0).toUpperCase() + spaced.slice(1);
    }

    function renderConnectionsTable(data, container, tableId, title, labelOverrides = {}) {
        if (!container) return;

        container.innerHTML = ''; // Clear previous content

        if (!data || !Array.isArray(data) || data.length === 0) {
            container.innerHTML = `<p style="padding:var(--space-3) var(--space-4);color:var(--color-text-muted);font-size:14px;">No ${title.toLowerCase()} found for this asset.</p>`;
            return;
        }

        const table = document.createElement("table");
        table.className = "connections-table";
        const thead = document.createElement("thead");
        const tbody = document.createElement("tbody");

        // Create table headers
        const headers = Object.keys(data[0]);
        const headerRow = document.createElement("tr");
        headers.forEach(headerText => {
            const th = document.createElement("th");
            th.textContent = labelOverrides[headerText] || humanizeConnectionsFieldLabel(headerText);
            th.dataset.column = headerText;
            th.classList.add('sortable');
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        // Sort data based on current state
        const currentSortState = tableSortStates[tableId];
        if (currentSortState.column) {
            data.sort((a, b) => {
                const valA = a[currentSortState.column] ?? "";
                const valB = b[currentSortState.column] ?? "";
                let comparison = 0;
                if (valA > valB) comparison = 1;
                else if (valA < valB) comparison = -1;
                return currentSortState.direction === 'desc' ? comparison * -1 : comparison;
            });
        }

        // Create table rows
        data.forEach(rowData => {
            const row = document.createElement("tr");
            headers.forEach(headerText => {
                const td = document.createElement("td");
                td.textContent = rowData[headerText];
                row.appendChild(td);
            });
            tbody.appendChild(row);
        });
        table.appendChild(tbody);

        container.appendChild(table);

        // Add event listeners to headers for sorting
        thead.querySelectorAll('th.sortable').forEach(header => {
            header.addEventListener('click', () => {
                const column = header.dataset.column;
                let direction = 'asc';

                if (tableSortStates[tableId].column === column && tableSortStates[tableId].direction === 'asc') {
                    direction = 'desc';
                }

                tableSortStates[tableId] = { column, direction };
                // Re-render the specific table
                renderConnectionsTable(data, container, tableId, title);
            });
        });
    }

    // --- Utility: Render Table ---
    function renderTable(data, container, tableId) { // Added tableId parameter
        if (!data || data.length === 0) {
            container.innerHTML = "<p>No results found.</p>";
            return;
        }

        const table = document.createElement("table");
        const thead = document.createElement("thead");
        const tbody = document.createElement("tbody");

        // Create table headers
        const headers = Object.keys(data[0]);
        const headerRow = document.createElement("tr");
        headers.forEach(headerText => {
            const th = document.createElement("th");
            th.textContent = headerText;
            th.dataset.column = headerText; // Store column name in dataset
            th.classList.add('sortable'); // Add class for styling
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        // Sort data based on current state
        // Initialize sort state if it doesn't exist
        if (!tableSortStates[tableId]) {
            tableSortStates[tableId] = { column: null, direction: 'asc' };
        }
        const currentSortState = tableSortStates[tableId];
        if (currentSortState.column) {
            data.sort((a, b) => {
                const valA = a[currentSortState.column];
                const valB = b[currentSortState.column];
                let comparison = 0;
                if (valA > valB) comparison = 1;
                else if (valA < valB) comparison = -1;
                return currentSortState.direction === 'desc' ? comparison * -1 : comparison;
            });
        }

        // Create table rows (same as before)
        data.forEach(rowData => {
            const row = document.createElement("tr");
            headers.forEach(headerText => {
                const td = document.createElement("td");

                // Special handling for IssueID in knowledge base issues table
                if (tableId === "knowledgeBaseIssuesTable" && headerText === "IssueID") {
                    const issueId = rowData[headerText];
                    if (issueId) {
                        td.style.cursor = "pointer";
                        td.style.color = "#0066cc";
                        td.style.textDecoration = "underline";
                        td.textContent = issueId;
                        td.addEventListener("click", async () => {
                            // Switch to Knowledge Base tab
                            document.querySelector('.tab-button[data-tab="knowledgeBase"]').click();

                            // Populate the IssueID search field and clear others
                            if (kbIssueIdSearch) kbIssueIdSearch.value = issueId;
                            if (kbTagSearch) kbTagSearch.value = '';
                            if (kbFreeformSearch) kbFreeformSearch.value = '';
                            if (kbActiveIssueTags) Array.from(kbActiveIssueTags.options).forEach(o => { o.selected = false; });

                            // Perform the search
                            await performKBSearch();
                        });
                    } else {
                        td.textContent = rowData[headerText];
                    }
                } else {
                    td.textContent = rowData[headerText];
                }

                row.appendChild(td);
            });
            tbody.appendChild(row);
        });
        table.appendChild(tbody);

        container.innerHTML = ""; // Clear previous content
        container.appendChild(table);

        // Add event listeners to headers for sorting
        thead.querySelectorAll('th').forEach(header => {
            header.addEventListener('click', () => {
                const column = header.dataset.column;
                let direction = 'asc';

                if (tableSortStates[tableId].column === column && tableSortStates[tableId].direction === 'asc') {
                    direction = 'desc';
                }

                tableSortStates[tableId] = { column, direction };
                renderTable(data, container, tableId); // Re-render with sorted data
            });
        });
    }

    // Sets the global target asset and refreshes all tabs that show single-asset data.
    // Two-asset tabs (Cross-point, Signal Path) get their first/source field pre-filled.
    // Does NOT switch tabs — callers decide navigation.
    async function setGlobalTargetAsset(tag) {
        if (!tag) return;
        globalTargetAsset = tag;
        updateUrlHash(tag);

        // Fill all single-asset inputs
        if (assetDetailsTagInput) assetDetailsTagInput.value = tag;
        if (locationAssetTagInput) locationAssetTagInput.value = tag;
        if (targetTagFilter) targetTagFilter.value = tag;

        // Pre-fill first field of two-asset tabs
        if (signalPathSource) signalPathSource.value = tag;
        if (crosspointSourceInput) {
            crosspointSourceInput.value = tag;
            handleAssetInputChange("source", tag);
        }

        // Update and reload Knowledge Base for this asset
        if (kbTagSearch) kbTagSearch.value = tag;
        performKBSearch();

        // Reset diagram state
        baseTargetTag = tag;
        hiddenNodes.clear();
        hiddenCables.clear();
        hiddenNodeNeighbors.clear();
        allKnownDiagramAssetTags.clear();
        expansionResultLog.clear();
        currentFilters = {
            targetTag: tag,
            cableId: "",
            direction: directionFilter.value,
            cableType: cableTypeFilter.value,
            protocol: protocolFilter ? protocolFilter.value.trim() : ""
        };
        initializeExpansionMap(baseTargetTag, currentFilters.direction);

        // Load all single-asset tabs in parallel (fire-and-forget; each manages its own UI state)
        fetchAndRenderAssetDetails(tag);
        fetchAndRenderRackProfile(tag).catch(e => console.error("rack profile error:", e));
        if (document.getElementById("networkViewer")?.classList.contains("active")) {
            fetchAndRenderNetworkDetails(tag);
        }
        fetchAndRenderDiagramAndCables(
            currentFilters.targetTag,
            currentFilters.direction,
            currentFilters.cableType,
            currentFilters.protocol,
            currentFilters.cableId,
            true
        );
    }

    async function fetchAndRenderAssetDetails(assetTag) {
        const assetPropertiesContainer = document.getElementById(ASSET_PROPERTIES_CONTAINER_ID);
        const inputPartnersList = document.getElementById(INPUT_PARTNERS_LIST_ID);
        const outputPartnersList = document.getElementById(OUTPUT_PARTNERS_LIST_ID);
        const knowledgeBaseIssuesTableContainer = document.getElementById(KNOWLEDGE_BASE_ISSUES_TABLE_ID);
        const manualsContainer = document.getElementById(ASSET_MANUALS_CONTAINER_ID);
        const licensesContainer = document.getElementById(ASSET_LICENSES_CONTAINER_ID);

        // Clear previous content from individual containers only
        if (assetPropertiesContainer) assetPropertiesContainer.innerHTML = '<p>Loading asset details...</p>';
        if (inputPartnersList) inputPartnersList.innerHTML = '';
        if (outputPartnersList) outputPartnersList.innerHTML = '';
        if (knowledgeBaseIssuesTableContainer) knowledgeBaseIssuesTableContainer.innerHTML = '';
        if (manualsContainer) manualsContainer.innerHTML = '';
        if (licensesContainer) licensesContainer.innerHTML = '';

        document.querySelector(`.tab-button[data-tab="${ASSET_DETAILS_TAB_ID}"]`).click(); // Switch to asset details tab

        try {
            const [detailsResponse, manualsResponse] = await Promise.all([
                fetch(`${API_BASE_URL}/assets/${encodeURIComponent(assetTag)}/details`),
                fetch(`${API_BASE_URL}/manuals/${encodeURIComponent(assetTag)}`),
            ]);

            if (!detailsResponse.ok) {
                const errorData = await detailsResponse.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP error! status: ${detailsResponse.status}`);
            }
            const data = await detailsResponse.json();
            const manualsData = manualsResponse.ok ? await manualsResponse.json() : null;

            renderAssetProperties(data.asset, assetPropertiesContainer);
            renderPartnersList(data.input_partners, inputPartnersList, "input");
            renderPartnersList(data.output_partners, outputPartnersList, "output");
            renderAssetNetwork(data.network || [], document.getElementById("assetNetworkContainer"));
            renderKnowledgeBaseIssues(data.knowledge_base_issues, knowledgeBaseIssuesTableContainer);
            renderManuals(manualsData, manualsContainer);
            renderLicenses(data.licenses || [], licensesContainer);

            // Update location tab in background
            fetchAndRenderRackProfile(assetTag).catch(e => console.error("rack profile error:", e));
        } catch (error) {
            console.error("Error fetching asset details:", error);
            if (assetPropertiesContainer) assetPropertiesContainer.innerHTML = `<p style="color: red;">Error loading asset details: ${error.message}</p>`;
            if (inputPartnersList) inputPartnersList.innerHTML = '';
            if (outputPartnersList) outputPartnersList.innerHTML = '';
            if (knowledgeBaseIssuesTableContainer) knowledgeBaseIssuesTableContainer.innerHTML = '';
        }
    }

    function renderManuals(data, container) {
        if (!container) return;
        container.innerHTML = '';
        if (!data || !data.manuals || data.manuals.length === 0) {
            container.innerHTML = '<p class="manuals-empty">No manuals available.</p>';
            return;
        }
        const list = document.createElement('ul');
        list.className = 'manuals-list';
        data.manuals.forEach(manual => {
            const li = document.createElement('li');
            const a = document.createElement('a');
            a.href = manual.url;
            a.textContent = manual.name;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            li.appendChild(a);
            list.appendChild(li);
        });
        container.appendChild(list);
    }

    function renderLicenses(licenses, container) {
        if (!container) return;
        container.innerHTML = '';

        if (!licenses || licenses.length === 0) {
            container.innerHTML = '<p class="manuals-empty">No licenses associated with this asset.</p>';
            return;
        }

        const table = document.createElement('table');
        table.className = 'property-table licenses-table';

        const thead = document.createElement('thead');
        thead.innerHTML = '<tr><th>Name</th><th>Acquired By</th><th>Acquired Date</th><th>Terms</th><th>Expiry Terms</th><th>Expiry Date</th><th>Details</th></tr>';
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        licenses.forEach(lic => {
            const tr = document.createElement('tr');

            const fmt = v => v ? String(v).split('T')[0] : '';

            const detailsCell = lic.confidential
                ? '<span class="license-confidential" title="License details are confidential">🔒 Confidential</span>'
                : (lic.license_details
                    ? `<pre class="license-details-pre">${escapeHtml(lic.license_details)}</pre>`
                    : '—');

            tr.innerHTML = `
                <td>${escapeHtml(lic.name || '')}</td>
                <td>${escapeHtml(lic.acquired_by || '')}</td>
                <td>${escapeHtml(fmt(lic.acquired_date))}</td>
                <td>${escapeHtml(lic.terms || '')}</td>
                <td>${escapeHtml(lic.expiry_terms || '')}</td>
                <td>${escapeHtml(fmt(lic.expiry_date))}</td>
                <td>${detailsCell}</td>
            `;
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        container.appendChild(table);
    }

    function renderAssetProperties(asset, container) {
        if (!container || !asset) return;
        container.innerHTML = '<h3>Properties</h3>';

        const getValue = (key) => asset[key] || "";
        const hasValue = (key) => asset[key] && String(asset[key]).trim() !== "";

        // Define field groups
        const basicFields = ["AssetTag", "Type", "Category", "InService", "Manufacturer", "Model", "SN", "AcqYear", "EolYear", "Usage", "Desc"];
        const locationFields = ["Building", "Floor", "Room", "Sector", "Location", "Rack", "RackU", "RackHeight"];
        const financialFields = ["Qty", "UnitValue", "AcqValue", "Unit", "PurcDate", "PurcFrom", "Invoice"];
        const currencyFields = new Set(["UnitValue", "AcqValue"]);
        const dateOnlyFields = new Set(["PurcDate"]);
        const integerFields = new Set(["EolYear"]);
        const dispositionFields = ["Disposition", "DispositionDate", "DispositionDestination", "DispositionNotes"];

        const allGroupedFields = new Set([
            ...basicFields, ...locationFields, ...financialFields, ...dispositionFields
        ]);

        const content = document.createElement("div");
        content.className = "asset-properties-content";

        // Helper function to create a table with headers and values.
        // clickableFieldsMap: { fieldName: searchParamsObj } — fields that navigate to asset search on click.
        function createPropertyTable(fields, clickableFieldsMap = {}) {
            const fieldsWithValues = fields.filter(field => hasValue(field));
            if (fieldsWithValues.length === 0) return null;

            const table = document.createElement("table");
            table.className = "property-table";

            const thead = document.createElement("thead");
            const headerRow = document.createElement("tr");
            fieldsWithValues.forEach(field => {
                const th = document.createElement("th");
                th.textContent = humanizeFieldLabel(field);
                headerRow.appendChild(th);
            });
            thead.appendChild(headerRow);
            table.appendChild(thead);

            const tbody = document.createElement("tbody");
            const valueRow = document.createElement("tr");
            fieldsWithValues.forEach(field => {
                const td = document.createElement("td");
                const raw = getValue(field);
                let displayText;
                if (currencyFields.has(field)) {
                    const num = parseFloat(raw);
                    displayText = isNaN(num) ? raw : `$${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                } else if (dateOnlyFields.has(field)) {
                    displayText = raw ? String(raw).split('T')[0].split(' ')[0] : raw;
                } else if (integerFields.has(field)) {
                    const num = parseFloat(raw);
                    displayText = isNaN(num) ? raw : String(Math.round(num));
                } else {
                    displayText = raw;
                }

                if (clickableFieldsMap[field] && raw) {
                    const link = document.createElement("a");
                    link.href = "#";
                    link.className = "field-search-link";
                    link.textContent = displayText;
                    const searchParams = clickableFieldsMap[field];
                    link.addEventListener("click", (e) => {
                        e.preventDefault();
                        navigateToAssetSearch(searchParams);
                    });
                    td.appendChild(link);
                } else {
                    td.textContent = displayText;
                }
                valueRow.appendChild(td);
            });
            tbody.appendChild(valueRow);
            table.appendChild(tbody);

            return table;
        }

        // Basic Information Table
        const basicSection = document.createElement("div");
        basicSection.className = "property-section";
        basicSection.innerHTML = "<h4>Basic Information</h4>";

        // Row 1: AssetTag, Type, Category, InService
        const row1Table = createPropertyTable(["AssetTag", "Type", "Category", "InService"]);
        if (row1Table) basicSection.appendChild(row1Table);

        // Row 2: Manufacturer, Model, SN
        const row2ClickMap = {};
        if (getValue("Manufacturer")) row2ClickMap["Manufacturer"] = { manufacturer: getValue("Manufacturer"), in_service_only: false };
        if (getValue("Model")) row2ClickMap["Model"] = { model: getValue("Model"), in_service_only: false };
        const row2Table = createPropertyTable(["Manufacturer", "Model", "SN"], row2ClickMap);
        if (row2Table) basicSection.appendChild(row2Table);

        // Row 3: AcqYear, EolYear, Usage, Desc
        const row3Table = createPropertyTable(["AcqYear", "EolYear", "Usage", "Desc"]);
        if (row3Table) basicSection.appendChild(row3Table);

        content.appendChild(basicSection);

        // Location Table
        const hasLocation = locationFields.some(field => hasValue(field));
        if (hasLocation) {
            const locationSection = document.createElement("div");
            locationSection.className = "property-section";
            locationSection.innerHTML = "<h4>Location</h4>";

            const _b = getValue("Building");
            const _f = getValue("Floor");
            const _r = getValue("Room");
            const _s = getValue("Sector");
            const locationClickMap = {};
            if (_b) locationClickMap["Building"] = { building: _b, in_service_only: false };
            if (_f) locationClickMap["Floor"] = { building: _b, floor: _f, in_service_only: false };
            if (_r) locationClickMap["Room"] = { building: _b, floor: _f, room: _r, in_service_only: false };
            if (_s) locationClickMap["Sector"] = { building: _b, floor: _f, room: _r, sector: _s, in_service_only: false };
            const locationTable = createPropertyTable(locationFields, locationClickMap);
            if (locationTable) locationSection.appendChild(locationTable);

            content.appendChild(locationSection);
        }

        // Financial Table (including "Other" fields except EolYear which is already in Basic)
        const otherFields = Object.keys(asset).filter(key => !allGroupedFields.has(key) && hasValue(key));
        const allFinancialFields = [...financialFields, ...otherFields];

        const hasFinancial = allFinancialFields.some(field => hasValue(field));
        if (hasFinancial) {
            const financialSection = document.createElement("div");
            financialSection.className = "property-section";
            financialSection.innerHTML = "<h4>Financial</h4>";

            const financialClickMap = {};
            if (getValue("PurcFrom")) financialClickMap["PurcFrom"] = { purc_from: getValue("PurcFrom"), in_service_only: false };
            if (getValue("Invoice")) financialClickMap["Invoice"] = { invoice: getValue("Invoice"), in_service_only: false };
            const financialTable = createPropertyTable(allFinancialFields, financialClickMap);
            if (financialTable) financialSection.appendChild(financialTable);

            content.appendChild(financialSection);
        }

        // Disposition (only if Disposition is not "N")
        const disposition = getValue("Disposition").toUpperCase();
        if (disposition && disposition !== "N") {
            const dispSection = document.createElement("div");
            dispSection.className = "property-section";
            dispSection.innerHTML = "<h4>Disposition</h4>";

            const dispTable = createPropertyTable(dispositionFields);
            if (dispTable) dispSection.appendChild(dispTable);

            content.appendChild(dispSection);
        }

        container.appendChild(content);
    }

    function renderAssetNetwork(nics, container) {
        if (!container) return;
        container.innerHTML = "";
        if (!nics || nics.length === 0) {
            container.innerHTML = `<p class="network-empty">No network records found.</p>`;
            return;
        }

        const table = document.createElement("table");
        table.className = "network-table";
        table.innerHTML = `<thead><tr>
            <th>NIC</th><th>IP</th><th>MAC</th>
            <th>Monitor</th><th>Type</th><th>Usage</th><th>Services</th><th>Notes</th>
        </tr></thead>`;
        const tbody = document.createElement("tbody");

        // Protocols that use TCP ports but are not browser-accessible web services.
        const NON_WEB_PROTOCOLS = new Set(["pjlink", "osc", "midi"]);

        function renderServicesCell(services, ip) {
            if (!services) return "—";
            const parts = services.split(",").map(s => s.trim()).filter(Boolean);
            if (parts.length === 0) return "—";
            return parts.map(part => {
                const serviceMatch = part.match(/^(.+):(\d+)$/);
                if (serviceMatch && ip) {
                    const name = serviceMatch[1].toLowerCase();
                    const port = serviceMatch[2];
                    if (!NON_WEB_PROTOCOLS.has(name)) {
                        const href = `http://${ip}:${port}`;
                        return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener" class="network-url-link">${escapeHtml(part)}</a>`;
                    }
                }
                return escapeHtml(part);
            }).join("<br>");
        }

        nics.forEach(n => {
            const tr = document.createElement("tr");
            const missingIp = n.monitor && !n.ip;
            if (missingIp) tr.className = "network-row-warning";

            // Monitor cell
            const monCell = n.monitor
                ? `<span class="network-monitor-yes">Yes${missingIp ? " ⚠" : ""}</span>`
                : `<span class="network-monitor-no">No</span>`;

            // Services cell — web:<port> entries become clickable links
            const servicesCell = renderServicesCell(n.services, n.ip);

            tr.innerHTML = `
                <td>${escapeHtml(n.nic  || "—")}</td>
                <td class="network-ip">${escapeHtml(n.ip   || "—")}</td>
                <td class="network-mac">${escapeHtml(n.mac  || "—")}</td>
                <td>${monCell}</td>
                <td>${escapeHtml(n.static_reserved || "—")}</td>
                <td>${escapeHtml(n.usage || "—")}</td>
                <td class="network-services">${servicesCell}</td>
                <td>${escapeHtml(n.notes || "—")}</td>
            `;
            tbody.appendChild(tr);
        });

        table.appendChild(tbody);
        container.appendChild(table);
    }

    function renderPartnersList(partners, container, direction) {
        if (!container) return;
        container.innerHTML = ''; // Clear previous content
        if (!partners || partners.length === 0) {
            container.textContent = `No ${direction} partners found.`;
            return;
        }
        const ul = document.createElement("ul");
        ul.className = "partner-list";
        partners.forEach(partner => {
            const li = document.createElement("li");
            li.className = "partner-item";
            li.textContent = `${partner.AssetTag} (${partner.Manufacturer} ${partner.Model} - ${partner.Usage})`;
            li.dataset.assetTag = partner.AssetTag;
            li.addEventListener("click", (event) => {
                const newTargetTag = event.target.dataset.assetTag;
                if (newTargetTag) setGlobalTargetAsset(newTargetTag);
            });
            ul.appendChild(li);
        });
        container.appendChild(ul);
    }

    // ---- Rack Profile / Location Tab ----

    const locationAssetTagInput = document.getElementById("locationAssetTagInput");
    const viewLocationBtn = document.getElementById("viewLocationBtn");
    const printRackBtn = document.getElementById("printRackBtn");
    const locationStatus = document.getElementById("locationStatus");

    if (viewLocationBtn) {
        viewLocationBtn.addEventListener("click", () => {
            const tag = locationAssetTagInput ? locationAssetTagInput.value.trim() : "";
            if (tag) fetchAndRenderRackProfile(tag).catch(e => console.error("rack profile error:", e));
        });
    }
    if (printRackBtn) {
        printRackBtn.addEventListener("click", () => {
            document.body.classList.add("print-rack-mode");
            window.print();
            document.body.classList.remove("print-rack-mode");
        });
    }
    if (locationAssetTagInput) {
        locationAssetTagInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                const tag = locationAssetTagInput.value.trim();
                if (tag) fetchAndRenderRackProfile(tag).catch(e => console.error("rack profile error:", e));
            }
        });
    }

    async function fetchAndRenderRackProfile(assetTag) {
        const locationContent = document.getElementById("locationContent");
        if (!locationContent) return;

        if (locationAssetTagInput) locationAssetTagInput.value = assetTag;

        showLoadingSpinner(locationContent, "Loading location…");

        try {
            const encoded = encodeURIComponent(assetTag);
            const [rackResp, fpResp] = await Promise.all([
                fetch(`${API_BASE_URL}/assets/${encoded}/rack-profile`),
                fetch(`${API_BASE_URL}/location/floorplan?asset_tag=${encoded}`)
            ]);

            if (!rackResp.ok) {
                const err = await rackResp.json().catch(() => ({}));
                showEmptyState(locationContent, err.detail || `Asset not found: ${assetTag}`, "⚠️");
                return;
            }

            const rackData = await rackResp.json();
            const fpData   = fpResp.ok ? await fpResp.json().catch(() => null) : null;

            renderRackProfile(rackData, assetTag, locationContent, fpData);
        } catch (e) {
            console.error("fetchAndRenderRackProfile error:", e);
            showEmptyState(locationContent, `Error loading location: ${e.message}`, "⚠️");
        }
    }

    function openFloorplanLightbox(dataUrl, caption) {
        const overlay = document.createElement("div");
        overlay.className = "floorplan-lightbox";

        const img = document.createElement("img");
        img.src = dataUrl;
        img.alt = caption || "Floor plan";
        overlay.appendChild(img);

        if (caption) {
            const cap = document.createElement("div");
            cap.className = "floorplan-lightbox-caption";
            cap.textContent = caption;
            overlay.appendChild(cap);
        }

        const close = () => {
            overlay.remove();
            document.removeEventListener("keydown", onKey);
        };
        const onKey = (e) => { if (e.key === "Escape") close(); };
        overlay.addEventListener("click", close);
        document.addEventListener("keydown", onKey);
        document.body.appendChild(overlay);
    }

    function renderRackProfile(data, assetTag, container, fpData = null) {
        container.innerHTML = "";

        // Floorplan image (most specific available, embedded as data URL)
        if (fpData && fpData.image_data_url) {
            const fpSection = document.createElement("div");
            fpSection.className = "floorplan-section";

            const fpLabel = document.createElement("p");
            fpLabel.className = "floorplan-label";
            const parts = [fpData.building, fpData.floor, fpData.room].filter(v => v && v.trim());
            if (fpData.sector && String(fpData.sector).trim()) parts.push(`Sector ${fpData.sector}`);
            fpLabel.textContent = `Floor Plan — ${parts.join(" / ")}`;
            fpSection.appendChild(fpLabel);

            const img = document.createElement("img");
            img.src = fpData.image_data_url;
            img.alt = fpData.filename || "Floor plan";
            img.className = "floorplan-image";
            img.title = "Click to view full size";
            img.addEventListener("click", () => openFloorplanLightbox(fpData.image_data_url, fpLabel.textContent));
            fpSection.appendChild(img);

            container.appendChild(fpSection);
        }

        if (!data.rack_tag) {
            const msg = document.createElement("p");
            msg.className = "location-placeholder";
            msg.innerHTML = `Asset <strong>${escapeHtml(assetTag)}</strong> is not assigned to a rack.`;
            container.appendChild(msg);
            return;
        }

        const header = document.createElement("div");
        header.style.cssText = "margin-bottom:var(--space-4)";
        header.innerHTML = `<h3 style="margin:0 0 4px 0">Rack: ${escapeHtml(data.rack_tag)}</h3>` +
            (data.rack_height ? `<span style="font-size:13px;color:var(--color-text-muted)">${data.rack_height}U rack</span>` : "");
        container.appendChild(header);

        const front = data.devices.filter(d => d.face === "Front");
        const rear  = data.devices.filter(d => d.face === "Rear");

        const wrap = document.createElement("div");
        wrap.className = "rack-profile-container";

        if (front.length > 0 || rear.length > 0) {
            const maxU = Math.max(
                data.rack_height || 1,
                ...data.devices.map(d => d.u_start + d.u_height - 1)
            );
            if (front.length > 0) wrap.appendChild(buildRackPanel("Front", front, maxU, data.rack_height, assetTag));
            if (rear.length > 0)  wrap.appendChild(buildRackPanel("Rear",  rear,  maxU, data.rack_height, assetTag));
        } else {
            wrap.innerHTML = `<p class="location-placeholder">No racked devices found in ${escapeHtml(data.rack_tag)}.</p>`;
        }

        container.appendChild(wrap);
    }

    function buildRackPanel(faceLabel, devices, maxU, standardHeight, targetAssetTag) {
        const U_PX = 30;       // pixels per rack unit
        const LABEL_W = 32;    // width of U-number label column
        const RACK_W = 260;    // inner rack width
        const SVG_W = LABEL_W + RACK_W + 2;
        const SVG_H = maxU * U_PX + 2;

        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", `0 0 ${SVG_W} ${SVG_H}`);
        svg.setAttribute("xmlns", ns);

        // Background
        const bg = document.createElementNS(ns, "rect");
        bg.setAttribute("x", LABEL_W); bg.setAttribute("y", 0);
        bg.setAttribute("width", RACK_W); bg.setAttribute("height", SVG_H);
        bg.setAttribute("fill", "#ffffff"); bg.setAttribute("stroke", "#333"); bg.setAttribute("stroke-width", "1.5");
        svg.appendChild(bg);

        // U grid lines and labels (1 at bottom, maxU at top)
        for (let u = 1; u <= maxU; u++) {
            const y = SVG_H - u * U_PX;  // y of top edge of this U slot

            // Dotted grid line
            const line = document.createElementNS(ns, "line");
            line.setAttribute("x1", LABEL_W); line.setAttribute("x2", SVG_W);
            line.setAttribute("y1", y + U_PX); line.setAttribute("y2", y + U_PX);
            line.setAttribute("stroke", "#ccc"); line.setAttribute("stroke-dasharray", "3,3"); line.setAttribute("stroke-width", "0.5");
            svg.appendChild(line);

            // U number label
            const txt = document.createElementNS(ns, "text");
            txt.setAttribute("x", LABEL_W - 4); txt.setAttribute("y", y + U_PX - U_PX / 2 + 4);
            txt.setAttribute("text-anchor", "end"); txt.setAttribute("font-size", "9");
            txt.setAttribute("fill", "#666"); txt.setAttribute("font-family", "Inter,Arial,sans-serif");
            txt.textContent = u;
            svg.appendChild(txt);
        }

        // Devices
        devices.forEach(dev => {
            const yTop = SVG_H - (dev.u_start + dev.u_height - 1) * U_PX;
            const devH = dev.u_height * U_PX;
            const xLeft  = LABEL_W + Math.round(dev.x_start * RACK_W) + 1;
            const devW   = Math.round((dev.x_end - dev.x_start) * RACK_W) - 2;

            const isTarget = dev.asset_tag.toUpperCase() === targetAssetTag.toUpperCase();
            const isAboveStd = standardHeight && dev.u_start > standardHeight;
            let fillColor = faceLabel === "Front" ? "#bfdbfe" : "#bbf7d0";
            if (isTarget) fillColor = "#fde68a";
            if (isAboveStd) fillColor = "#fecaca";

            // Clickable group — navigates to Asset Details for this device
            const g = document.createElementNS(ns, "g");
            g.setAttribute("style", "cursor: pointer;");
            g.addEventListener("click", () => {
                setGlobalTargetAsset(dev.asset_tag);
                document.querySelector('.tab-button[data-tab="assetDetails"]').click();
            });

            // Native SVG tooltip
            const titleEl = document.createElementNS(ns, "title");
            titleEl.textContent = `${dev.asset_tag}${dev.usage ? " — " + dev.usage : ""}\nClick to view details`;
            g.appendChild(titleEl);

            const rect = document.createElementNS(ns, "rect");
            rect.setAttribute("x", xLeft); rect.setAttribute("y", yTop);
            rect.setAttribute("width", devW); rect.setAttribute("height", devH);
            rect.setAttribute("fill", fillColor); rect.setAttribute("stroke", "#333"); rect.setAttribute("stroke-width", "1");
            rect.setAttribute("rx", "2");
            g.appendChild(rect);

            // Label: asset tag + usage, centered, clipped
            const label = `${dev.asset_tag}${dev.usage ? "\n" + dev.usage : ""}`;
            const lines = label.split("\n").filter(Boolean);
            const lineH = 11;
            const totalTextH = lines.length * lineH;
            const textStartY = yTop + devH / 2 - totalTextH / 2 + lineH - 2;

            lines.forEach((line, i) => {
                if (devH < 10) return;
                const t = document.createElementNS(ns, "text");
                t.setAttribute("x", xLeft + devW / 2);
                t.setAttribute("y", textStartY + i * lineH);
                t.setAttribute("text-anchor", "middle");
                t.setAttribute("font-size", devH >= 24 ? "9" : "7");
                t.setAttribute("font-family", "Inter,Arial,sans-serif");
                t.setAttribute("fill", "#1e293b");
                const clip = document.createElementNS(ns, "clipPath");
                const clipId = `clip-${dev.asset_tag.replace(/[^a-z0-9]/gi, '')}-${i}-${faceLabel}`;
                clip.setAttribute("id", clipId);
                const clipRect = document.createElementNS(ns, "rect");
                clipRect.setAttribute("x", xLeft); clipRect.setAttribute("y", yTop);
                clipRect.setAttribute("width", devW); clipRect.setAttribute("height", devH);
                clip.appendChild(clipRect);
                svg.appendChild(clip);
                t.setAttribute("clip-path", `url(#${clipId})`);
                t.textContent = line;
                g.appendChild(t);
            });

            svg.appendChild(g);
        });

        const panel = document.createElement("div");
        panel.className = "rack-panel";

        const title = document.createElement("h3");
        title.textContent = faceLabel;
        panel.appendChild(title);

        const svgWrap = document.createElement("div");
        svgWrap.className = "rack-svg-wrap";
        svgWrap.appendChild(svg);
        panel.appendChild(svgWrap);
        return panel;
    }

    function renderKnowledgeBaseIssues(issues, container) {
        if (!container) return;
        container.innerHTML = '<h3>Relevant Knowledge Base Issues</h3>';
        if (!issues || issues.length === 0) {
            container.innerHTML += "<p>No relevant knowledge base issues found.</p>";
            return;
        }
        renderTable(issues, container, "knowledgeBaseIssuesTable"); // Reuse renderTable
    }

    // Renders a KB text field with full markdown support, external links opening in a
    // new tab, and [[IssueID]] wiki-style cross-references rendered as clickable spans.
    function renderMarkdown(text) {
        if (!text) return '';
        if (typeof marked === 'undefined' || !marked.parse) {
            return escapeHtml(text);
        }

        // Pre-process [[IssueID]] cross-references before markdown parsing.
        // Encode them as a placeholder the markdown parser will pass through as-is.
        const processed = text.replace(/\[\[([^\]]+)\]\]/g, (_, id) => {
            const safeId = id.replace(/"/g, '&quot;');
            return `<span class="kb-crossref" data-id="${safeId}">${escapeHtml(id)}</span>`;
        });

        // Custom renderer: open all links in a new tab.
        const renderer = new marked.Renderer();
        const origLink = renderer.link.bind(renderer);
        renderer.link = (href, title, text) => {
            const html = origLink(href, title, text);
            return html.replace(/^<a /, '<a target="_blank" rel="noopener noreferrer" ');
        };

        return marked.parse(processed, { renderer });
    }

    function renderKBResults(issues) {
        if (!kbResultsContainer) return;

        kbResultsContainer.innerHTML = '';

        if (!issues || issues.length === 0) {
            showEmptyState(kbResultsContainer, "No knowledge base issues matched your criteria.", "📚");
            return;
        }

        const autoExpand = issues.length === 1;

        issues.forEach((issue, index) => {
            const issueSection = document.createElement('div');
            issueSection.className = 'kb-issue-section';

            // Create header (always visible)
            const header = document.createElement('div');
            header.className = 'kb-issue-header';
            header.innerHTML = `
                <span class="kb-issue-id">${escapeHtml(issue.IssueID || '')}</span>
                <span class="kb-issue-title">${escapeHtml(issue.Title || '')}</span>
                <span class="kb-expand-icon">${autoExpand ? '▼' : '▶'}</span>
            `;

            // Create details section (expandable)
            const details = document.createElement('div');
            details.className = autoExpand ? 'kb-issue-details expanded' : 'kb-issue-details';

            // Build the details content
            const fieldsToDisplay = [
                { label: 'Category', value: issue.Category },
                { label: 'Subcategory', value: issue.Subcategory },
                { label: 'Symptom', value: issue.Symptom },
                { label: 'Trigger Conditions', value: issue.TriggerConditions },
                { label: 'Likely Cause', value: issue.LikelyCause },
                { label: 'Recovery Steps', value: issue.RecoverySteps },
                { label: 'Applies to Asset Type', value: issue.AppliesToAssetType },
                { label: 'Applies to Asset Tag', value: issue.AppliesToAssetTag },
                { label: 'Tags', value: issue.Tags },
                { label: 'Notes', value: issue.Notes }
            ];

            fieldsToDisplay.forEach(field => {
                if (field.value && field.value !== '' && field.value !== 'N/A') {
                    const fieldDiv = document.createElement('div');
                    fieldDiv.className = 'kb-field';

                    const label = document.createElement('strong');
                    label.textContent = field.label + ': ';
                    fieldDiv.appendChild(label);

                    const valueSpan = document.createElement('span');
                    valueSpan.className = 'kb-field-value';

                    // Special handling for Applies to Asset Tag - make tags clickable
                    if (field.label === 'Applies to Asset Tag') {
                        // Parse comma-separated tags
                        const tags = field.value.split(',').map(t => t.trim()).filter(t => t.length > 0);
                        tags.forEach((tag, tagIndex) => {
                            if (tagIndex > 0) {
                                valueSpan.appendChild(document.createTextNode(', '));
                            }
                            const tagLink = document.createElement('span');
                            tagLink.textContent = tag;
                            tagLink.style.cursor = 'pointer';
                            tagLink.style.color = '#0066cc';
                            tagLink.style.textDecoration = 'underline';
                            tagLink.addEventListener('click', (e) => {
                                e.stopPropagation();
                                setGlobalTargetAsset(tag);
                                document.querySelector('.tab-button[data-tab="assetDetails"]').click();
                            });
                            valueSpan.appendChild(tagLink);
                        });
                    } else {
                        valueSpan.innerHTML = renderMarkdown(field.value);
                        valueSpan.querySelectorAll('.kb-crossref').forEach(span => {
                            span.addEventListener('click', async (e) => {
                                e.stopPropagation();
                                const id = span.dataset.id;
                                if (kbIssueIdSearch) kbIssueIdSearch.value = id;
                                if (kbTagSearch) kbTagSearch.value = '';
                                if (kbFreeformSearch) kbFreeformSearch.value = '';
                                if (kbActiveIssueTags) Array.from(kbActiveIssueTags.options).forEach(o => { o.selected = false; });
                                await performKBSearch();
                            });
                        });
                    }

                    fieldDiv.appendChild(valueSpan);

                    // Insert See Also section immediately after Applies to Asset Tag
                    if (field.label === 'Applies to Asset Tag') {
                        details.appendChild(fieldDiv);
                        const resolved = issue.SeeAlsoResolved;
                        if (Array.isArray(resolved) && resolved.length > 0) {
                            const seen = new Set();
                            const seeAlsoDiv = document.createElement('div');
                            seeAlsoDiv.className = 'kb-field';
                            const seeAlsoLabel = document.createElement('strong');
                            seeAlsoLabel.textContent = 'See Also: ';
                            seeAlsoDiv.appendChild(seeAlsoLabel);
                            const listEl = document.createElement('ul');
                            listEl.className = 'kb-seealso-list';
                            resolved.forEach(rel => {
                                if (!rel.IssueID || seen.has(rel.IssueID.toUpperCase())) return;
                                seen.add(rel.IssueID.toUpperCase());
                                const li = document.createElement('li');
                                const link = document.createElement('span');
                                link.textContent = rel.Title
                                    ? `${rel.IssueID} - ${rel.Title}`
                                    : rel.IssueID;
                                link.style.cursor = 'pointer';
                                link.style.color = '#0066cc';
                                link.style.textDecoration = 'underline';
                                link.addEventListener('click', async (e) => {
                                    e.stopPropagation();
                                    if (kbIssueIdSearch) kbIssueIdSearch.value = rel.IssueID;
                                    if (kbTagSearch) kbTagSearch.value = '';
                                    if (kbFreeformSearch) kbFreeformSearch.value = '';
                                    if (kbActiveIssueTags) Array.from(kbActiveIssueTags.options).forEach(o => { o.selected = false; });
                                    await performKBSearch();
                                });
                                li.appendChild(link);
                                listEl.appendChild(li);
                            });
                            seeAlsoDiv.appendChild(listEl);
                            details.appendChild(seeAlsoDiv);
                        }
                        return; // fieldDiv already appended above
                    }

                    details.appendChild(fieldDiv);
                }
            });

            // Add click handler to toggle expansion
            header.addEventListener('click', (e) => {
                console.log('KB header clicked', issue.IssueID);
                const isExpanded = details.classList.contains('expanded');
                console.log('Currently expanded:', isExpanded);
                details.classList.toggle('expanded');
                const icon = header.querySelector('.kb-expand-icon');
                if (icon) {
                    icon.textContent = isExpanded ? '▶' : '▼';
                    console.log('Icon changed to:', icon.textContent);
                } else {
                    console.log('Warning: expand icon not found');
                }
            });

            issueSection.appendChild(header);
            issueSection.appendChild(details);
            kbResultsContainer.appendChild(issueSection);
        });
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // --- Signal Path Finder ---
    const signalPathSource = document.getElementById("signalPathSource");
    const signalPathTarget = document.getElementById("signalPathTarget");
    const signalPathMaxHops = document.getElementById("signalPathMaxHops");
    const findSignalPathBtn = document.getElementById("findSignalPathBtn");
    const signalPathStatus = document.getElementById("signalPathStatus");
    const signalPathResult = document.getElementById("signalPathResult");

    async function performSignalPathFind() {
        const source = signalPathSource ? signalPathSource.value.trim() : "";
        const target = signalPathTarget ? signalPathTarget.value.trim() : "";
        if (!source || !target) { alert("Enter both source and target asset tags."); return; }
        const maxHops = signalPathMaxHops ? parseInt(signalPathMaxHops.value, 10) || 10 : 10;

        if (signalPathStatus) { signalPathStatus.textContent = "Searching…"; signalPathStatus.classList.remove("hidden"); }
        if (signalPathResult) signalPathResult.innerHTML = "";

        try {
            const params = new URLSearchParams({ source, target, max_hops: maxHops });
            const resp = await fetch(`${API_BASE_URL}/signal-path?${params}`);
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }
            const data = await resp.json();
            if (signalPathStatus) signalPathStatus.classList.add("hidden");
            renderSignalPath(data);
        } catch (e) {
            if (signalPathStatus) { signalPathStatus.textContent = `Error: ${e.message}`; signalPathStatus.classList.remove("hidden"); }
        }
    }

    function renderSignalPath(data) {
        if (!signalPathResult) return;
        signalPathResult.innerHTML = "";

        const summary = document.createElement("div");
        summary.className = "signal-path-summary";
        if (data.found) {
            summary.innerHTML = `Path found: <strong>${escapeHtml(data.source)}</strong> → <strong>${escapeHtml(data.target)}</strong> &nbsp;|&nbsp; <strong>${data.hops}</strong> hop${data.hops !== 1 ? "s" : ""}`;
        } else {
            summary.innerHTML = `<span style="color:var(--color-danger)">No path found</span>: ${escapeHtml(data.source)} → ${escapeHtml(data.target)}. ${escapeHtml(data.message || "")}`;
        }
        signalPathResult.appendChild(summary);

        if (!data.path || data.path.length === 0) return;

        const table = document.createElement("table");
        table.className = "connections-table";
        const headers = ["Hop", "From", "To", "Cable", "Type", "Protocol", "Src Port", "Dst Port"];
        const fields  = [null, "from", "to", "cable_tag", "type", "protocol", "src_port", "dst_port"];
        const thead = document.createElement("thead");
        const headerRow = document.createElement("tr");
        headers.forEach(h => { const th = document.createElement("th"); th.textContent = h; headerRow.appendChild(th); });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = document.createElement("tbody");
        data.path.forEach((hop, i) => {
            const tr = document.createElement("tr");
            fields.forEach((f, j) => {
                const td = document.createElement("td");
                td.textContent = f === null ? (i + 1) : (hop[f] || "");
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        signalPathResult.appendChild(table);
    }

    if (findSignalPathBtn) findSignalPathBtn.addEventListener("click", performSignalPathFind);
    [signalPathSource, signalPathTarget].forEach(inp => {
        if (inp) inp.addEventListener("keypress", e => { if (e.key === "Enter") { e.preventDefault(); performSignalPathFind(); } });
    });

    // --- URL Hash State ---
    function updateUrlHash(tag) {
        const hash = tag ? '#tag=' + encodeURIComponent(tag) : '#';
        history.replaceState(null, '', hash);
    }

    function restoreFromUrlHash() {
        const hash = window.location.hash;
        if (!hash || !hash.startsWith('#tag=')) return;
        const tag = decodeURIComponent(hash.slice(5)).trim();
        if (!tag) return;
        if (targetTagFilter) targetTagFilter.value = tag;
        performDiagramView();
    }

    window.addEventListener('hashchange', () => {
        const hash = window.location.hash;
        if (!hash || !hash.startsWith('#tag=')) return;
        const tag = decodeURIComponent(hash.slice(5)).trim();
        if (tag && targetTagFilter) {
            targetTagFilter.value = tag;
            performDiagramView();
        }
    });

    restoreFromUrlHash();

    // -------------------------------------------------------------------------
    // Dashboard — Route Comparison
    // -------------------------------------------------------------------------

    const dashboardContent       = document.getElementById("dashboardContent");
    const dashboardLastUpdated   = document.getElementById("dashboardLastUpdated");
    const dashboardRefreshBtn    = document.getElementById("dashboardRefreshBtn");
    const dashboardAutoRefresh   = document.getElementById("dashboardAutoRefresh");
    let   dashboardRefreshTimer  = null;

    const DASHBOARD_POLL_MS = 30_000;

    const DASHBOARD_STATUS_LABEL = {
        ok:          { text: "OK",          cls: "dash-badge-ok"          },
        warning:     { text: "WARNING",     cls: "dash-badge-warning"     },
        critical:    { text: "CRITICAL",    cls: "dash-badge-critical"    },
        unavailable: { text: "UNAVAILABLE", cls: "dash-badge-unavailable" },
        pending:     { text: "PENDING",     cls: "dash-badge-pending"     },
    };

    function dashBadge(status) {
        const info = DASHBOARD_STATUS_LABEL[status] || { text: status.toUpperCase(), cls: "dash-badge-pending" };
        const span = document.createElement("span");
        span.className = `dash-badge ${info.cls}`;
        span.textContent = info.text;
        return span;
    }

    function renderDashboard(data) {
        if (!dashboardContent) return;
        dashboardContent.innerHTML = "";

        // Overall status banner
        const banner = document.createElement("div");
        banner.className = "dash-banner";
        banner.appendChild(dashBadge(data.status));
        if (data.message) {
            const msg = document.createElement("span");
            msg.className = "dash-banner-msg";
            msg.textContent = data.message;
            banner.appendChild(msg);
        }
        dashboardContent.appendChild(banner);

        if (!data.panels || data.panels.length === 0) return;

        // Section heading
        const heading = document.createElement("h3");
        heading.className = "dash-section-heading";
        heading.textContent = "Route Comparison";
        dashboardContent.appendChild(heading);

        data.panels.forEach(panel => {
            const card = document.createElement("div");
            card.className = "dash-card";

            // Card header
            const header = document.createElement("div");
            header.className = "dash-card-header";

            const titleWrap = document.createElement("div");
            titleWrap.className = "dash-card-title";

            const assetLink = document.createElement("span");
            assetLink.className = "dash-asset-link";
            assetLink.textContent = panel.asset_tag;
            assetLink.title = "Click to set as target asset";
            assetLink.addEventListener("click", () => setGlobalTargetAsset(panel.asset_tag));
            titleWrap.appendChild(assetLink);

            if (panel.model || panel.usage) {
                const meta = document.createElement("span");
                meta.className = "dash-asset-meta";
                meta.textContent = [panel.model, panel.usage].filter(Boolean).join(" — ");
                titleWrap.appendChild(meta);
            }

            if (panel.adapter) {
                const adapterTag = document.createElement("span");
                adapterTag.className = "dash-adapter-tag";
                adapterTag.textContent = panel.adapter;
                titleWrap.appendChild(adapterTag);
            }

            const routeCount = document.createElement("span");
            routeCount.className = "dash-route-count";
            const checked = panel.total_routes_checked ?? 0;
            const defined = panel.total_routes_defined ?? 0;
            routeCount.textContent = panel.status === "pending" || panel.status === "unavailable"
                ? `${defined} routes defined`
                : `${checked} / ${defined} routes checked`;
            titleWrap.appendChild(routeCount);

            header.appendChild(titleWrap);
            header.appendChild(dashBadge(panel.status));
            card.appendChild(header);

            // Body
            if (panel.status === "ok") {
                const ok = document.createElement("p");
                ok.className = "dash-ok-msg";
                ok.textContent = `✓ All ${checked} routes match live state`;
                card.appendChild(ok);
            } else if (panel.status === "unavailable") {
                const msg = document.createElement("p");
                msg.className = "dash-unavailable-msg";
                msg.textContent = panel.error || "Route data unavailable";
                card.appendChild(msg);
            } else if (panel.status === "pending") {
                const msg = document.createElement("p");
                msg.className = "dash-pending-msg";
                msg.textContent = panel.message || "Monitoring not yet configured for this device";
                card.appendChild(msg);
            }

            if (panel.exceptions && panel.exceptions.length > 0) {
                const table = document.createElement("table");
                table.className = "dash-exceptions-table";

                const thead = document.createElement("thead");
                thead.innerHTML = `<tr>
                    <th>Cable</th>
                    <th>Output Port</th>
                    <th>Expected Input</th>
                    <th>Live Input</th>
                    <th>Detail</th>
                </tr>`;
                table.appendChild(thead);

                const tbody = document.createElement("tbody");
                panel.exceptions.forEach(ex => {
                    const tr = document.createElement("tr");
                    tr.className = `dash-ex-row dash-ex-${ex.severity}`;
                    tr.innerHTML = `
                        <td class="dash-ex-cable">${escapeHtml(ex.cable_tag || "")}</td>
                        <td>${escapeHtml(ex.output_port || (ex.output != null ? String(ex.output) : ""))}</td>
                        <td>${ex.expected_input != null ? ex.expected_input : "—"}</td>
                        <td>${ex.actual_input  != null ? ex.actual_input  : "—"}</td>
                        <td class="dash-ex-msg">${escapeHtml(ex.message || "")}</td>
                    `;
                    tbody.appendChild(tr);
                });
                table.appendChild(tbody);
                card.appendChild(table);
            }

            dashboardContent.appendChild(card);
        });
    }

    function renderNetworkPanel(data) {
        if (!dashboardContent) return;

        const heading = document.createElement("h3");
        heading.className = "dash-section-heading";
        heading.textContent = "Network Status";
        dashboardContent.appendChild(heading);

        // Config exceptions card (Monitor=Yes but no IP)
        if (data.config_exceptions && data.config_exceptions.length > 0) {
            const card = document.createElement("div");
            card.className = "dash-card";
            const header = document.createElement("div");
            header.className = "dash-card-header";
            const title = document.createElement("div");
            title.className = "dash-card-title";
            title.textContent = "Config Exceptions";
            header.appendChild(title);
            header.appendChild(dashBadge("warning"));
            card.appendChild(header);

            const table = document.createElement("table");
            table.className = "dash-exceptions-table";
            table.innerHTML = `<thead><tr><th>Asset Tag</th><th>Usage</th><th>NIC</th><th>Issue</th></tr></thead>`;
            const tbody = document.createElement("tbody");
            data.config_exceptions.forEach(ex => {
                const tr = document.createElement("tr");
                tr.className = "dash-ex-row dash-ex-warning";
                const assetLink = document.createElement("span");
                assetLink.className = "dash-asset-link";
                assetLink.textContent = ex.asset_tag;
                assetLink.title = "Click to set as target asset";
                assetLink.addEventListener("click", () => setGlobalTargetAsset(ex.asset_tag));
                const tdTag = document.createElement("td");
                tdTag.appendChild(assetLink);
                const tdUsage = document.createElement("td");
                tdUsage.textContent = ex.usage || "—";
                const tdNic = document.createElement("td");
                tdNic.textContent = ex.nic || "—";
                const tdIssue = document.createElement("td");
                tdIssue.textContent = ex.issue || "Monitor=Yes but no IP assigned";
                tr.appendChild(tdTag);
                tr.appendChild(tdUsage);
                tr.appendChild(tdNic);
                tr.appendChild(tdIssue);
                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            card.appendChild(table);
            dashboardContent.appendChild(card);
        }

        // Ping results — backend returns data.ping.results
        const ping = data.ping || {};
        if (ping.status === "unavailable" || !ping.results) {
            const card = document.createElement("div");
            card.className = "dash-card";
            const p = document.createElement("p");
            p.className = "dash-unavailable-msg";
            p.textContent = `Ping data unavailable — ${ping.error || "CueCommander unreachable"}`;
            card.appendChild(p);
            dashboardContent.appendChild(card);
            return;
        }

        const results = ping.results;
        const total = results.length;
        const down = results.filter(r => r.status === "down").length;
        const highLat = results.filter(r => r.status === "high_latency").length;

        const summaryCard = document.createElement("div");
        summaryCard.className = "dash-card";
        const summaryHeader = document.createElement("div");
        summaryHeader.className = "dash-card-header";
        const summaryTitle = document.createElement("div");
        summaryTitle.className = "dash-card-title";
        summaryTitle.textContent = `Ping Status (${total} monitored)`;
        const overallStatus = down > 0 ? "critical" : highLat > 0 ? "warning" : "ok";
        summaryHeader.appendChild(summaryTitle);
        summaryHeader.appendChild(dashBadge(overallStatus));
        summaryCard.appendChild(summaryHeader);

        // Build per-asset NIC summary: { asset_tag -> { total, okCount } }
        const nicSummary = {};
        results.forEach(r => {
            const tag = r.asset_tag;
            if (!nicSummary[tag]) nicSummary[tag] = { total: 0, okCount: 0 };
            nicSummary[tag].total++;
            if (r.status === "ok") nicSummary[tag].okCount++;
        });

        if (down === 0 && highLat === 0) {
            const ok = document.createElement("p");
            ok.className = "dash-ok-msg";
            ok.textContent = `✓ All ${total} monitored NICs reachable`;
            summaryCard.appendChild(ok);
        } else {
            const table = document.createElement("table");
            table.className = "dash-exceptions-table";
            table.innerHTML = `<thead><tr><th>Asset Tag</th><th>Usage</th><th>NIC</th><th>IP</th><th>Status</th><th>Avg ms</th><th>Loss</th><th>NICs</th><th>KB Issues</th></tr></thead>`;
            const tbody = document.createElement("tbody");
            results.filter(r => r.status !== "ok").forEach(r => {
                const tr = document.createElement("tr");
                tr.className = `dash-ex-row dash-ex-${r.status === "down" ? "critical" : "warning"}`;

                const assetLink = document.createElement("span");
                assetLink.className = "dash-asset-link";
                assetLink.textContent = r.asset_tag;
                assetLink.addEventListener("click", () => setGlobalTargetAsset(r.asset_tag));
                const tdTag = document.createElement("td");
                tdTag.appendChild(assetLink);
                tr.appendChild(tdTag);

                const tdUsage = document.createElement("td");
                tdUsage.textContent = r.usage || "—";
                tr.appendChild(tdUsage);

                [r.nic || "—", r.ip || "—", r.status,
                 r.avg_ms != null ? r.avg_ms.toFixed(1) : "—",
                 r.loss_pct != null ? `${r.loss_pct}%` : "—"
                ].forEach(c => {
                    const td = document.createElement("td");
                    td.textContent = c;
                    tr.appendChild(td);
                });

                // NIC summary column — only meaningful if device has >1 NIC
                const s = nicSummary[r.asset_tag];
                const tdNics = document.createElement("td");
                if (s && s.total > 1) {
                    tdNics.textContent = `${s.okCount}/${s.total} ok`;
                    tdNics.className = s.okCount > 0 ? "nic-summary-partial" : "nic-summary-all-down";
                }
                tr.appendChild(tdNics);

                // KB Issues column — clickable issue IDs from network.xlsx RelatedIssueId
                const tdKb = document.createElement("td");
                const issueIds = Array.isArray(r.related_issue_ids) ? r.related_issue_ids : [];
                if (issueIds.length > 0) {
                    issueIds.forEach((issueId, idx) => {
                        if (idx > 0) tdKb.appendChild(document.createTextNode(" "));
                        const link = document.createElement("span");
                        link.className = "dash-kb-link";
                        link.textContent = issueId;
                        link.title = `Open KB issue ${issueId}`;
                        link.addEventListener("click", async () => {
                            document.querySelector('.tab-button[data-tab="knowledgeBase"]').click();
                            if (kbIssueIdSearch) kbIssueIdSearch.value = issueId;
                            if (kbTagSearch) kbTagSearch.value = "";
                            if (kbFreeformSearch) kbFreeformSearch.value = "";
                            if (kbActiveIssueTags) Array.from(kbActiveIssueTags.options).forEach(o => { o.selected = false; });
                            await performKBSearch();
                        });
                        tdKb.appendChild(link);
                    });
                } else {
                    tdKb.textContent = "—";
                }
                tr.appendChild(tdKb);

                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            summaryCard.appendChild(table);
        }
        dashboardContent.appendChild(summaryCard);
    }

    function renderKlangPanel(data) {
        if (!dashboardContent) return;

        const heading = document.createElement("h3");
        heading.className = "dash-section-heading";
        heading.textContent = "Klang Mix Consistency";
        dashboardContent.appendChild(heading);

        const card = document.createElement("div");
        card.className = "dash-card";
        const header = document.createElement("div");
        header.className = "dash-card-header";
        const titleWrap = document.createElement("div");
        titleWrap.className = "dash-card-title";

        const status  = data.status || "unavailable";
        const sweep   = data.sweep || {};
        const vReport = data.variances;

        if (sweep.active || status === "pending") {
            titleWrap.textContent = `Sweep in progress (mix ${sweep.mix_current || 0}/16)`;
            header.appendChild(titleWrap);
            header.appendChild(dashBadge("warning"));
            card.appendChild(header);
            const p = document.createElement("p");
            p.className = "dash-ok-msg";
            p.textContent = "Collecting state from all 16 mixes… (~11s total)";
            card.appendChild(p);
        } else if (status === "unavailable") {
            titleWrap.textContent = "Mix Consistency";
            header.appendChild(titleWrap);
            header.appendChild(dashBadge("unavailable"));
            card.appendChild(header);
            const p = document.createElement("p");
            p.className = "dash-unavailable-msg";
            p.textContent = data.error || "No results yet — click Rebuild to start a sweep.";
            card.appendChild(p);
        } else if (vReport) {
            const genAt = vReport.generated_at ? new Date(vReport.generated_at).toLocaleTimeString() : "";
            titleWrap.textContent = `Mix Consistency${genAt ? ` (${genAt})` : ""}`;
            header.appendChild(titleWrap);
            header.appendChild(dashBadge(status));
            card.appendChild(header);

            // Discovered mixes table
            const mixesData = data.mixes;
            if (mixesData && mixesData.mixes && Object.keys(mixesData.mixes).length > 0) {
                const mixTable = document.createElement("table");
                mixTable.className = "dash-exceptions-table";
                mixTable.innerHTML = `<thead><tr><th>#</th><th>Mix Name</th><th>Preset</th><th>Channel Data</th></tr></thead>`;
                const mixTbody = document.createElement("tbody");
                const sortedKeys = Object.keys(mixesData.mixes).map(Number).sort((a, b) => a - b);
                const hasChannelData = mixesData.phase !== "mix_names_only";
                const chCount = mixesData.channels_with_data || 0;
                sortedKeys.forEach(mixNum => {
                    const m = mixesData.mixes[String(mixNum)];
                    const tr = document.createElement("tr");
                    const chCell = hasChannelData ? `✓ ${chCount} ch` : "Pending";
                    [String(mixNum), m.mix_name || "—", m.preset || "—", chCell].forEach((c, i) => {
                        const td = document.createElement("td");
                        td.textContent = c;
                        if (i === 3) td.style.color = hasChannelData ? "var(--color-ok, #4a4)" : "var(--color-warning, #aaa)";
                        tr.appendChild(td);
                    });
                    mixTbody.appendChild(tr);
                });
                mixTable.appendChild(mixTbody);
                card.appendChild(mixTable);
            }

            if (vReport.total_variances === 0 && (!mixesData || mixesData.phase === "mix_names_only")) {
                const p = document.createElement("p");
                p.className = "dash-ok-msg";
                p.style.marginTop = "8px";
                p.textContent = vReport.note || "Per-channel consistency check pending.";
                card.appendChild(p);
            } else if (vReport.total_variances === 0) {
                const p = document.createElement("p");
                p.className = "dash-ok-msg";
                p.textContent = "✓ All 16 mixes consistent";
                card.appendChild(p);
            } else {
                const crit = vReport.critical_count || 0;
                const total = vReport.total_variances;
                const summary = document.createElement("p");
                summary.className = "dash-ok-msg";
                const chWithVar = new Set((vReport.variances || []).map(v => v.channel)).size;
                summary.textContent =
                    `${total} variance${total !== 1 ? "s" : ""} across ${chWithVar} channel${chWithVar !== 1 ? "s" : ""}` +
                    (crit > 0 ? ` — ${crit} critical (mute)` : "");
                card.appendChild(summary);

                const variances = vReport.variances || [];
                const colKeys = ["mix", "channel", "attribute", "consensus", "vote", "actual"];
                const colLabels = ["Mix", "Ch", "Attribute", "Consensus", "Vote", "Actual"];
                const varSort = tableSortStates.klangVariances;

                const table = document.createElement("table");
                table.className = "dash-exceptions-table";
                const thead = document.createElement("thead");
                const headerRow = document.createElement("tr");
                colKeys.forEach((key, i) => {
                    const th = document.createElement("th");
                    th.textContent = colLabels[i];
                    th.style.cursor = "pointer";
                    th.dataset.col = key;
                    headerRow.appendChild(th);
                });
                const thSet = document.createElement("th");
                thSet.textContent = "Set this to";
                headerRow.appendChild(thSet);
                const thProp = document.createElement("th");
                thProp.textContent = "Set all others to";
                headerRow.appendChild(thProp);
                thead.appendChild(headerRow);
                table.appendChild(thead);

                const tbody = document.createElement("tbody");

                function renderVarianceRows() {
                    tbody.innerHTML = "";
                    const sorted = [...variances].sort((a, b) => {
                        let av, bv;
                        if (varSort.column === "vote") {
                            av = a.vote_count != null ? a.vote_count / (a.total_votes || 1) : -1;
                            bv = b.vote_count != null ? b.vote_count / (b.total_votes || 1) : -1;
                        } else {
                            av = a[varSort.column]; bv = b[varSort.column];
                        }
                        if (av < bv) return varSort.direction === "asc" ? -1 : 1;
                        if (av > bv) return varSort.direction === "asc" ? 1 : -1;
                        return 0;
                    });
                    sorted.forEach(v => {
                        const tr = document.createElement("tr");
                        tr.className = `dash-ex-row dash-ex-${v.severity === "critical" ? "critical" : "warning"}`;
                        const voteStr = (v.vote_count != null && v.total_votes != null)
                            ? `${v.vote_count}/${v.total_votes}` : "—";
                        [v.mix, v.channel, v.attribute, String(v.consensus), voteStr, String(v.actual)].forEach(c => {
                            const td = document.createElement("td");
                            td.textContent = c;
                            tr.appendChild(td);
                        });
                        // "Set this to" — set this mix to the consensus value
                        const setTd = document.createElement("td");
                        const setBtn = document.createElement("button");
                        setBtn.className = "dash-fix-btn";
                        setBtn.textContent = String(v.consensus);
                        setBtn.addEventListener("click", async () => {
                            setBtn.disabled = true;
                            const orig = setBtn.textContent;
                            setBtn.textContent = "…";
                            try {
                                const r = await fetch(`${API_BASE_URL}/dashboard/klang/setvariance`, {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ mix: v.mix, channel: v.channel, attribute: v.attribute, value: v.consensus })
                                });
                                const result = await r.json();
                                if (result.ok) { setBtn.textContent = "✓"; tr.style.opacity = "0.4"; }
                                else { setBtn.textContent = orig; setBtn.disabled = false; }
                            } catch(e) { setBtn.textContent = orig; setBtn.disabled = false; }
                        });
                        setTd.appendChild(setBtn);
                        tr.appendChild(setTd);

                        // "Set all others to" — propagate this row's actual value to all other 15 mixes
                        const propTd = document.createElement("td");
                        const allMixNums = mixesData && mixesData.mixes
                            ? Object.keys(mixesData.mixes).map(Number)
                            : Array.from({length: 16}, (_, i) => i + 1);
                        const otherMixNums = allMixNums.filter(m => m !== v.mix);
                        if (otherMixNums.length > 0) {
                            const propBtn = document.createElement("button");
                            propBtn.className = "dash-fix-btn dash-prop-btn";
                            propBtn.textContent = String(v.actual);
                            propBtn.addEventListener("click", async () => {
                                propBtn.disabled = true;
                                const orig = propBtn.textContent;
                                propBtn.textContent = `0/${otherMixNums.length}`;
                                try {
                                    let allOk = true;
                                    for (let i = 0; i < otherMixNums.length; i++) {
                                        propBtn.textContent = `${i + 1}/${otherMixNums.length}`;
                                        const r = await fetch(`${API_BASE_URL}/dashboard/klang/setvariance`, {
                                            method: "POST",
                                            headers: { "Content-Type": "application/json" },
                                            body: JSON.stringify({ mix: otherMixNums[i], channel: v.channel, attribute: v.attribute, value: v.actual })
                                        });
                                        const result = await r.json();
                                        if (!result.ok) { allOk = false; }
                                        // wait for SwitchUser + SET to complete before next mix
                                        await new Promise(res => setTimeout(res, 400));
                                    }
                                    propBtn.textContent = allOk ? "✓" : "Err";
                                    if (!allOk) propBtn.disabled = false;
                                } catch(e) { propBtn.textContent = orig; propBtn.disabled = false; }
                            });
                            propTd.appendChild(propBtn);
                        }
                        tr.appendChild(propTd);
                        tbody.appendChild(tr);
                    });
                    headerRow.querySelectorAll("th[data-col]").forEach(th => {
                        const active = th.dataset.col === varSort.column;
                        th.textContent = colLabels[colKeys.indexOf(th.dataset.col)] + (active ? (varSort.direction === "asc" ? " ▲" : " ▼") : "");
                    });
                }

                headerRow.querySelectorAll("th[data-col]").forEach(th => {
                    th.addEventListener("click", () => {
                        const col = th.dataset.col;
                        if (varSort.column === col) {
                            varSort.direction = varSort.direction === "asc" ? "desc" : "asc";
                        } else {
                            varSort.column = col;
                            varSort.direction = "asc";
                        }
                        renderVarianceRows();
                    });
                });

                renderVarianceRows();
                table.appendChild(tbody);
                card.appendChild(table);
            }
        }

        if (!sweep.active) {
            const bar = document.createElement("div");
            bar.className = "dash-action-bar";
            const btn = document.createElement("button");
            btn.className = "dash-rebuild-btn";
            btn.textContent = "Rebuild";
            btn.addEventListener("click", () => triggerKlangRebuild(btn));
            bar.appendChild(btn);
            card.appendChild(bar);
        }

        dashboardContent.appendChild(card);
    }

    async function triggerKlangRebuild(btn) {
        btn.disabled = true;
        btn.textContent = "Starting…";
        try {
            const resp = await fetch(`${API_BASE_URL}/dashboard/klang/buildconsensus`, { method: "POST" });
            if (resp.status === 409) {
                btn.textContent = "Already running";
                setTimeout(() => { btn.disabled = false; btn.textContent = "Rebuild"; }, 3000);
                return;
            }
            if (!resp.ok) {
                btn.disabled = false;
                btn.textContent = "Rebuild";
                return;
            }
            btn.textContent = "Sweep in progress…";
            let tries = 0;
            const poll = async () => {
                tries++;
                try {
                    const sr = await fetch(`${API_BASE_URL}/dashboard/klang`);
                    const sd = await sr.json();
                    if (sd.sweep && !sd.sweep.active && sd.variances) {
                        fetchAndRenderDashboard();
                        return;
                    }
                } catch (_) { /* ignore polling errors */ }
                if (tries < 20) setTimeout(poll, 2000);
                else { btn.disabled = false; btn.textContent = "Rebuild"; }
            };
            setTimeout(poll, 3000);
        } catch (_) {
            btn.disabled = false;
            btn.textContent = "Rebuild";
        }
    }

    async function fetchAndRenderDashboard() {
        if (!dashboardContent) return;
        try {
            const [xpResp, netResp, klangResp] = await Promise.all([
                fetch(`${API_BASE_URL}/dashboard/crosspoint`),
                fetch(`${API_BASE_URL}/dashboard/network`),
                fetch(`${API_BASE_URL}/dashboard/klang`),
            ]);
            if (!xpResp.ok) throw new Error(`Crosspoint HTTP ${xpResp.status}`);
            const xpData = await xpResp.json();
            renderDashboard(xpData);

            if (netResp.ok) {
                const netData = await netResp.json();
                renderNetworkPanel(netData);
            } else {
                renderNetworkPanel({ ping: { status: "unavailable", error: `HTTP ${netResp.status}` } });
            }

            const klangData = klangResp.ok ? await klangResp.json() : { status: "unavailable", error: `HTTP ${klangResp.status}` };
            renderKlangPanel(klangData);

            if (dashboardLastUpdated) {
                const t = xpData.generated_at ? new Date(xpData.generated_at).toLocaleTimeString() : new Date().toLocaleTimeString();
                dashboardLastUpdated.textContent = `Last updated: ${t}`;
            }
        } catch (err) {
            if (dashboardContent) dashboardContent.innerHTML =
                `<p class="dash-error">Failed to load dashboard: ${escapeHtml(err.message)}</p>`;
        }
    }

    function scheduleDashboardRefresh() {
        clearInterval(dashboardRefreshTimer);
        if (dashboardAutoRefresh && dashboardAutoRefresh.checked) {
            dashboardRefreshTimer = setInterval(fetchAndRenderDashboard, DASHBOARD_POLL_MS);
        }
    }

    if (dashboardRefreshBtn) {
        dashboardRefreshBtn.addEventListener("click", () => {
            fetchAndRenderDashboard();
        });
    }

    if (dashboardAutoRefresh) {
        dashboardAutoRefresh.addEventListener("change", scheduleDashboardRefresh);
    }

    // Load dashboard when its tab is activated; start/stop auto-refresh accordingly
    tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            if (btn.dataset.tab === "dashboard") {
                fetchAndRenderDashboard();
                scheduleDashboardRefresh();
            } else {
                clearInterval(dashboardRefreshTimer);
            }
        });
    });

    // Dashboard is the default active tab — load it on startup
    fetchAndRenderDashboard();
    scheduleDashboardRefresh();

    // ── Network Tab ───────────────────────────────────────────────────────────
    const networkAssetTagSearch  = document.getElementById("networkAssetTagSearch");
    const networkAssetTagSearchBtn = document.getElementById("networkAssetTagSearchBtn");
    const networkAddrSearch      = document.getElementById("networkAddrSearch");
    const networkAddrSearchBtn   = document.getElementById("networkAddrSearchBtn");
    const networkResultsContainer = document.getElementById("networkResultsContainer");
    const networkDetailsContainer = document.getElementById("networkDetailsContainer");
    const networkSearchStatus    = document.getElementById("networkSearchStatus");

    function showNetworkStatus(msg) {
        if (!networkSearchStatus) return;
        networkSearchStatus.textContent = msg;
        networkSearchStatus.classList.toggle("hidden", !msg);
    }

    async function fetchAndRenderNetworkDetails(tag) {
        if (!networkDetailsContainer) return;
        if (networkAssetTagSearch) networkAssetTagSearch.value = tag;
        showNetworkStatus("Loading…");
        networkResultsContainer.innerHTML = "";
        try {
            const resp = await fetch(`${API_BASE_URL}/assets/${encodeURIComponent(tag)}/network`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const nics = await resp.json();
            showNetworkStatus("");
            networkDetailsContainer.innerHTML = `<h3 class="network-asset-heading">${escapeHtml(tag)}</h3>`;
            renderAssetNetwork(nics, networkDetailsContainer);
        } catch (err) {
            showNetworkStatus(`Error loading network data: ${err.message}`);
            networkDetailsContainer.innerHTML = "";
        }
    }

    function renderNetworkSearchResults(results) {
        networkResultsContainer.innerHTML = "";
        networkDetailsContainer.innerHTML = "";

        if (results.length === 0) {
            showEmptyState(networkResultsContainer, "No matching network records found.", "🔍");
            return;
        }

        if (results.length === 1) {
            // Single match — show details directly without the summary table
            const a = results[0];
            setGlobalTargetAsset(a.asset_tag);
            networkDetailsContainer.innerHTML = `<h3 class="network-asset-heading">${escapeHtml(a.asset_tag)}${a.manufacturer || a.model ? ` — ${escapeHtml([a.manufacturer, a.model].filter(Boolean).join(" "))}` : ""}</h3>`;
            renderAssetNetwork(a.nics, networkDetailsContainer);
            return;
        }

        // Multiple matches — summary table with clickable asset tags
        const table = document.createElement("table");
        table.className = "network-search-results-table";
        table.innerHTML = `<thead><tr>
            <th>Asset Tag</th><th>Manufacturer</th><th>Model</th>
            <th>IP Addresses</th><th>MAC Addresses</th>
        </tr></thead>`;
        const tbody = document.createElement("tbody");

        results.forEach(a => {
            const tr = document.createElement("tr");
            const tagCell = document.createElement("td");
            const tagLink = document.createElement("a");
            tagLink.href = "#";
            tagLink.className = "asset-tag-link";
            tagLink.textContent = a.asset_tag;
            tagLink.addEventListener("click", e => {
                e.preventDefault();
                setGlobalTargetAsset(a.asset_tag);
                networkDetailsContainer.innerHTML = `<h3 class="network-asset-heading">${escapeHtml(a.asset_tag)}${a.manufacturer || a.model ? ` — ${escapeHtml([a.manufacturer, a.model].filter(Boolean).join(" "))}` : ""}</h3>`;
                renderAssetNetwork(a.nics, networkDetailsContainer);
            });
            tagCell.appendChild(tagLink);
            tr.appendChild(tagCell);
            tr.innerHTML += `
                <td>${escapeHtml(a.manufacturer || "—")}</td>
                <td>${escapeHtml(a.model        || "—")}</td>
                <td class="network-ip">${a.ip_addresses.map(escapeHtml).join("<br>") || "—"}</td>
                <td class="network-mac">${a.mac_addresses.map(escapeHtml).join("<br>") || "—"}</td>`;
            tr.firstChild.replaceWith(tagCell);
            tbody.appendChild(tr);
        });

        table.appendChild(tbody);
        networkResultsContainer.appendChild(table);
    }

    async function performNetworkAssetTagSearch() {
        const tag = networkAssetTagSearch?.value.trim();
        if (!tag) return;
        setGlobalTargetAsset(tag);
        await fetchAndRenderNetworkDetails(tag);
    }

    async function performNetworkAddrSearch() {
        const q = networkAddrSearch?.value.trim();
        if (!q) return;
        showNetworkStatus("Searching…");
        networkResultsContainer.innerHTML = "";
        networkDetailsContainer.innerHTML = "";
        try {
            const resp = await fetch(`${API_BASE_URL}/network/search?q=${encodeURIComponent(q)}`);
            if (resp.status === 400) {
                const err = await resp.json();
                showNetworkStatus(err.detail || "Invalid search query.");
                return;
            }
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const results = await resp.json();
            showNetworkStatus("");
            renderNetworkSearchResults(results);
        } catch (err) {
            showNetworkStatus(`Error: ${err.message}`);
        }
    }

    if (networkAssetTagSearchBtn) networkAssetTagSearchBtn.addEventListener("click", performNetworkAssetTagSearch);
    if (networkAddrSearchBtn)     networkAddrSearchBtn.addEventListener("click", performNetworkAddrSearch);
    if (networkAssetTagSearch)    networkAssetTagSearch.addEventListener("keydown", e => { if (e.key === "Enter") performNetworkAssetTagSearch(); });
    if (networkAddrSearch)        networkAddrSearch.addEventListener("keydown", e => { if (e.key === "Enter") performNetworkAddrSearch(); });

    // ── Deep-link handling ────────────────────────────────────────────────────
    // Supports ?tab=assetDetails&tag=ZVVU-0001 and ?tab=knowledgeBase&issue=KB0001
    const dlParams = new URLSearchParams(window.location.search);
    const dlTab    = dlParams.get("tab");
    const dlTag    = dlParams.get("tag");
    const dlIssue  = dlParams.get("issue");

    function activateTab(tabId) {
        tabButtons.forEach(btn => btn.classList.remove("active"));
        tabContents.forEach(c => c.classList.remove("active"));
        const btn = document.querySelector(`.tab-button[data-tab="${tabId}"]`);
        if (btn) btn.classList.add("active");
        const content = document.getElementById(tabId);
        if (content) content.classList.add("active");
    }

    if (dlTab === "assetDetails" && dlTag) {
        activateTab("assetDetails");
        const input = document.getElementById(ASSET_DETAILS_INPUT_ID);
        if (input) input.value = dlTag;
        fetchAndRenderAssetDetails(dlTag);
    } else if (dlTab === "knowledgeBase" && dlIssue) {
        activateTab("knowledgeBase");
        const issueInput = document.getElementById("kbIssueIdSearch");
        if (issueInput) issueInput.value = dlIssue;
        // Trigger KB search for the specific issue
        const params = new URLSearchParams({ issue_id: dlIssue });
        fetch(`${API_BASE_URL}/knowledgebase/search?${params}`)
            .then(r => r.ok ? r.json() : [])
            .then(issues => renderKBResults(issues))
            .catch(err => console.error("Deep-link KB search failed:", err));
    }
});
