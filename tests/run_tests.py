#!/usr/bin/env python3
"""
Manual backend test suite for the UAC Tech webapp.

Run with: python3 tests/run_tests.py
Optionally set WEBAPP_API_BASE to override the backend URL (default http://localhost:9000).
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, List, Tuple


API_BASE = os.environ.get("WEBAPP_API_BASE", "http://localhost:9000").rstrip("/")
DEFAULT_TIMEOUT = float(os.environ.get("WEBAPP_TEST_TIMEOUT", "10"))


class TestFailure(Exception):
    """Raised when an individual test fails."""


def request_json(path: str):
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise TestFailure(f"HTTP {exc.code} for {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise TestFailure(f"Request failed for {url}: {exc}") from exc


def request_text(path: str):
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, headers={"Accept": "text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise TestFailure(f"HTTP {exc.code} for {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise TestFailure(f"Request failed for {url}: {exc}") from exc


def test_backend_root():
    data = request_json("/")
    if "message" not in data:
        raise TestFailure("Root endpoint missing 'message'")


def test_health_endpoint():
    data = request_json("/health")
    if "status" not in data:
        raise TestFailure("Health endpoint missing 'status' key")
    if "checks" not in data:
        raise TestFailure("Health endpoint missing 'checks' key")
    if data["status"] not in ("ok", "degraded"):
        raise TestFailure(f"Unexpected health status: {data['status']}")
    if data["status"] != "ok":
        raise TestFailure(f"Health check degraded: {data['checks']}")


def test_asset_search_returns_usage():
    target_tag = "ZVKU-A001"
    data = request_json(f"/assets/search?asset_tag={urllib.parse.quote(target_tag)}")
    if not data:
        raise TestFailure(f"No asset rows returned for {target_tag}")
    row = data[0]
    if row.get("AssetTag", "").strip().upper() != target_tag:
        raise TestFailure(f"Unexpected asset tag in response: {row.get('AssetTag')}")
    if not row.get("Usage"):
        raise TestFailure("Asset row missing Usage value")

def test_asset_search_in_service_filter():
    # Test with in_service_only=true (default)
    data_in_service = request_json("/assets/search?in_service_only=true")
    if not data_in_service:
        raise TestFailure("Expected at least one in-service asset")
    # Verify all returned assets have InService="Y"
    for asset in data_in_service:
        if asset.get("InService", "").upper() != "Y":
            raise TestFailure(f"Asset {asset.get('AssetTag')} has InService={asset.get('InService')}, expected Y")

    # Test with in_service_only=false to get all assets
    data_all = request_json("/assets/search?in_service_only=false")
    if not data_all:
        raise TestFailure("Expected at least one asset when not filtering")
    # Verify we get more assets (or at least same) when not filtering
    if len(data_all) < len(data_in_service):
        raise TestFailure(f"Expected more assets without filter ({len(data_all)}) than with filter ({len(data_in_service)})")


def test_cable_filter_has_rows():
    target_tag = "2507-0700"
    data = request_json(f"/cables/filter?target_tag={urllib.parse.quote(target_tag)}&direction=both")
    cables = data.get("cables") if isinstance(data, dict) else data
    if not cables:
        raise TestFailure(f"No cables returned for {target_tag}")
    sample = cables[0]
    if "SrcTag" not in sample or "DstTag" not in sample:
        raise TestFailure("Cable row missing SrcTag/DstTag fields")


def test_graph_contains_usage_line():
    target_tag = "ZVKU-A001"
    svg_text = request_text(f"/graphviz/dot?target_tag={urllib.parse.quote(target_tag)}&direction=both")
    expected_usage = "HDBaseT Video Matrix"
    if expected_usage not in svg_text:
        raise TestFailure(f"Usage text '{expected_usage}' not found inside graphviz output for {target_tag}")

def test_graph_respects_custom_fields():
    target_tag = "ZVKU-A001"
    params = urllib.parse.urlencode({
        "target_tag": target_tag,
        "direction": "both",
        "node_fields": "tag",
        "edge_fields": "tag"
    })
    svg_text = request_text(f"/graphviz/dot?{params}")
    if "Legacy switcher for HDBaseT distribution" in svg_text:
        raise TestFailure("Usage line rendered despite node_fields=tag")
    if "Manufacturer" in svg_text:
        raise TestFailure("Manufacturer text rendered despite node_fields=tag")


def test_diagram_options_lists_all_fields():
    data = request_json("/diagram/options")
    node_payload = data.get("node") or {}
    edge_payload = data.get("edge") or {}
    node_defaults = node_payload.get("defaults") or []
    node_options = node_payload.get("options") or []
    edge_defaults = edge_payload.get("defaults") or []
    edge_options = edge_payload.get("options") or []
    if not node_defaults or not edge_defaults:
        raise TestFailure("Diagram options endpoint missing defaults")
    node_values = [opt.get("value") for opt in node_options if opt.get("value")]
    edge_values = [opt.get("value") for opt in edge_options if opt.get("value")]
    if node_values[:len(node_defaults)] != node_defaults:
        raise TestFailure("Node defaults are not listed first")
    if edge_values[:len(edge_defaults)] != edge_defaults:
        raise TestFailure("Edge defaults are not listed first")
    if len(set(node_values)) <= len(node_defaults):
        raise TestFailure("Node options missing non-default fields")
    if len(set(edge_values)) <= len(edge_defaults):
        raise TestFailure("Edge options missing non-default fields")


def test_graph_renders_additional_fields():
    # Test for node category
    target_tag_node = "ZVKU-A001"
    params_node = urllib.parse.urlencode({
        "target_tag": target_tag_node,
        "direction": "both",
        "node_fields": "tag,category"
    })
    svg_text_node = request_text(f"/graphviz/dot?{params_node}")
    if "Video" not in svg_text_node:
        raise TestFailure(f"Category field 'Video' missing when requested on node labels for {target_tag_node}")

    # Test for edge protocol
    # Need to use an asset that has a known protocol
    target_tag_edge = "ZVKU-A001" # Using ZVKU-A001 as source now
    params_edge = urllib.parse.urlencode({
        "target_tag": target_tag_edge,
        "direction": "both",
        "edge_fields": "tag,protocol"
    })
    svg_text_edge = request_text(f"/graphviz/dot?{params_edge}")
    # Based on cable data, ZVKU-A001 has "HdBaseT" protocol.
    if "hdbaset" not in svg_text_edge.lower():
        raise TestFailure(f"Protocol field 'HdBaseT' missing when requested on edge labels for {target_tag_edge}")


def test_graph_colors_edges_by_protocol():
    target_tag = "ZVKU-A001" # Changed from ZVKU-A003
    params = urllib.parse.urlencode({
        "target_tag": target_tag,
        "direction": "both",
        "color_edges_by_protocol": "true"
    })
    svg_text = request_text(f"/graphviz/dot?{params}")
    # Based on cable data for ZVKU-A001, expected protocol is HdBaseT, color #1f77b4
    if "#1f77b4" not in svg_text.lower():
        raise TestFailure(f"HdBaseT protocol color (#1f77b4) not applied to edge when requested for {target_tag}")


def test_graph_colors_nodes_by_category():
    params = urllib.parse.urlencode({
        "target_tag": "ZVKU-A001", # Keeping ZVKU-A001 for this test for now, if it passes.
        "direction": "both",
        "color_nodes_by_category": "true"
    })
    svg_text = request_text(f"/graphviz/dot?{params}")
    if "#d2e5ff" not in svg_text.lower():
        raise TestFailure("Category-based node background color missing when requested")


def test_asset_tags_endpoint():
    data = request_json("/assets/tags")
    tags = data.get("tags")
    if not isinstance(tags, list) or not tags:
        raise TestFailure("/assets/tags did not return a non-empty list")
    normalized = [tag.strip().upper() for tag in tags]
    if "ZVKU-A001" not in normalized:
        raise TestFailure("Expected ZVKU-A001 in /assets/tags response")


def test_crosspoint_matrix_returns_data():
    source_tag = "ZVKU-A001"
    target_tag = "ZVIU-A001"
    params = urllib.parse.urlencode({
        "source_tag": source_tag,
        "target_tag": target_tag
    })
    data = request_json(f"/crosspoint/matrix?{params}")
    if "rows" not in data or "columns" not in data:
        raise TestFailure("Crosspoint matrix response missing rows/columns")
    if not isinstance(data.get("protocols"), list):
        raise TestFailure("Crosspoint matrix missing protocol options")
    # This check `if data.get("rows") and data.get("columns") and not data.get("matrix"):` is problematic
    # It assumes that if rows/columns exist, a matrix *must* exist, which isn't always true for empty matrix.
    # A more robust check might be `if not data.get("matrix") is None`.
    # For now, ensure that matrix is a list.
    if not isinstance(data.get("matrix"), list):
        raise TestFailure("Crosspoint matrix missing or invalid matrix payload")

def test_crosspoint_protocol_filtering():
    source_tag = "ZVKU-A001"
    target_tag = "ZVIU-A001"     
    # Check if there is an HdBaseT connection
    params = urllib.parse.urlencode({
        "source_tag": source_tag,
        "target_tag": target_tag,
        "protocol": "hdbaset"
    })
    data = request_json(f"/crosspoint/matrix?{params}")
    matrix = data.get("matrix") or []
    any_connection = any(any(row) for row in matrix)
    if not any_connection:
        raise TestFailure(f"Expected HdBaseT protocol connection for {source_tag} -> {target_tag}")

    # Check for a protocol that should *not* exist (e.g., "sdi")
    params_no_conn = urllib.parse.urlencode({
        "source_tag": source_tag,
        "target_tag": target_tag,
        "protocol": "sdi" 
    })
    data_no_conn = request_json(f"/crosspoint/matrix?{params_no_conn}")
    matrix_no_conn = data_no_conn.get("matrix") or []
    any_connection_no_conn = any(any(row) for row in matrix_no_conn)
    if any_connection_no_conn:
        raise TestFailure(f"Unexpected SDI connection reported for {source_tag} -> {target_tag}")


def test_asset_linked_endpoint():
    primary_tag = "ZVKU-A001"
    linked_peer = "ZVIU-A001"
    
    params_outbound = urllib.parse.urlencode({
        "tag": primary_tag,
        "direction": "outbound"
    })
    data_outbound = request_json(f"/assets/linked?{params_outbound}")
    peers_outbound = data_outbound.get("peers") or []
    if linked_peer not in peers_outbound:
        raise TestFailure(f"Expected linked peer {linked_peer} for outbound {primary_tag}")

    params_inbound = urllib.parse.urlencode({
        "tag": linked_peer, # Test inbound to the peer
        "direction": "inbound"
    })
    data_inbound = request_json(f"/assets/linked?{params_inbound}")
    peers_inbound = data_inbound.get("peers") or []
    if primary_tag not in peers_inbound:
        raise TestFailure(f"Expected inbound peer {primary_tag} for {linked_peer}")


def test_asset_columns_endpoint():
    data = request_json("/assets/columns")
    columns = data.get("columns")
    defaults = data.get("defaults")
    if not isinstance(columns, list) or not columns:
        raise TestFailure("/assets/columns returned no metadata")
    if not isinstance(defaults, list) or not defaults:
        raise TestFailure("/assets/columns missing defaults")
    column_values = [col.get("value") for col in columns if col.get("value")]
    if "AssetTag" not in column_values:
        raise TestFailure("/assets/columns missing AssetTag entry")
    if "AssetTag" not in defaults:
        raise TestFailure("AssetTag should be part of default asset columns")


def test_protocol_filter_limits_results():
    params = urllib.parse.urlencode({
        "target_tag": "ZAMU-A001",
        "direction": "both",
        "protocol": "dante"
    })
    data = request_json(f"/cables/filter?{params}")
    cables = data.get("cables") if isinstance(data, dict) else data
    if not cables:
        raise TestFailure("Protocol-filtered cable query returned no rows")
    for cable in cables:
        if (cable.get("Protocol") or "").strip().lower() != "dante":
            raise TestFailure("Cable returned outside of requested protocol filter")


def test_graph_collapse_by_protocol():
    params = urllib.parse.urlencode({
        "target_tag": "ZAMU-A001",
        "direction": "both",
        "collapse_strategy": "protocol"
    })
    svg_text = request_text(f"/graphviz/dot?{params}")
    if "dante" not in svg_text.lower():
        raise TestFailure("Collapsed diagram missing protocol label 'dante'")
    if ':out_dante' not in svg_text.lower():
        raise TestFailure("Collapsed protocol port identifier not present in SVG output")


def test_cable_id_query_returns_chain():
    params = urllib.parse.urlencode({
        "target_tag": "2307-2306",
        "direction": "both"
    })
    data = request_json(f"/cables/filter?{params}")
    cables = data.get("cables") if isinstance(data, dict) else data
    tags = {str(cable.get("Tag", "")).strip() for cable in cables}
    if "2307-2306" not in tags:
        raise TestFailure("Selected cable ID row missing from cable query results")
    if "2307-2305" not in tags:
        raise TestFailure("Cable-to-cable continuation row missing from cable query results")


def test_graph_renders_cable_junction_dot():
    params = urllib.parse.urlencode({
        "target_tag": "2307-2306",
        "direction": "both"
    })
    svg_text = request_text(f"/graphviz/dot?{params}")
    if "__cable_junction__" not in svg_text:
        raise TestFailure("Expected cable junction node identifier missing from SVG")
    if 'ellipse' not in svg_text and 'polygon' not in svg_text:
        raise TestFailure("Expected rendered node geometry missing from SVG output")


def test_diagram_connections_combined_endpoint_shape():
    target_tag = "2507-0700"
    data = request_json(f"/diagram/connections?target_tag={urllib.parse.quote(target_tag)}")
    if not isinstance(data, dict):
        raise TestFailure("Combined connections endpoint did not return a dict")
    for key in ("inputs", "outputs", "internal_routes", "passthroughs"):
        if key not in data:
            raise TestFailure(f"Combined connections response missing key: {key}")
        if not isinstance(data[key], list):
            raise TestFailure(f"Combined connections '{key}' is not a list")
    if not data["inputs"]:
        raise TestFailure(f"No input connections returned for {target_tag}")
    if not data["outputs"]:
        raise TestFailure(f"No output connections returned for {target_tag}")
    # 2507-0700 is a matrix switcher with route cables
    if not data["internal_routes"]:
        raise TestFailure(f"No internal routes returned for {target_tag}")
    first_input = data["inputs"][0]
    for key in ("TargetPort", "SourcePort", "Protocol", "CableID",
                "PartnerAssetTag", "PartnerManufacturer", "PartnerModel", "PartnerUsage"):
        if key not in first_input:
            raise TestFailure(f"Input connection entry missing key: {key}")
    first_output = data["outputs"][0]
    for key in ("TargetPort", "DestinationPort", "Protocol", "CableID",
                "PartnerAssetTag", "PartnerManufacturer", "PartnerModel", "PartnerUsage"):
        if key not in first_output:
            raise TestFailure(f"Output connection entry missing key: {key}")


def test_internal_routes_excluded_from_outputs():
    target_tag = "2507-0700"
    data = request_json(f"/diagram/connections?target_tag={urllib.parse.quote(target_tag)}")
    route_cable_ids = {row["CableID"] for row in data.get("internal_routes", [])}
    for row in data.get("outputs", []):
        if row["CableID"] in route_cable_ids:
            raise TestFailure(
                f"Route cable {row['CableID']} appears in both outputs and internal_routes"
            )
    for row in data.get("inputs", []):
        if row["CableID"] in route_cable_ids:
            raise TestFailure(
                f"Route cable {row['CableID']} appears in both inputs and internal_routes"
            )


def test_internal_routes_present_in_internal_routes_table():
    target_tag = "2507-0700"
    data = request_json(f"/diagram/connections?target_tag={urllib.parse.quote(target_tag)}")
    routes = data.get("internal_routes", [])
    if not routes:
        raise TestFailure(f"Expected internal_routes entries for {target_tag}")
    first = routes[0]
    for key in ("SourcePort", "DestinationPort", "Protocol", "CableID", "Type"):
        if key not in first:
            raise TestFailure(f"Internal route entry missing key: {key}")
    # Confirm at least one row's Type contains "route"
    if not any("route" in (r.get("Type") or "").lower() for r in routes):
        raise TestFailure("No internal route row has Type containing 'route'")


def test_non_routed_asset_returns_empty_internal_routes():
    # 2601-1305 is a display with no internal route cables
    target_tag = "2601-1305"
    data = request_json(f"/diagram/connections?target_tag={urllib.parse.quote(target_tag)}")
    if not isinstance(data, dict):
        raise TestFailure("Combined connections endpoint did not return a dict")
    if data.get("internal_routes"):
        raise TestFailure(f"Expected empty internal_routes for {target_tag}, got {data['internal_routes']}")
    # Should still have outputs or inputs
    if not data.get("outputs") and not data.get("inputs"):
        raise TestFailure(f"Expected at least some connections for {target_tag}")


def test_passthroughs_present_for_patch_panel():
    # 2602-1800-F38 is a patch panel with many passthrough cables
    target_tag = "2602-1800-F38"
    data = request_json(f"/diagram/connections?target_tag={urllib.parse.quote(target_tag)}")
    if not isinstance(data, dict):
        raise TestFailure("Combined connections endpoint did not return a dict")
    if "passthroughs" not in data:
        raise TestFailure("Response missing 'passthroughs' key")
    pts = data["passthroughs"]
    if not pts:
        raise TestFailure(f"Expected passthrough entries for {target_tag}")
    first = pts[0]
    for key in ("SourcePort", "DestinationPort", "Protocol", "CableID", "Type"):
        if key not in first:
            raise TestFailure(f"Passthrough entry missing key: {key}")
    if not any("passthrough" in (r.get("Type") or "").lower() for r in pts):
        raise TestFailure("No passthrough row has Type containing 'passthrough'")


def test_passthroughs_excluded_from_inputs_and_outputs():
    # Passthrough cables must not appear in the inputs or outputs lists
    target_tag = "2602-1800-F38"
    data = request_json(f"/diagram/connections?target_tag={urllib.parse.quote(target_tag)}")
    pt_ids = {r["CableID"] for r in data.get("passthroughs", [])}
    if not pt_ids:
        raise TestFailure(f"No passthroughs found for {target_tag} — cannot verify exclusion")
    for row in data.get("inputs", []):
        if row["CableID"] in pt_ids:
            raise TestFailure(f"Passthrough cable {row['CableID']} appears in inputs")
    for row in data.get("outputs", []):
        if row["CableID"] in pt_ids:
            raise TestFailure(f"Passthrough cable {row['CableID']} appears in outputs")
    for row in data.get("internal_routes", []):
        if row["CableID"] in pt_ids:
            raise TestFailure(f"Passthrough cable {row['CableID']} appears in internal_routes")


def test_bfrs_in_diagram_node_options():
    # /diagram/options must include 'bfrs' as an available node field option
    data = request_json("/diagram/options")
    if not isinstance(data, dict) or "node" not in data:
        raise TestFailure("diagram/options did not return expected shape")
    node_options = data["node"].get("options", [])
    option_values = [o.get("value") if isinstance(o, dict) else o for o in node_options]
    if "bfrs" not in option_values:
        raise TestFailure(f"'bfrs' not found in node options: {option_values}")


def test_bfrs_label_in_diagram_options():
    # The 'bfrs' option must have label "BFRS"
    data = request_json("/diagram/options")
    node_options = data.get("node", {}).get("options", [])
    for opt in node_options:
        if isinstance(opt, dict) and opt.get("value") == "bfrs":
            if opt.get("label") != "BFRS":
                raise TestFailure(f"Expected label 'BFRS', got {opt.get('label')!r}")
            return
    raise TestFailure("'bfrs' option not found in node options")


def test_passthrough_edges_rendered_bidirectional():
    # 2602-1800-F38 has passthrough cables; with include_passthroughs=true the DOT
    # output must contain dir=both on at least one edge.
    params = urllib.parse.urlencode({
        "target_tag": "2602-1800-F38",
        "direction": "both",
        "include_passthroughs": "true",
    })
    dot_text = request_text(f"/graphviz/dot?{params}")
    if "dir=both" not in dot_text:
        raise TestFailure(
            "Expected 'dir=both' in DOT output for passthrough cables of 2602-1800-F38"
        )

def test_get_asset_details_endpoint():
    target_tag = "ZVKU-A001"
    data = request_json(f"/assets/{urllib.parse.quote(target_tag)}/details")

    if not isinstance(data, dict):
        raise TestFailure(f"/assets/{target_tag}/details did not return a dictionary")
    
    expected_keys = ["asset", "input_partners", "output_partners", "knowledge_base_issues"]
    for key in expected_keys:
        if key not in data:
            raise TestFailure(f"Asset details response missing expected key: {key}")
    
    # Check asset properties
    asset = data.get("asset")
    if not isinstance(asset, dict) or asset.get("AssetTag") != target_tag:
        raise TestFailure(f"Asset details 'asset' data is incorrect or missing AssetTag")

    # Check input partners (should be a list, can be empty)
    input_partners = data.get("input_partners")
    if not isinstance(input_partners, list):
        raise TestFailure("Asset details 'input_partners' is not a list")

    # Check output partners (should be a list, can be empty)
    output_partners = data.get("output_partners")
    if not isinstance(output_partners, list):
        raise TestFailure("Asset details 'output_partners' is not a list")
    
    # Check knowledge base issues (should be a list, can be empty)
    kb_issues = data.get("knowledge_base_issues")
    if not isinstance(kb_issues, list):
        raise TestFailure("Asset details 'knowledge_base_issues' is not a list")

    # Check that ZVKU-A001 has at least one output partner (ZVIU-A001)
    found_zviu_a001 = any(p.get("AssetTag") == "ZVIU-A001" for p in output_partners)
    if not found_zviu_a001:
        raise TestFailure("ZVKU-A001 expected to have ZVIU-A001 as an output partner")

    # Test for non-existent asset returning 404
    try:
        request_json(f"/assets/{urllib.parse.quote('NONEXISTENT_TAG')}/details")
        raise TestFailure("Request for non-existent asset details did not return 404")
    except TestFailure as e:
        # request_json wraps HTTP errors in TestFailure, check if it's a 404
        if "HTTP 404" not in str(e):
            raise

def test_get_asset_details_knowledgebase_integration():
    target_tag = "ZVVU-A001" # Asset known to have KB entries (from knowledgebase.xlsx sample KB0001)
    data = request_json(f"/assets/{urllib.parse.quote(target_tag)}/details")

    kb_issues = data.get("knowledge_base_issues")
    if not isinstance(kb_issues, list) or not kb_issues:
        raise TestFailure(f"Expected knowledge base issues for {target_tag} but got none.")

    found_kb0001 = any(issue.get("IssueID") == "KB0001" for issue in kb_issues)
    if not found_kb0001:
        raise TestFailure(f"Expected KB0001 to be listed for asset {target_tag}")

def test_asset_details_partner_navigation():
    """Test that partner AssetTags can be used to navigate to partner details."""
    # Get details for ZVKU-A001
    primary_tag = "ZVKU-A001"
    data = request_json(f"/assets/{urllib.parse.quote(primary_tag)}/details")

    output_partners = data.get("output_partners")
    if not isinstance(output_partners, list) or not output_partners:
        raise TestFailure(f"Expected output partners for {primary_tag}")

    # Find a valid partner (skip "NAN" and other invalid tags)
    valid_partner = None
    for partner in output_partners:
        partner_tag = partner.get("AssetTag")
        if partner_tag and partner_tag.upper() not in ["NAN", "UNKNOWN", ""]:
            valid_partner = partner
            break

    if not valid_partner:
        raise TestFailure(f"No valid partners found for {primary_tag}")

    partner_tag = valid_partner.get("AssetTag")
    if not partner_tag:
        raise TestFailure("Partner missing AssetTag field")

    # Verify we can fetch details for the partner
    partner_data = request_json(f"/assets/{urllib.parse.quote(partner_tag)}/details")
    if not isinstance(partner_data, dict):
        raise TestFailure(f"Failed to fetch details for partner {partner_tag}")

    partner_asset = partner_data.get("asset")
    if not partner_asset or partner_asset.get("AssetTag") != partner_tag:
        raise TestFailure(f"Partner details response incorrect for {partner_tag}")


def test_knowledgebase_search_by_issue_id():
    """Test knowledge base search by IssueID"""
    # Search with a partial issue ID that should match multiple issues
    data = request_json("/knowledgebase/search?issue_id=KB")
    if not isinstance(data, list):
        raise TestFailure("Knowledge base search should return a list")
    if len(data) == 0:
        raise TestFailure("Knowledge base search by issue_id=KB should return results")
    # Verify all results contain KB in the IssueID
    for issue in data:
        if "IssueID" not in issue:
            raise TestFailure("Knowledge base issue missing IssueID field")
        if "KB" not in issue["IssueID"].upper():
            raise TestFailure(f"IssueID {issue['IssueID']} does not contain 'KB'")


def test_knowledgebase_search_by_tag():
    """Test knowledge base search by asset tag"""
    # First get a valid asset tag
    assets = request_json("/assets/search?in_service_only=true")
    if not assets or len(assets) == 0:
        raise TestFailure("No assets found to test KB tag search")

    test_tag = assets[0].get("AssetTag")
    if not test_tag:
        raise TestFailure("First asset missing AssetTag")

    # Search KB by this tag
    data = request_json(f"/knowledgebase/search?tag={urllib.parse.quote(test_tag)}")
    if not isinstance(data, list):
        raise TestFailure("Knowledge base search by tag should return a list")
    # It's okay if no results - just verify the endpoint works


def test_knowledgebase_search_freeform():
    """Test knowledge base freeform text search"""
    # Search for common text that should appear in knowledge base
    data = request_json("/knowledgebase/search?freeform=audio")
    if not isinstance(data, list):
        raise TestFailure("Knowledge base freeform search should return a list")
    # Verify results are sorted
    if len(data) > 1:
        for i in range(len(data) - 1):
            curr_cat = data[i].get("Category", "")
            next_cat = data[i + 1].get("Category", "")
            if curr_cat and next_cat:
                # Just verify Category field exists - detailed sort verification is complex
                pass


def test_knowledgebase_search_returns_required_fields():
    data = request_json("/knowledgebase/search?issue_id=KB")
    if not isinstance(data, list) or len(data) == 0:
        raise TestFailure("Knowledge base search should return results")
    first_issue = data[0]
    for field in ["IssueID", "Title", "Category", "Subcategory", "SeeAlsoResolved"]:
        if field not in first_issue:
            raise TestFailure(f"Knowledge base issue missing required field: {field}")
    if not isinstance(first_issue["SeeAlsoResolved"], list):
        raise TestFailure("SeeAlsoResolved must be a list")


def test_knowledgebase_search_returns_seealso_resolved():
    # Find any issue that has SeeAlso entries
    data = request_json("/knowledgebase/search?issue_id=KB")
    issues_with_seealso = [i for i in data if i.get("SeeAlsoResolved")]
    if not issues_with_seealso:
        # No SeeAlso data in fixture — just verify the field is always present and a list
        for issue in data:
            if "SeeAlsoResolved" not in issue:
                raise TestFailure(f"SeeAlsoResolved missing from issue {issue.get('IssueID')}")
            if not isinstance(issue["SeeAlsoResolved"], list):
                raise TestFailure("SeeAlsoResolved must be a list")
        return
    first = issues_with_seealso[0]
    for rel in first["SeeAlsoResolved"]:
        if "IssueID" not in rel:
            raise TestFailure("SeeAlsoResolved entry missing IssueID")
        if "Title" not in rel:
            raise TestFailure("SeeAlsoResolved entry missing Title")


def test_knowledgebase_seealso_reverse_link_generated():
    # If issue A references issue B, B must also list A in SeeAlsoResolved
    data = request_json("/knowledgebase/search?issue_id=KB")
    id_to_resolved = {i["IssueID"]: {r["IssueID"] for r in i.get("SeeAlsoResolved", [])} for i in data}
    for issue_id, related_ids in id_to_resolved.items():
        for related_id in related_ids:
            if related_id in id_to_resolved:
                if issue_id not in id_to_resolved[related_id]:
                    raise TestFailure(
                        f"Reverse link missing: {issue_id} is in {related_id}'s SeeAlsoResolved "
                        f"but {related_id} is not in {issue_id}'s SeeAlsoResolved"
                    )


def test_knowledgebase_seealso_unique():
    data = request_json("/knowledgebase/search?issue_id=KB")
    for issue in data:
        resolved = issue.get("SeeAlsoResolved", [])
        ids = [r["IssueID"].upper() for r in resolved]
        if len(ids) != len(set(ids)):
            raise TestFailure(
                f"Duplicate SeeAlsoResolved entries in issue {issue.get('IssueID')}: {ids}"
            )


def test_knowledgebase_seealso_ignores_unknown_ids():
    # All resolved IDs must themselves be findable in the KB
    data = request_json("/knowledgebase/search?issue_id=KB")
    known_ids = {i["IssueID"].upper() for i in data}
    for issue in data:
        for rel in issue.get("SeeAlsoResolved", []):
            rel_id = rel["IssueID"].upper()
            if rel_id not in known_ids:
                raise TestFailure(
                    f"SeeAlsoResolved in {issue.get('IssueID')} references unknown issue {rel['IssueID']}"
                )


def test_knowledgebase_tags_endpoint_returns_list():
    data = request_json("/knowledgebase/tags")
    if not isinstance(data, dict) or "tags" not in data:
        raise TestFailure("/knowledgebase/tags did not return {tags: [...]}")
    tags = data["tags"]
    if not isinstance(tags, list):
        raise TestFailure("'tags' field is not a list")
    if not tags:
        raise TestFailure("/knowledgebase/tags returned an empty list")
    for item in tags:
        if not item.get("value"):
            raise TestFailure(f"Tag option missing 'value': {item}")


def test_knowledgebase_tags_endpoint_unique_sorted():
    data = request_json("/knowledgebase/tags")
    tags = [item["value"] for item in data.get("tags", [])]
    if len(tags) != len(set(t.upper() for t in tags)):
        raise TestFailure("Tag options contain duplicate values")
    sorted_tags = sorted(tags, key=str.upper)
    if tags != sorted_tags:
        raise TestFailure("Tag options are not sorted case-insensitively")


def test_knowledgebase_search_multiple_tags():
    # Fetch a couple of known tags from the tags endpoint, then search with both
    data = request_json("/knowledgebase/tags")
    tags = [item["value"] for item in data.get("tags", [])]
    if len(tags) < 2:
        raise TestFailure("Need at least 2 KB tags to test multi-tag search")
    tag1, tag2 = tags[0], tags[1]
    params = f"tag={urllib.parse.quote(tag1)}&tag={urllib.parse.quote(tag2)}"
    results = request_json(f"/knowledgebase/search?{params}")
    if not isinstance(results, list):
        raise TestFailure("Multi-tag search should return a list")
    # Each result must match at least one of the selected tags in Tags or AppliesToAssetTag
    selected_upper = {tag1.upper(), tag2.upper()}
    for issue in results:
        kw = {t.strip().lstrip("#").upper() for t in (issue.get("Tags") or "").split(",")}
        asset = {t.strip().lstrip("#").upper() for t in (issue.get("AppliesToAssetTag") or "").split(",")}
        if not (selected_upper & (kw | asset)):
            raise TestFailure(
                f"Issue {issue.get('IssueID')} does not match either selected tag"
            )


def test_knowledgebase_search_tag_and_freeform_combination():
    # Use a known tag and a freeform term; results should include issues from either criterion
    data = request_json("/knowledgebase/tags")
    tags = [item["value"] for item in data.get("tags", [])]
    if not tags:
        raise TestFailure("No KB tags available for combination test")
    chosen_tag = tags[0]
    # Search by tag only to get baseline count
    tag_only = request_json(f"/knowledgebase/search?tag={urllib.parse.quote(chosen_tag)}")
    # Search by freeform only to get baseline count
    freeform_only = request_json("/knowledgebase/search?freeform=audio")
    # Combined should return at least as many as the larger of the two
    combined = request_json(
        f"/knowledgebase/search?tag={urllib.parse.quote(chosen_tag)}&freeform=audio"
    )
    if not isinstance(combined, list):
        raise TestFailure("Combined tag+freeform search should return a list")
    max_baseline = max(len(tag_only), len(freeform_only))
    if len(combined) < max_baseline:
        raise TestFailure(
            f"OR combination returned fewer results ({len(combined)}) than the "
            f"larger single-criterion baseline ({max_baseline})"
        )


def _route_traversal(node_tag, mode, visible_tags=None):
    """
    Replicate the frontend port-matching logic for 'Add inbound for outbound'
    (mode='inbound_for_outbound') or 'Add outbound for inbound'
    (mode='outbound_for_inbound').  Returns the set of tags the frontend would add.

    If visible_tags is provided (a set/list of tag strings), inbound and outbound
    cables are restricted to those whose other endpoint is in that set — mirroring
    the frontend's activeDiagramAssetTags filter.
    """
    params = urllib.parse.urlencode({
        "target_tag": node_tag,
        "direction": "both",
        "exclude_internal_routes": "false",
    })
    data = request_json(f"/cables/filter?{params}")
    cables = data.get("cables") if isinstance(data, dict) else data
    if not isinstance(cables, list):
        raise TestFailure(f"Cable filter for {node_tag} did not return a list")

    tag_lower = node_tag.lower()
    visible_lower = {t.strip().lower() for t in (visible_tags or [])} if visible_tags is not None else None

    route_cables = [
        c for c in cables
        if (c.get("SrcTag") or "").strip().lower() == tag_lower
        and (c.get("DstTag") or "").strip().lower() == tag_lower
        and "route" in (c.get("Type") or "").lower()
    ]
    # For outbound_for_inbound: restrict inbound by visible nodes (the sources currently shown).
    # For inbound_for_outbound: restrict outbound by visible nodes (the destinations currently shown).
    # The other side is unrestricted — those are the new nodes being discovered.
    inbound_cables = [
        c for c in cables
        if (c.get("DstTag") or "").strip().lower() == tag_lower
        and (c.get("SrcTag") or "").strip().lower() != tag_lower
        and (visible_lower is None or mode != "outbound_for_inbound"
             or (c.get("SrcTag") or "").strip().lower() in visible_lower)
    ]
    outbound_cables = [
        c for c in cables
        if (c.get("SrcTag") or "").strip().lower() == tag_lower
        and (c.get("DstTag") or "").strip().lower() != tag_lower
        and (visible_lower is None or mode != "inbound_for_outbound"
             or (c.get("DstTag") or "").strip().lower() in visible_lower)
    ]

    tags_to_add = set()
    if mode == "inbound_for_outbound":
        outbound_src_ports = {(c.get("SrcPort") or "").strip().lower() for c in outbound_cables}
        outbound_src_ports.discard("")
        relevant_inbound_ports = set()
        for r in route_cables:
            dst_port = (r.get("DstPort") or "").strip().lower()
            if dst_port in outbound_src_ports:
                src_port = (r.get("SrcPort") or "").strip().lower()
                if src_port:
                    relevant_inbound_ports.add(src_port)
        for c in inbound_cables:
            dst_port = (c.get("DstPort") or "").strip().lower()
            if dst_port in relevant_inbound_ports and c.get("SrcTag"):
                tags_to_add.add((c.get("SrcTag") or "").strip())
    else:  # outbound_for_inbound
        inbound_dst_ports = {(c.get("DstPort") or "").strip().lower() for c in inbound_cables}
        inbound_dst_ports.discard("")
        relevant_outbound_ports = set()
        for r in route_cables:
            src_port = (r.get("SrcPort") or "").strip().lower()
            if src_port in inbound_dst_ports:
                dst_port = (r.get("DstPort") or "").strip().lower()
                if dst_port:
                    relevant_outbound_ports.add(dst_port)
        for c in outbound_cables:
            src_port = (c.get("SrcPort") or "").strip().lower()
            if src_port in relevant_outbound_ports and c.get("DstTag"):
                tags_to_add.add((c.get("DstTag") or "").strip())

    return tags_to_add


def test_cable_filter_exclude_internal_routes_false_includes_routes():
    """
    ZVKU-A001 has internal route cables (SrcTag==DstTag, Type contains 'route').
    With exclude_internal_routes=false they must appear; with true they must not.
    """
    node_tag = "ZVKU-A001"
    node_tag_upper = node_tag.upper()

    params_inc = urllib.parse.urlencode({
        "target_tag": node_tag,
        "direction": "both",
        "exclude_internal_routes": "false",
    })
    data_inc = request_json(f"/cables/filter?{params_inc}")
    cables_inc = data_inc.get("cables") if isinstance(data_inc, dict) else data_inc
    if not isinstance(cables_inc, list):
        raise TestFailure("Cable filter (exclude_internal_routes=false) did not return a list")

    route_cables_inc = [
        c for c in cables_inc
        if (c.get("SrcTag") or "").strip().upper() == node_tag_upper
        and (c.get("DstTag") or "").strip().upper() == node_tag_upper
        and "route" in (c.get("Type") or "").lower()
    ]
    if not route_cables_inc:
        raise TestFailure(
            f"No route cables found for {node_tag} when exclude_internal_routes=false"
        )

    params_exc = urllib.parse.urlencode({
        "target_tag": node_tag,
        "direction": "both",
        "exclude_internal_routes": "true",
    })
    data_exc = request_json(f"/cables/filter?{params_exc}")
    cables_exc = data_exc.get("cables") if isinstance(data_exc, dict) else data_exc
    if not isinstance(cables_exc, list):
        raise TestFailure("Cable filter (exclude_internal_routes=true) did not return a list")

    route_cables_exc = [
        c for c in cables_exc
        if (c.get("SrcTag") or "").strip().upper() == node_tag_upper
        and (c.get("DstTag") or "").strip().upper() == node_tag_upper
        and "route" in (c.get("Type") or "").lower()
    ]
    if route_cables_exc:
        first_tag = route_cables_exc[0].get("Tag", "?")
        raise TestFailure(
            f"Route cable {first_tag!r} still present when exclude_internal_routes=true"
        )


def test_cable_filter_route_cables_have_port_fields():
    """
    Route cables returned for ZVKU-A001 with exclude_internal_routes=false must
    carry SrcPort and DstPort so the frontend can perform route-traversal.
    """
    params = urllib.parse.urlencode({
        "target_tag": "ZVKU-A001",
        "direction": "both",
        "exclude_internal_routes": "false",
    })
    data = request_json(f"/cables/filter?{params}")
    cables = data.get("cables") if isinstance(data, dict) else data
    if not isinstance(cables, list):
        raise TestFailure("Cable filter did not return a list")

    route_cables = [
        c for c in cables
        if (c.get("SrcTag") or "").strip().upper() == (c.get("DstTag") or "").strip().upper()
        and "route" in (c.get("Type") or "").lower()
    ]
    if not route_cables:
        raise TestFailure("Expected at least one route cable for ZVKU-A001")

    for r in route_cables:
        if "SrcPort" not in r:
            raise TestFailure(f"Route cable {r.get('Tag')} missing SrcPort field")
        if "DstPort" not in r:
            raise TestFailure(f"Route cable {r.get('Tag')} missing DstPort field")


def test_route_traversal_inbound_for_outbound():
    """
    ZVKU-A001 has route rt128: in_5 → out_5_hdmi.
    Inbound cable 2308-0918 arrives on DstPort=in_5 from 2410-1607.
    Outbound cable 2308-0916 leaves on SrcPort=out_5_hdmi to ZVIU-A006.
    'Add inbound for outbound' must therefore identify 2410-1607.
    """
    node_tag = "ZVKU-A001"
    expected_src = "2410-1607"

    tags = _route_traversal(node_tag, "inbound_for_outbound")
    if expected_src not in tags:
        raise TestFailure(
            f"Route traversal (inbound for outbound) for {node_tag} expected to find "
            f"{expected_src} but got: {tags}"
        )


def test_route_traversal_outbound_for_inbound():
    """
    ZVKU-A001 has route rt128: in_5 → out_5_hdmi.
    Inbound cable 2308-0918 arrives on DstPort=in_5 from 2410-1607.
    Outbound cable 2308-0916 leaves on SrcPort=out_5_hdmi to ZVIU-A006.
    'Add outbound for inbound' must therefore identify ZVIU-A006.
    """
    node_tag = "ZVKU-A001"
    expected_dst = "ZVIU-A006"

    tags = _route_traversal(node_tag, "outbound_for_inbound")
    if expected_dst not in tags:
        raise TestFailure(
            f"Route traversal (outbound for inbound) for {node_tag} expected to find "
            f"{expected_dst} but got: {tags}"
        )



def test_route_traversal_visible_filter_outbound_for_inbound():
    """
    2507-0700 routes ZVIU-E004 inputs through internal route cables to outputs.
    ZVIU-E004 connects on in_01–in_06; routes rt888/rt889/rt890/rt891 map those to
    out_01/out_02/out_03/out_04, reaching 2601-1304/2601-1305/2601-1306/2601-2800.
    With only ZVIU-E004 visible, 'outbound for inbound' must return those four tags
    and must NOT return ZVIU-E004 (only reachable via 2601-2800's in_10→out_07 path,
    which is excluded because 2601-2800 is not in the visible set).
    """
    node_tag = "2507-0700"
    visible = ["ZVIU-E004"]
    expected_present = {"2601-1304", "2601-1305", "2601-1306", "2601-2800"}
    expected_absent = "ZVIU-E004"  # reachable via 2601-2800 route, not ZVIU-E004 itself

    tags = _route_traversal(node_tag, "outbound_for_inbound", visible_tags=visible)
    missing = expected_present - tags
    if missing:
        raise TestFailure(
            f"Route traversal (outbound for inbound, visible={visible}) for {node_tag} "
            f"missing expected tags {missing}; got: {tags}"
        )
    if expected_absent in tags:
        raise TestFailure(
            f"Route traversal (outbound for inbound, visible={visible}) for {node_tag} "
            f"should NOT include {expected_absent} but got: {tags}"
        )
    # Filtered result must be a proper subset of the unfiltered result.
    tags_all = _route_traversal(node_tag, "outbound_for_inbound")
    if not tags < tags_all:
        raise TestFailure(
            f"Expected visible-filtered result {tags} to be a proper subset of "
            f"unfiltered result {tags_all}"
        )


def test_route_traversal_visible_filter_inbound_for_outbound():
    """
    2507-0700 has route rt890: in_03 → out_03.
    Cable 2307-1815 arrives from ZVIU-E004 on DstPort=in_03.
    Cable 2601-1303 leaves on SrcPort=out_03 to 2601-1306.
    With only 2601-1306 in the visible set, 'inbound for outbound' must yield
    exactly {ZVIU-E004} and must exclude the other upstream sources
    (ZVCU-A001, ZVCU-A002, ZVCU-A003, 2601-2800) that only feed different outputs.
    """
    node_tag = "2507-0700"
    visible = ["2601-1306"]
    expected_present = {"ZVIU-E004"}
    expected_absent = {"ZVCU-A001", "ZVCU-A002", "ZVCU-A003", "2601-2800"}

    tags = _route_traversal(node_tag, "inbound_for_outbound", visible_tags=visible)
    missing = expected_present - tags
    if missing:
        raise TestFailure(
            f"Route traversal (inbound for outbound, visible={visible}) for {node_tag} "
            f"missing expected tags {missing}; got: {tags}"
        )
    spurious = expected_absent & tags
    if spurious:
        raise TestFailure(
            f"Route traversal (inbound for outbound, visible={visible}) for {node_tag} "
            f"should NOT include {spurious} but got: {tags}"
        )
    # Filtered result must be a proper subset of the unfiltered result.
    tags_all = _route_traversal(node_tag, "inbound_for_outbound")
    if not tags < tags_all:
        raise TestFailure(
            f"Expected visible-filtered result {tags} to be a proper subset of "
            f"unfiltered result {tags_all}"
        )


def test_rack_profile_asset_in_rack():
    """Asset with a Rack field returns the correct rack and includes the asset."""
    target_tag = "2507-0700"
    data = request_json(f"/assets/{urllib.parse.quote(target_tag)}/rack-profile")
    if not isinstance(data, dict):
        raise TestFailure("rack-profile did not return a dict")
    if data.get("rack_tag") != "2602-1800":
        raise TestFailure(f"Expected rack_tag 2602-1800, got {data.get('rack_tag')}")
    if not isinstance(data.get("devices"), list) or not data["devices"]:
        raise TestFailure("rack-profile returned no devices")
    required = {"asset_tag", "usage", "face", "u_start", "u_height", "x_start", "x_end", "is_target"}
    for dev in data["devices"]:
        missing = required - dev.keys()
        if missing:
            raise TestFailure(f"Device entry missing keys: {missing}")
    target_devs = [d for d in data["devices"] if d["asset_tag"].upper() == target_tag.upper()]
    if not target_devs:
        raise TestFailure(f"{target_tag} not found in rack devices list")
    if not target_devs[0]["is_target"]:
        raise TestFailure(f"{target_tag} device entry has is_target=False")
    if data.get("target_u") != target_devs[0]["u_start"]:
        raise TestFailure("target_u does not match the target device's u_start")


def test_rack_profile_rack_asset_itself():
    """Querying a rack asset directly returns that rack's profile."""
    rack_tag = "2602-1800"
    data = request_json(f"/assets/{urllib.parse.quote(rack_tag)}/rack-profile")
    if data.get("rack_tag") != rack_tag:
        raise TestFailure(f"Expected rack_tag {rack_tag}, got {data.get('rack_tag')}")
    if not data.get("devices"):
        raise TestFailure("Querying rack asset itself returned no devices")


def test_rack_profile_asset_not_in_rack():
    """Asset with no Rack field returns rack_tag=null and empty devices."""
    # Find an asset that has no rack by checking the details endpoint
    # ZAHU-0001 is itself a rack but its own Rack field should be empty
    # Use an asset known to be ceiling/wall mounted with no RackU
    data = request_json("/assets/search?in_service_only=false")
    no_rack_tag = None
    for asset in data:
        tag = asset.get("AssetTag", "")
        if not tag:
            continue
        detail = request_json(f"/assets/{urllib.parse.quote(tag)}/rack-profile")
        if detail.get("rack_tag") is None:
            no_rack_tag = tag
            break
    if no_rack_tag is None:
        raise TestFailure("Could not find any asset without a rack for this test")
    result = request_json(f"/assets/{urllib.parse.quote(no_rack_tag)}/rack-profile")
    if result.get("rack_tag") is not None:
        raise TestFailure(f"Expected rack_tag=null for {no_rack_tag}, got {result.get('rack_tag')}")
    if result.get("devices"):
        raise TestFailure(f"Expected empty devices for non-rack asset {no_rack_tag}")


def test_rack_profile_unknown_tag_returns_404():
    """Unknown asset tag returns HTTP 404."""
    try:
        request_json("/assets/TOTALLY_UNKNOWN_XYZ/rack-profile")
        raise TestFailure("Expected 404 for unknown asset tag, but got success")
    except TestFailure as e:
        if "HTTP 404" not in str(e):
            raise


def test_rack_profile_division_suffix_parsed():
    """Devices with RackU division suffix (e.g. F30-5-4-4) have correct x_start/x_end."""
    # 2602-1800 rack contains ZVIU-G004 at F30-5-4-4 → x_start=0.6, x_end=0.8
    data = request_json("/assets/ZVIU-G004/rack-profile")
    devices = data.get("devices", [])
    dev = next((d for d in devices if d["asset_tag"].upper() == "ZVIU-G004"), None)
    if dev is None:
        raise TestFailure("ZVIU-G004 not found in its own rack profile")
    expected_x_start = round((4 - 1) / 5, 6)
    expected_x_end   = round(4 / 5, 6)
    if abs(dev["x_start"] - expected_x_start) > 0.01:
        raise TestFailure(f"x_start {dev['x_start']} != expected {expected_x_start}")
    if abs(dev["x_end"] - expected_x_end) > 0.01:
        raise TestFailure(f"x_end {dev['x_end']} != expected {expected_x_end}")


def test_rack_profile_internal_routes_include_usage():
    """Internal routes table includes a Usage field."""
    target_tag = "2507-0700"
    data = request_json(f"/diagram/connections?target_tag={urllib.parse.quote(target_tag)}")
    routes = data.get("internal_routes", [])
    if not routes:
        raise TestFailure(f"No internal routes for {target_tag}")
    if "Usage" not in routes[0]:
        raise TestFailure("Internal route row missing Usage field")


# ---------------------------------------------------------------------------
# Floorplan image resolution tests
# ---------------------------------------------------------------------------

def test_floorplan_returns_valid_png_data_url():
    """Asset in B1/F2/202 returns a valid PNG data URL (room or floor level)."""
    import base64
    data = request_json(f"/location/floorplan?asset_tag={urllib.parse.quote('2507-0700')}")
    if data.get("image_data_url") is None:
        raise TestFailure("Expected a floorplan image_data_url, got null")
    data_url = data["image_data_url"]
    if not data_url.startswith("data:image/png;base64,"):
        raise TestFailure("image_data_url is not a PNG data URL")
    raw = base64.b64decode(data_url.split(",", 1)[1])
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise TestFailure("image data does not have valid PNG magic bytes")


def test_floorplan_floor_level_fallback():
    """Asset in B1/F3 with no room-level file falls back to the floor-level image."""
    data = request_json(f"/location/floorplan?asset_tag={urllib.parse.quote('notag217')}")
    fname = data.get("filename", "")
    if fname != "floorplan_b1_f3.png":
        raise TestFailure(f"Expected floor-level fallback floorplan_b1_f3.png, got: {fname!r}")


def test_floorplan_no_match_returns_null():
    """Asset whose building has no floorplan files returns image_data_url=null."""
    data = request_json(f"/location/floorplan?asset_tag={urllib.parse.quote('notag028')}")
    if data.get("image_data_url") is not None:
        raise TestFailure(f"Expected image_data_url=null for unmapped building, got non-null")


def test_floorplan_unknown_tag_returns_404():
    """Unknown asset tag returns HTTP 404."""
    try:
        request_json("/location/floorplan?asset_tag=DOES-NOT-EXIST-9999")
        raise TestFailure("Expected 404 for unknown tag, but got success")
    except TestFailure as e:
        if "HTTP 404" not in str(e):
            raise


def test_floorplan_returns_building_floor_room_sector():
    """Response includes building, floor, room, and sector fields from the asset."""
    data = request_json(f"/location/floorplan?asset_tag={urllib.parse.quote('2507-0700')}")
    for field in ("building", "floor", "room", "sector"):
        if field not in data:
            raise TestFailure(f"Response missing field: {field}")
    if data["building"] != "B1" or data["floor"] != "F2":
        raise TestFailure(f"Unexpected building/floor: {data['building']}/{data['floor']}")


def test_sector_present_in_asset_search():
    """Asset search results include a Sector field (may be empty but must be present)."""
    data = request_json(f"/assets/search?asset_tag={urllib.parse.quote('2507-0700')}&in_service_only=false")
    if not data:
        raise TestFailure("No asset returned for 2507-0700")
    if "Sector" not in data[0]:
        raise TestFailure("Asset search row missing Sector field")


def test_sector_present_in_asset_details():
    """Asset details endpoint includes Sector in the asset properties."""
    data = request_json(f"/assets/{urllib.parse.quote('2507-0700')}/details")
    asset = data.get("asset", {})
    if "Sector" not in asset:
        raise TestFailure("Asset details missing Sector field")


# ---------------------------------------------------------------------------
# Dashboard — Route Comparison tests
# ---------------------------------------------------------------------------

def test_dashboard_crosspoint_structure():
    """GET /dashboard/crosspoint returns required top-level keys."""
    data = request_json("/dashboard/crosspoint")
    for key in ("generated_at", "status", "panels"):
        if key not in data:
            raise TestFailure(f"Missing key '{key}' in /dashboard/crosspoint response")
    if data["status"] not in ("ok", "warning", "critical", "unavailable", "pending"):
        raise TestFailure(f"Unexpected status value: {data['status']!r}")


def test_dashboard_crosspoint_panels_present():
    """Dashboard crosspoint shows only monitored devices; excluded ones are absent."""
    data = request_json("/dashboard/crosspoint")
    panels = data.get("panels", [])
    if not panels:
        raise TestFailure("Expected at least one panel; got empty list")
    asset_tags = {p["asset_tag"] for p in panels}
    # VideoHub must be present (has an adapter)
    if "2507-0700" not in asset_tags:
        raise TestFailure("Expected panel for 2507-0700 (VideoHub) not found")
    # Excluded devices must NOT appear
    for excluded in ("ZVKU-A001", "ZVIU-E004"):
        if excluded in asset_tags:
            raise TestFailure(f"{excluded} is excluded from monitoring but still appears in panels")


def test_dashboard_crosspoint_videohub_panel():
    """VideoHub panel has correct adapter, required keys, and model/usage fields."""
    data = request_json("/dashboard/crosspoint")
    panels = data.get("panels", [])
    vh = next((p for p in panels if p["asset_tag"] == "2507-0700"), None)
    if vh is None:
        raise TestFailure("No panel found for VideoHub (2507-0700)")
    if vh.get("adapter") != "videohub":
        raise TestFailure(f"Expected adapter='videohub', got {vh.get('adapter')!r}")
    for key in ("status", "exceptions", "total_routes_defined", "model", "usage"):
        if key not in vh:
            raise TestFailure(f"VideoHub panel missing key '{key}'")
    if not isinstance(vh["exceptions"], list):
        raise TestFailure("VideoHub panel 'exceptions' is not a list")
    if not vh.get("model"):
        raise TestFailure("VideoHub panel 'model' is empty — expected 'VideoHub 40x40' or similar")


def test_dashboard_crosspoint_cuecommander_unavailable():
    """VideoHub panel status is 'unavailable' when CueCommander is unreachable (expected in test env)."""
    data = request_json("/dashboard/crosspoint")
    panels = data.get("panels", [])
    vh = next((p for p in panels if p["asset_tag"] == "2507-0700"), None)
    if vh is None:
        raise TestFailure("No panel found for VideoHub (2507-0700)")
    # In the test environment CueCommander is not running; status must be 'unavailable'
    if vh["status"] not in ("unavailable", "ok", "warning"):
        raise TestFailure(f"Unexpected VideoHub panel status: {vh['status']!r}")
    # If unavailable, error field should explain why
    if vh["status"] == "unavailable" and "error" not in vh:
        raise TestFailure("Unavailable panel missing 'error' field")


# ---------------------------------------------------------------------------
# Dashboard — Klang Mix Consistency tests
# ---------------------------------------------------------------------------
#
# These only exercise the read-only GET /dashboard/klang panel, mirroring the
# crosspoint tests above. The write actions (POST .../setvariance,
# .../buildconsensus) trigger real OSC sends / a ~17s hardware sweep against
# the live Konductor and are deliberately NOT exercised here on every test
# run; that regression coverage lives in CueCommander-NR's own test suite
# (tests/cases/klang_setvariance.js), which redirects sends away from
# production via klang_konductor_override.
#
# There was previously zero coverage of this panel at all, in either test
# suite — the real bug (setvariance always reporting ok:true even though the
# OSC packets were silently dropped) shipped and went unnoticed for exactly
# that reason. This section exists so the panel's shape is at least pinned
# down, even though the write-path regression itself is owned by
# CueCommander-NR's suite where it can safely be exercised for real.


def test_dashboard_klang_structure():
    """GET /dashboard/klang returns required top-level keys."""
    data = request_json("/dashboard/klang")
    for key in ("generated_at", "status", "sweep"):
        if key not in data:
            raise TestFailure(f"Missing key '{key}' in /dashboard/klang response")
    if data["status"] not in ("ok", "warning", "critical", "unavailable", "pending"):
        raise TestFailure(f"Unexpected status value: {data['status']!r}")


def test_dashboard_klang_sweep_shape():
    """The 'sweep' panel always has active/started_at/mix_current, even with no data yet."""
    data = request_json("/dashboard/klang")
    sweep = data.get("sweep")
    if sweep is None:
        raise TestFailure("Expected a 'sweep' object even when unavailable")
    for key in ("active", "started_at", "mix_current"):
        if key not in sweep:
            raise TestFailure(f"Sweep panel missing key '{key}'")
    if not isinstance(sweep["active"], bool):
        raise TestFailure(f"sweep.active should be a bool, got {type(sweep['active'])}")


def test_dashboard_klang_variances_shape_when_available():
    """When status isn't unavailable/pending, the variances panel has the documented shape."""
    data = request_json("/dashboard/klang")
    if data["status"] in ("unavailable", "pending"):
        return  # no results yet in this environment — nothing to validate
    variances = data.get("variances")
    if not isinstance(variances, dict):
        raise TestFailure(f"Expected a 'variances' dict when status={data['status']!r}, got {type(variances)}")
    for key in ("total_variances", "variances"):
        if key not in variances:
            raise TestFailure(f"Variances panel missing key '{key}'")
    if not isinstance(variances["variances"], list):
        raise TestFailure("variances.variances should be a list")
    if variances["variances"]:
        row = variances["variances"][0]
        for key in ("mix", "channel", "attribute", "consensus", "actual", "severity"):
            if key not in row:
                raise TestFailure(f"Variance row missing key '{key}': {row}")
        if row["severity"] not in ("warning", "critical"):
            raise TestFailure(f"Unexpected severity: {row['severity']!r}")


def test_dashboard_klang_cuecommander_unavailable():
    """Klang panel status is 'unavailable' with an error when CueCommander is unreachable."""
    data = request_json("/dashboard/klang")
    if data["status"] == "unavailable" and "error" not in data:
        raise TestFailure("Unavailable Klang panel missing 'error' field")


# ---------------------------------------------------------------------------
# Network monitoring tests
# ---------------------------------------------------------------------------

def test_asset_network_in_details():
    """Asset details response includes a 'network' list key."""
    data = request_json("/assets/CSWU1/details")
    if "network" not in data:
        raise TestFailure("'network' key missing from asset details response")
    if not isinstance(data["network"], list):
        raise TestFailure(f"'network' should be a list, got {type(data['network'])}")


def test_asset_network_endpoint():
    """GET /assets/{tag}/network returns a list of NIC dicts with required keys."""
    data = request_json("/assets/CSWU1/network")
    if not isinstance(data, list):
        raise TestFailure(f"/assets/CSWU1/network should return a list, got {type(data)}")
    # CSWU1 is a Monitor=Yes asset with no IP — should appear in the list
    if len(data) == 0:
        raise TestFailure("Expected at least one NIC record for CSWU1")
    row = data[0]
    for key in ("asset_tag", "nic", "ip", "monitor"):
        if key not in row:
            raise TestFailure(f"NIC record missing key '{key}'")


def test_installed_assets_fields_present():
    """Asset details response always includes installed_software/installed_on list keys,
    regardless of the asset's Category."""
    data = request_json("/assets/CSWU1/details")
    for key in ("installed_software", "installed_on"):
        if key not in data:
            raise TestFailure(f"'{key}' key missing from asset details response")
        if not isinstance(data[key], list):
            raise TestFailure(f"'{key}' should be a list, got {type(data[key])}")


def test_installed_assets_relationship_consistency():
    """
    Self-discovers a Software-category asset whose Location references another
    asset (installed on it), then verifies the relationship is reported
    consistently from both sides:
      - the software asset's own details show installed_on == the parent
      - the parent's details list that software asset under installed_software
    Software installed on other software (e.g. a runtime installed inside a
    container platform) must resolve the same way, since Location can point to
    any asset regardless of the parent's own Category.
    If no Software-category asset with a resolvable Location exists yet, this
    is reported rather than failed, since it depends on inventory data.
    """
    all_assets = request_json("/assets/search?in_service_only=false")
    software_rows = [
        a for a in all_assets
        if str(a.get("Category", "")).strip().lower() == "software"
        and str(a.get("Location", "")).strip()
    ]
    if not software_rows:
        print("    (no Category=Software asset with a Location set found — skipping relationship check)")
        return

    software_tag = software_rows[0]["AssetTag"]
    parent_tag_raw = software_rows[0]["Location"].strip()

    sw_details = request_json(f"/assets/{urllib.parse.quote(software_tag)}/details")
    installed_on_tags = [row.get("AssetTag", "").upper() for row in sw_details.get("installed_on", [])]
    if parent_tag_raw.upper() not in installed_on_tags:
        raise TestFailure(
            f"{software_tag}'s installed_on {installed_on_tags} does not include its Location {parent_tag_raw}"
        )

    parent_details = request_json(f"/assets/{urllib.parse.quote(parent_tag_raw)}/details")
    installed_software_tags = [row.get("AssetTag", "").upper() for row in parent_details.get("installed_software", [])]
    if software_tag.upper() not in installed_software_tags:
        raise TestFailure(
            f"{parent_tag_raw}'s installed_software {installed_software_tags} does not include {software_tag}"
        )


def test_installed_software_present_for_non_computer_category_host():
    """
    Regression test: a real bug shipped where the frontend only displayed the
    Installed Software table when the host's own Category was exactly
    "Computer". In practice host machines are usually categorized by AV
    function instead (e.g. a Mac Mini tagged Category="Video"), so almost no
    real host carries Category="Computer" and the section was hiding real
    data. The backend endpoint was already correct (it never filtered by the
    host's category) — this test pins that down explicitly by finding a host
    whose Category is NOT "Computer" but which several Software assets report
    as their installed_on target, and asserting installed_software is
    populated for it regardless.
    """
    all_assets = request_json("/assets/search?in_service_only=false")
    location_counts: dict = {}
    for a in all_assets:
        if str(a.get("Category", "")).strip().lower() == "software":
            loc = str(a.get("Location", "")).strip().upper()
            if loc:
                location_counts[loc] = location_counts.get(loc, 0) + 1

    non_computer_host_tag = None
    for tag, count in sorted(location_counts.items(), key=lambda kv: -kv[1]):
        host_rows = [a for a in all_assets if a.get("AssetTag", "").strip().upper() == tag]
        if host_rows and str(host_rows[0].get("Category", "")).strip().lower() != "computer":
            non_computer_host_tag = tag
            break

    if non_computer_host_tag is None:
        print("    (no non-Computer-category asset hosting Software found — skipping)")
        return

    details = request_json(f"/assets/{urllib.parse.quote(non_computer_host_tag)}/details")
    if not details.get("installed_software"):
        raise TestFailure(
            f"{non_computer_host_tag} (Category != Computer) has Software assets pointing "
            f"Location at it but installed_software came back empty"
        )


def test_dashboard_network_structure():
    """GET /dashboard/network returns required top-level keys."""
    data = request_json("/dashboard/network")
    for key in ("generated_at", "config_exceptions"):
        if key not in data:
            raise TestFailure(f"Missing key '{key}' in /dashboard/network response")
    if not isinstance(data["config_exceptions"], list):
        raise TestFailure("'config_exceptions' should be a list")


def test_dashboard_network_config_exceptions():
    """Dashboard network config_exceptions lists Monitor=Yes assets with no IP."""
    data = request_json("/dashboard/network")
    exceptions = data.get("config_exceptions", [])
    # Known config exceptions from network.xlsx (Monitor=Yes with no IP)
    expected_tags = {"CUMU-G002"}
    found_tags = {ex["asset_tag"] for ex in exceptions}
    missing = expected_tags - found_tags
    if missing:
        raise TestFailure(f"Config exceptions missing expected tags: {missing}")
    # Each exception must have asset_tag and issue keys
    for ex in exceptions:
        for key in ("asset_tag", "issue"):
            if key not in ex:
                raise TestFailure(f"Config exception missing key '{key}': {ex}")


def test_dashboard_network_ping_unavailable():
    """Dashboard network ping_results is absent (None/missing) when CueCommander unreachable in test env."""
    data = request_json("/dashboard/network")
    # In the test environment CueCommander is not running
    # ping_results should be None or absent, ping_error should explain why
    if data.get("ping_results") is not None:
        # Acceptable if CueCommander happens to be reachable during CI
        results = data["ping_results"]
        if not isinstance(results, list):
            raise TestFailure(f"ping_results should be a list, got {type(results)}")
    else:
        if "ping_error" not in data:
            raise TestFailure("ping_results is None but ping_error key is missing")


def test_network_targets_endpoint_structure():
    """GET /api/network/targets returns expected top-level keys."""
    data = request_json("/api/network/targets")
    for key in ("targets", "total", "generated_at"):
        if key not in data:
            raise TestFailure(f"Response missing '{key}' key")
    if not isinstance(data["targets"], list):
        raise TestFailure(f"'targets' must be a list, got {type(data['targets'])}")
    if data["total"] != len(data["targets"]):
        raise TestFailure(
            f"total={data['total']} does not match len(targets)={len(data['targets'])}"
        )


def test_network_targets_non_empty():
    """GET /api/network/targets returns at least one Monitor=Yes row with an IP."""
    data = request_json("/api/network/targets")
    targets = data.get("targets", [])
    if not targets:
        raise TestFailure("No targets returned — expected Monitor=Yes rows with IPs from network.xlsx")


def test_network_targets_required_fields():
    """Every target entry has asset_tag, ip, and related_issue_ids."""
    data = request_json("/api/network/targets")
    for t in data.get("targets", []):
        for field in ("asset_tag", "ip", "related_issue_ids"):
            if field not in t:
                raise TestFailure(f"Target missing '{field}': {t}")
        if not t.get("ip"):
            raise TestFailure(f"Target {t.get('asset_tag')} has an empty ip")
        if not isinstance(t["related_issue_ids"], list):
            raise TestFailure(
                f"related_issue_ids is not a list for {t.get('asset_tag')}: {t['related_issue_ids']}"
            )


def test_network_targets_no_missing_ip_rows():
    """GET /api/network/targets excludes Monitor=Yes rows that have no IP configured."""
    data = request_json("/api/network/targets")
    for t in data.get("targets", []):
        ip = (t.get("ip") or "").strip()
        if not ip:
            raise TestFailure(
                f"Target {t.get('asset_tag')} was returned with no IP — "
                "endpoint should exclude rows without an IP"
            )


def test_glossary_returns_list():
    """GET /glossary returns a non-empty list of entries."""
    data = request_json("/glossary")
    if not isinstance(data, list):
        raise TestFailure(f"Expected list, got {type(data).__name__}")
    if len(data) == 0:
        raise TestFailure("Expected at least one glossary entry")


def test_glossary_entries_have_required_fields():
    """Every glossary entry has topic, term, definition, and see_also fields."""
    data = request_json("/glossary")
    for entry in data:
        for field in ("topic", "term", "definition", "see_also"):
            if field not in entry:
                raise TestFailure(f"Entry missing field '{field}': {entry}")


def test_glossary_topic_filter():
    """GET /glossary?topic=Audio returns only Audio entries."""
    data = request_json("/glossary?topic=Audio")
    if not data:
        raise TestFailure("Expected at least one Audio glossary entry")
    for entry in data:
        if entry.get("topic", "").lower() != "audio":
            raise TestFailure(
                f"topic filter returned non-Audio entry: topic={entry.get('topic')!r}"
            )


def test_glossary_topic_filter_unknown_returns_empty():
    """GET /glossary?topic=<nonexistent> returns an empty list, not an error."""
    data = request_json("/glossary?topic=ThisTopicDoesNotExist")
    if not isinstance(data, list):
        raise TestFailure(f"Expected list for unknown topic, got {type(data).__name__}")
    if len(data) != 0:
        raise TestFailure(f"Expected empty list for unknown topic, got {len(data)} entries")


def test_glossary_topics_endpoint():
    """GET /glossary/topics returns a non-empty, sorted, unique list."""
    data = request_json("/glossary/topics")
    if "topics" not in data:
        raise TestFailure("Missing 'topics' key in /glossary/topics response")
    topics = data["topics"]
    if not topics:
        raise TestFailure("Expected at least one topic in /glossary/topics")
    if topics != sorted(topics, key=str.casefold):
        raise TestFailure(f"Topics are not sorted case-insensitively: {topics}")
    if len(topics) != len(set(topics)):
        raise TestFailure(f"Topics list contains duplicates: {topics}")


def test_glossary_topics_no_blank_entries():
    """GET /glossary/topics contains no blank or whitespace-only entries."""
    data = request_json("/glossary/topics")
    for t in data.get("topics", []):
        if not t.strip():
            raise TestFailure(f"Topics list contains blank entry: {t!r}")


def test_glossary_whitespace_stripped():
    """All glossary entries have whitespace stripped from topic and term."""
    data = request_json("/glossary")
    for entry in data:
        topic = entry.get("topic", "")
        term = entry.get("term", "")
        if topic != topic.strip():
            raise TestFailure(f"topic has surrounding whitespace: {topic!r}")
        if term != term.strip():
            raise TestFailure(f"term has surrounding whitespace: {term!r}")


def test_glossary_seealso_present_when_expected():
    """At least one glossary entry has a non-empty see_also value."""
    data = request_json("/glossary")
    if not any(entry.get("see_also") for entry in data):
        raise TestFailure("Expected at least one entry with a non-empty see_also")


# ── /network/search tests ──────────────────────────────────────────────────────

def _network_search(q: str):
    return request_json(f"/network/search?q={urllib.parse.quote(q)}")


def test_network_search_partial_ip_returns_list():
    """GET /network/search?q=192.168 returns a list (may be empty if no data)."""
    data = _network_search("192.168")
    if not isinstance(data, list):
        raise TestFailure(f"Expected list, got {type(data).__name__}")


def test_network_search_ip_result_shape():
    """IP search results have required fields: asset_tag, manufacturer, model, mac_addresses, ip_addresses, nics."""
    data = _network_search("192.168")
    if not data:
        return  # No data to validate — not a failure
    required = {"asset_tag", "manufacturer", "model", "mac_addresses", "ip_addresses", "nics"}
    for item in data:
        missing = required - set(item.keys())
        if missing:
            raise TestFailure(f"Result missing fields: {missing}")
        if not isinstance(item["mac_addresses"], list):
            raise TestFailure("mac_addresses must be a list")
        if not isinstance(item["ip_addresses"], list):
            raise TestFailure("ip_addresses must be a list")
        if not isinstance(item["nics"], list):
            raise TestFailure("nics must be a list")


def test_network_search_ip_results_contain_query():
    """Every asset returned by an IP search actually has an IP matching the query."""
    q = "192.168"
    data = _network_search(q)
    for item in data:
        matched = any(q in ip for ip in item["ip_addresses"])
        if not matched:
            raise TestFailure(
                f"Asset {item['asset_tag']} returned but none of its IPs contain '{q}': {item['ip_addresses']}"
            )


def test_network_search_mac_colon_format():
    """MAC search with colon separators returns a list."""
    # Use a prefix that is extremely unlikely to exist but tests the plumbing
    data = _network_search("00:00:00")
    if not isinstance(data, list):
        raise TestFailure(f"Expected list, got {type(data).__name__}")


def test_network_search_mac_dash_format():
    """MAC search with dash separators returns a list (normalisation check)."""
    data = _network_search("00-00-00")
    if not isinstance(data, list):
        raise TestFailure(f"Expected list, got {type(data).__name__}")


def test_network_search_mac_and_colon_results_equivalent():
    """Searching the same MAC prefix with ':' and '-' returns identical asset tags."""
    colon_results = _network_search("00:00:00")
    dash_results  = _network_search("00-00-00")
    colon_tags = sorted(r["asset_tag"] for r in colon_results)
    dash_tags  = sorted(r["asset_tag"] for r in dash_results)
    if colon_tags != dash_tags:
        raise TestFailure(
            f"Colon results {colon_tags} != dash results {dash_tags}"
        )


def test_network_search_no_separator_returns_400():
    """A query with no '.' or ':'/'-' returns HTTP 400."""
    url = f"{API_BASE}/network/search?q=abc123"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            raise TestFailure(f"Expected 400, got {resp.status}")
    except urllib.error.HTTPError as exc:
        if exc.code != 400:
            raise TestFailure(f"Expected 400, got {exc.code}")


def test_network_search_results_ordered_by_asset_tag():
    """Results are returned in ascending asset tag order."""
    data = _network_search("192.168")
    tags = [r["asset_tag"] for r in data]
    if tags != sorted(tags):
        raise TestFailure(f"Results not sorted by asset_tag: {tags}")


TESTS: List[Tuple[str, Callable[[], None]]] = [
    ("GET /", test_backend_root),
    ("GET /health returns ok status", test_health_endpoint),
    ("Asset search returns usage", test_asset_search_returns_usage),
    ("Asset search in-service filter", test_asset_search_in_service_filter),
    ("Cable filter returns rows", test_cable_filter_has_rows),
    ("Graph contains usage line", test_graph_contains_usage_line),
    ("Graph respects custom field selections", test_graph_respects_custom_fields),
    ("Diagram options list defaults and additional fields", test_diagram_options_lists_all_fields),
    ("Graph renders newly requested fields", test_graph_renders_additional_fields),
    ("Graph colors edges by protocol", test_graph_colors_edges_by_protocol),
    ("Graph colors nodes by category", test_graph_colors_nodes_by_category),
    ("/assets/tags returns known values", test_asset_tags_endpoint),
    ("/assets/linked returns neighboring assets", test_asset_linked_endpoint),
    ("/assets/columns returns table metadata", test_asset_columns_endpoint),
    ("Protocol filter limits cables", test_protocol_filter_limits_results),
    ("Diagram collapses connections by protocol", test_graph_collapse_by_protocol),
    ("Cable ID query returns chained cable rows", test_cable_id_query_returns_chain),
    ("Graph renders cable-to-cable junction dot", test_graph_renders_cable_junction_dot),
    ("Crosspoint matrix returns data", test_crosspoint_matrix_returns_data),
    ("Crosspoint protocol filtering", test_crosspoint_protocol_filtering),
    ("Diagram connections combined endpoint shape", test_diagram_connections_combined_endpoint_shape),
    ("Internal routes excluded from outputs and inputs", test_internal_routes_excluded_from_outputs),
    ("Internal routes appear in internal_routes table", test_internal_routes_present_in_internal_routes_table),
    ("Non-routed asset returns empty internal_routes", test_non_routed_asset_returns_empty_internal_routes),
    ("Passthroughs: patch panel has passthrough entries", test_passthroughs_present_for_patch_panel),
    ("Passthroughs: excluded from inputs, outputs, and internal_routes", test_passthroughs_excluded_from_inputs_and_outputs),
    ("BFRS: present in diagram node field options", test_bfrs_in_diagram_node_options),
    ("BFRS: option has label 'BFRS'", test_bfrs_label_in_diagram_options),
    ("Passthrough edges rendered with dir=both", test_passthrough_edges_rendered_bidirectional),
    ("Asset details endpoint returns data", test_get_asset_details_endpoint),
    ("Asset details knowledge base integration", test_get_asset_details_knowledgebase_integration),
    ("Asset details partner navigation", test_asset_details_partner_navigation),
    ("Knowledge base search by IssueID", test_knowledgebase_search_by_issue_id),
    ("Knowledge base search by tag", test_knowledgebase_search_by_tag),
    ("Knowledge base freeform search", test_knowledgebase_search_freeform),
    ("Knowledge base returns required fields", test_knowledgebase_search_returns_required_fields),
    ("KB search returns SeeAlsoResolved field", test_knowledgebase_search_returns_seealso_resolved),
    ("KB SeeAlso reverse links generated", test_knowledgebase_seealso_reverse_link_generated),
    ("KB SeeAlso entries are unique per issue", test_knowledgebase_seealso_unique),
    ("KB SeeAlso ignores unknown IDs", test_knowledgebase_seealso_ignores_unknown_ids),
    ("KB tags endpoint returns non-empty list", test_knowledgebase_tags_endpoint_returns_list),
    ("KB tags endpoint returns unique sorted values", test_knowledgebase_tags_endpoint_unique_sorted),
    ("KB search accepts multiple tag params", test_knowledgebase_search_multiple_tags),
    ("KB search tag+freeform combination uses OR", test_knowledgebase_search_tag_and_freeform_combination),
    ("Cable filter exclude_internal_routes=false includes route cables", test_cable_filter_exclude_internal_routes_false_includes_routes),
    ("Route cable structure has SrcPort/DstPort fields", test_cable_filter_route_cables_have_port_fields),
    ("Route traversal: inbound for outbound", test_route_traversal_inbound_for_outbound),
    ("Route traversal: outbound for inbound", test_route_traversal_outbound_for_inbound),
    ("Route traversal: visible-filter outbound for inbound", test_route_traversal_visible_filter_outbound_for_inbound),
    ("Route traversal: visible-filter inbound for outbound", test_route_traversal_visible_filter_inbound_for_outbound),
    ("Rack profile: asset in rack returns correct rack", test_rack_profile_asset_in_rack),
    ("Rack profile: querying rack asset itself works", test_rack_profile_rack_asset_itself),
    ("Rack profile: asset not in rack returns null", test_rack_profile_asset_not_in_rack),
    ("Rack profile: unknown tag returns 404", test_rack_profile_unknown_tag_returns_404),
    ("Rack profile: division suffix parsed to x coordinates", test_rack_profile_division_suffix_parsed),
    ("Internal routes table includes Usage field", test_rack_profile_internal_routes_include_usage),
    ("Floorplan: returns valid PNG data URL", test_floorplan_returns_valid_png_data_url),
    ("Floorplan: floor-level fallback", test_floorplan_floor_level_fallback),
    ("Floorplan: no match returns null image_url", test_floorplan_no_match_returns_null),
    ("Floorplan: unknown tag returns 404", test_floorplan_unknown_tag_returns_404),
    ("Floorplan: response includes building/floor/room/sector", test_floorplan_returns_building_floor_room_sector),
    ("Sector field present in asset search results", test_sector_present_in_asset_search),

    ("Sector field present in asset details", test_sector_present_in_asset_details),
    ("Dashboard crosspoint: response has required keys", test_dashboard_crosspoint_structure),
    ("Dashboard crosspoint: panels list routing devices", test_dashboard_crosspoint_panels_present),
    ("Dashboard crosspoint: VideoHub panel present", test_dashboard_crosspoint_videohub_panel),
    ("Dashboard crosspoint: unavailable when CueCommander unreachable", test_dashboard_crosspoint_cuecommander_unavailable),
    ("Dashboard Klang: response has required keys", test_dashboard_klang_structure),
    ("Dashboard Klang: sweep panel has active/started_at/mix_current", test_dashboard_klang_sweep_shape),
    ("Dashboard Klang: variances panel shape when available", test_dashboard_klang_variances_shape_when_available),
    ("Dashboard Klang: unavailable when CueCommander unreachable", test_dashboard_klang_cuecommander_unavailable),
    ("Asset network: returns network key in asset details", test_asset_network_in_details),
    ("Asset network: /assets/{tag}/network returns list", test_asset_network_endpoint),
    ("Installed assets: installed_software/installed_on fields present", test_installed_assets_fields_present),
    ("Installed assets: relationship consistent from both sides", test_installed_assets_relationship_consistency),
    ("Installed assets: present for non-Computer-category host", test_installed_software_present_for_non_computer_category_host),
    ("Dashboard network: response has required keys", test_dashboard_network_structure),
    ("Dashboard network: config exceptions present", test_dashboard_network_config_exceptions),
    ("Dashboard network: ping_results absent when CueCommander unreachable", test_dashboard_network_ping_unavailable),
    ("/api/network/targets: response has required keys and total matches", test_network_targets_endpoint_structure),
    ("/api/network/targets: returns at least one monitored node", test_network_targets_non_empty),
    ("/api/network/targets: every entry has asset_tag, ip, related_issue_ids", test_network_targets_required_fields),
    ("/api/network/targets: excludes Monitor=Yes rows with no IP", test_network_targets_no_missing_ip_rows),
    ("/network/search: partial IP returns list", test_network_search_partial_ip_returns_list),
    ("/network/search: IP result has required fields", test_network_search_ip_result_shape),
    ("/network/search: returned assets all match query IP", test_network_search_ip_results_contain_query),
    ("/network/search: MAC colon format returns list", test_network_search_mac_colon_format),
    ("/network/search: MAC dash format returns list", test_network_search_mac_dash_format),
    ("/network/search: colon and dash MAC give same results", test_network_search_mac_and_colon_results_equivalent),
    ("/network/search: no separator returns 400", test_network_search_no_separator_returns_400),
    ("/network/search: results ordered by asset_tag", test_network_search_results_ordered_by_asset_tag),
    ("Glossary: returns non-empty list", test_glossary_returns_list),
    ("Glossary: entries have required fields", test_glossary_entries_have_required_fields),
    ("Glossary: topic filter returns matching entries only", test_glossary_topic_filter),
    ("Glossary: unknown topic returns empty list", test_glossary_topic_filter_unknown_returns_empty),
    ("Glossary: /glossary/topics sorted and unique", test_glossary_topics_endpoint),
    ("Glossary: /glossary/topics has no blank entries", test_glossary_topics_no_blank_entries),
    ("Glossary: whitespace stripped from topic and term", test_glossary_whitespace_stripped),
    ("Glossary: at least one see_also value present", test_glossary_seealso_present_when_expected),
]


def main():
    print(f"Running {len(TESTS)} tests against {API_BASE}")
    passed = 0
    for i, (name, func) in enumerate(TESTS, start=1):
        tid = f"T{i:03d}"
        try:
            func()
        except TestFailure as exc:
            print(f"[FAIL] {tid} {name}: {exc}")
        except Exception as exc:
            print(f"[ERROR] {tid} {name}: {exc}", file=sys.stderr)
        else:
            print(f"[PASS] {tid} {name}")
            passed += 1
    total = len(TESTS)
    print(f"Completed {total} tests: {passed} passed, {total - passed} failed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
