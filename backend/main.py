import base64
import datetime
import hashlib
import html  # Import html module
import json as _json
import logging
import os
import re
import urllib.error as _urllib_error
import urllib.request as _urllib_request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

import graphviz  # Import graphviz
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query  # Import Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response  # Import Response for SVG output
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_IMAGES_DIR = Path(os.environ.get("IMAGES_DIR", "/Users/avuser/uactechdoc/images"))
_AVL_DATA_URL = os.environ.get("AVL_DATA_URL", "http://localhost:8002")


def _avl_data_get(path: str):
    """Fetch JSON from the avl_data API. Raises HTTPException on failure."""
    url = f"{_AVL_DATA_URL}{path}"
    try:
        with _urllib_request.urlopen(url, timeout=10) as resp:
            return _json.loads(resp.read().decode())
    except _urllib_error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"avl_data API error: {exc.code} {path}")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"avl_data API unavailable: {exc}")


def clean_dataframe_for_json(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cleans a DataFrame by converting all values to strings or empty strings for JSON serialization.
    Handles NaN, NaT, Inf by converting to empty string "". Datetimes are converted to ISO format.
    """
    df_cleaned = df.copy()

    for col in df_cleaned.columns:
        # Replace all problematic float values (NaN, Inf, -Inf) and pd.NA with empty string ""
        df_cleaned[col] = df_cleaned[col].replace(
            {np.nan: "", np.inf: "", -np.inf: "", pd.NA: ""}
        )

        # Handle explicit datetime objects (pd.NaT should already be converted to "" by replace)
        if pd.api.types.is_datetime64_any_dtype(df_cleaned[col]):
            df_cleaned[col] = df_cleaned[col].apply(
                lambda x: x.isoformat() if x != "" else ""
            )  # Use "" not None here
        else:
            # Convert to string; render whole-number floats as integers ("1.0" -> "1")
            def _to_str(x):
                if x == "":
                    return ""
                try:
                    f = float(x)
                    if f == int(f):
                        return str(int(f))
                except (ValueError, TypeError, OverflowError):
                    pass
                return str(x)

            df_cleaned[col] = df_cleaned[col].apply(_to_str)

    return df_cleaned


# --- Data Loading ---
def normalize_tag_value(value: Optional[str]) -> str:
    """Returns a canonical representation for asset/cable tags."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return ""
    return s.upper()


_ASSETS_DB_TO_EXCEL = {
    "asset_tag": "AssetTag", "category": "Category", "qty": "Qty",
    "unit_value": "UnitValue", "acq_value": "AcqValue", "manufacturer": "Manufacturer",
    "model": "Model", "building": "Building", "floor": "Floor", "room": "Room",
    "sector": "Sector", "location": "Location", "rack": "Rack", "rack_u": "RackU",
    "rack_height": "RackHeight", "asset_type": "Type", "description": "Desc",
    "usage": "Usage", "serial_number": "SN", "in_service": "InService",
    "purc_date": "PurcDate", "purc_from": "PurcFrom", "invoice": "Invoice",
    "comments": "Comments", "acq_year": "AcqYear", "eol_year": "EolYear",
    "disposition": "Disposition", "disposed_year": "DisposedYear",
    "disposed_value": "DisposedValue", "disposed_comment": "DisposedComment",
    "disposition_destination": "DispositionDestination", "last_audit_date": "LastAuditDate",
}

_CABLES_DB_TO_EXCEL = {
    "cable_tag": "Tag", "src_tag": "SrcTag", "src_port": "SrcPort",
    "dst_tag": "DstTag", "dst_port": "DstPort", "cable_type": "Type",
    "protocol": "Protocol", "length": "Length", "labelled": "Labelled?",
    "usage": "Usage", "notes": "Notes", "invoice": "Invoice", "pathway": "Pathway",
}

_NETWORK_DB_TO_EXCEL = {
    "asset_tag": "AssetTag", "nic": "NIC", "ip_address": "IP",
    "mac_address": "MAC", "address_type": "Static-Reserved", "url": "URL",
    "usage": "Usage", "services": "Services", "monitor": "Monitor",
    "related_issue_id": "RelatedIssueId", "notes": "Notes",
}

_KB_DB_TO_EXCEL = {
    "issue_id": "IssueID", "category": "Category", "subcategory": "Subcategory",
    "title": "Title", "symptom": "Symptom", "trigger_conditions": "TriggerConditions",
    "likely_cause": "LikelyCause", "recovery_steps": "RecoverySteps",
    "applies_to_asset_type": "AppliesToAssetType", "applies_to_asset_tag": "AppliesToAssetTag",
    "tags": "Tags", "see_also": "SeeAlso", "sort_order": "SortOrder",
    "active": "Active", "notes": "Notes",
}


def load_assets_data():
    rows = _avl_data_get("/assets?limit=5000")
    if not rows:
        return pd.DataFrame(columns=list(_ASSETS_DB_TO_EXCEL.values()) + ["AssetTagNorm"])
    df = pd.DataFrame(rows).rename(columns=_ASSETS_DB_TO_EXCEL)
    df = df.astype(object)
    df["AssetTag"] = df["AssetTag"].fillna("").astype(str).str.strip()
    df["AssetTagNorm"] = df["AssetTag"].str.upper()
    return df


def load_cables_data():
    rows = _avl_data_get("/cables?limit=5000")
    if not rows:
        return pd.DataFrame(columns=list(_CABLES_DB_TO_EXCEL.values()) + ["TagNorm", "SrcTagNorm", "DstTagNorm"])
    df = pd.DataFrame(rows).rename(columns=_CABLES_DB_TO_EXCEL)
    df = df.astype(object)
    df["Tag"] = df["Tag"].fillna("").astype(str).str.strip()
    df["SrcTag"] = df["SrcTag"].fillna("").astype(str).str.strip()
    df["DstTag"] = df["DstTag"].fillna("").astype(str).str.strip()
    df["TagNorm"] = df["Tag"].str.upper()
    df["SrcTagNorm"] = df["SrcTag"].str.upper()
    df["DstTagNorm"] = df["DstTag"].str.upper()
    return df


def load_network_data() -> pd.DataFrame:
    rows = _avl_data_get("/network?limit=5000")
    if not rows:
        return pd.DataFrame(columns=list(_NETWORK_DB_TO_EXCEL.values()) + ["AssetTagNorm"])
    df = pd.DataFrame(rows).rename(columns=_NETWORK_DB_TO_EXCEL)
    df = df.astype(object)
    df["AssetTag"] = df["AssetTag"].fillna("").astype(str).str.strip()
    df["AssetTagNorm"] = df["AssetTag"].str.upper()
    df["Monitor"] = df["Monitor"].map({True: "Yes", False: "No"}).fillna("")
    df["IP"] = df["IP"].fillna("").astype(str).str.strip()
    df.loc[df["IP"].str.lower().isin(("nan", "none", "tbd", "na")), "IP"] = ""
    df["NIC"] = df["NIC"].fillna("").astype(str).str.strip()
    df.loc[df["NIC"].str.lower().isin(("nan", "none")), "NIC"] = ""
    return df


def _parse_issue_ids(raw) -> List[str]:
    """Parse a RelatedIssueId(s) cell into a clean list of issue ID strings."""
    s = str(raw or "").strip()
    if not s or s.lower() in ("nan", "none", ""):
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def _network_rows_for_tag(df_net: pd.DataFrame, asset_tag: str) -> List[dict]:
    """Return serialisable NIC records for one asset tag."""
    rows = df_net[df_net["AssetTagNorm"] == asset_tag.strip().upper()]
    result = []
    for _, r in rows.iterrows():
        ip = str(r.get("IP", "") or "").strip()
        nic = str(r.get("NIC", "") or "").strip()
        mac = str(r.get("MAC", "") or "").strip()
        url = str(r.get("URL", "") or "").strip()
        mon = str(r.get("Monitor", "") or "").strip()
        usage = str(r.get("Usage", "") or "").strip()
        notes = str(r.get("Notes", "") or "").strip()
        static = str(r.get("Static-Reserved", "") or "").strip()
        services = str(r.get("Services", "") or "").strip()
        _nan = ("nan", "none", "")
        result.append(
            {
                "nic": nic if nic not in _nan else "",
                "mac": mac if mac not in _nan else "",
                "ip": ip if ip not in _nan else "",
                "url": url if url not in _nan else "",
                "monitor": mon == "Yes",
                "static_reserved": static if static not in _nan else "",
                "usage": usage if usage not in _nan else "",
                "notes": notes if notes not in _nan else "",
                "services": services if services not in _nan else "",
            }
        )
    return result


def load_knowledgebase_data():
    rows = _avl_data_get("/knowledgebase?limit=5000")
    if not rows:
        return pd.DataFrame(columns=list(_KB_DB_TO_EXCEL.values()) + ["AppliesToAssetTagNorm"])
    df = pd.DataFrame(rows).rename(columns=_KB_DB_TO_EXCEL)
    df = df.astype(object)
    df["AppliesToAssetTag"] = df["AppliesToAssetTag"].fillna("").astype(str).str.strip()
    df["AppliesToAssetTagNorm"] = df["AppliesToAssetTag"].str.upper()
    df["SeeAlso"] = df["SeeAlso"].fillna("").astype(str).str.strip()
    df["Active"] = df["Active"].map({True: "Yes", False: "No"}).fillna("")
    df = df.dropna(subset=["IssueID"])
    return df


def build_kb_seealso_map(df_kb: pd.DataFrame) -> Dict[str, List[Dict[str, str]]]:
    """
    Build a bidirectional SeeAlso map: issue_id_upper -> sorted list of
    {IssueID, Title} dicts, deduplicated and excluding self-references.
    Only includes references to IDs that actually exist in the dataset.
    """
    id_to_display: Dict[str, str] = {}
    id_to_title: Dict[str, str] = {}
    for _, row in df_kb.iterrows():
        raw_id = str(row["IssueID"]).strip()
        if raw_id:
            key = raw_id.upper()
            id_to_display[key] = raw_id
            id_to_title[key] = str(row.get("Title") or "").strip()

    # Collect explicit forward edges
    edges: List[tuple] = []
    for _, row in df_kb.iterrows():
        src = str(row["IssueID"]).strip().upper()
        for part in str(row.get("SeeAlso") or "").split(","):
            dst = part.strip().upper()
            if dst and dst != src and dst in id_to_display:
                edges.append((src, dst))

    # Build bidirectional adjacency (both directions per edge)
    adj: Dict[str, set] = {k: set() for k in id_to_display}
    for src, dst in edges:
        adj[src].add(dst)
        adj[dst].add(src)

    result: Dict[str, List[Dict[str, str]]] = {}
    for key, neighbors in adj.items():
        result[key] = sorted(
            [{"IssueID": id_to_display[n], "Title": id_to_title[n]} for n in neighbors],
            key=lambda x: x["IssueID"].upper(),
        )
    return result


def build_kb_active_tags(df_kb: pd.DataFrame) -> List[Dict[str, str]]:
    """Return sorted unique keyword tags from the Tags column of active KB rows."""
    if "Active" not in df_kb.columns:
        active_df = df_kb
    else:
        active_df = df_kb[
            df_kb["Active"].fillna("").astype(str).str.strip().str.upper() == "YES"
        ]
    col = "Tags" if "Tags" in df_kb.columns else "AppliesToAssetTag"
    tags: List[str] = []
    for raw in active_df[col].dropna():
        for part in str(raw).split(","):
            t = part.strip().lstrip("#")
            if t:
                tags.append(t)
    seen: set = set()
    unique: List[str] = []
    for t in tags:
        key = t.upper()
        if key not in seen:
            seen.add(key)
            unique.append(t)
    unique.sort(key=lambda x: x.upper())
    return [{"value": t, "label": t} for t in unique]


# Load data globally for the application to avoid reloading on each request
try:
    df_assets = load_assets_data()
except Exception as exc:
    logging.warning("Failed to load assets at startup: %s", exc)
    df_assets = pd.DataFrame(columns=list(_ASSETS_DB_TO_EXCEL.values()) + ["AssetTagNorm"])

try:
    df_cables = load_cables_data()
except Exception as exc:
    logging.warning("Failed to load cables at startup: %s", exc)
    df_cables = pd.DataFrame(columns=list(_CABLES_DB_TO_EXCEL.values()) + ["TagNorm", "SrcTagNorm", "DstTagNorm"])

try:
    df_knowledgebase = load_knowledgebase_data()
except Exception as exc:
    logging.warning("Failed to load knowledgebase at startup: %s", exc)
    df_knowledgebase = pd.DataFrame(columns=list(_KB_DB_TO_EXCEL.values()) + ["AppliesToAssetTagNorm"])
KB_ACTIVE_TAGS: List[Dict[str, str]] = build_kb_active_tags(df_knowledgebase)
KB_SEEALSO_MAP: Dict[str, List[Dict[str, str]]] = build_kb_seealso_map(df_knowledgebase)
ASSET_TAG_LOOKUP: Dict[str, str] = {}
VALID_ASSET_TAGS_NORMALIZED: Set[str] = set()
CABLE_TAG_LOOKUP: Dict[str, str] = {}
CABLE_RECORD_TAG_LOOKUP: Dict[str, str] = {}
ALL_KNOWN_TAGS_NORMALIZED: Set[str] = set()
VALID_CABLE_IDS_NORMALIZED: Set[str] = set()
JUNCTION_NODE_PREFIX = "__cable_junction__::"

ASSET_FIELD_MAP: Dict[str, str] = {}  # canonical -> column name
ASSET_FIELD_LABELS: Dict[str, str] = {}
CABLE_FIELD_MAP: Dict[str, str] = {}
CABLE_FIELD_LABELS: Dict[str, str] = {}
NODE_FIELD_OPTIONS: Set[str] = set()
EDGE_FIELD_OPTIONS: Set[str] = set()
DEFAULT_NODE_FIELDS = ["tag", "manufacturer", "model", "usage"]
DEFAULT_EDGE_FIELDS = ["tag", "type", "ports", "usage"]
DEFAULT_NODE_BACKGROUND = "#D9E8FB"
CROSSPOINT_HEADER_LABELS = {
    "port": "Port",
    "usage": "Usage",
    "protocol": "Protocol",
    "tag": "Cable Tag",
    "type": "Cable Type",
    "notes": "Notes",
}
CROSSPOINT_HEADER_FIELDS = set(CROSSPOINT_HEADER_LABELS.keys())
CROSSPOINT_DEFAULT_FIELDS = ["port", "usage"]
PROTOCOL_COLOR_MAP = {
    "sdi": "#00B050",
    "hdmi": "#ED7D31",
    "ethernet": "#0070C0",
    "hdbaset": "#1F77B4",
    "dante": "#C00000",
    "dmx": "#7030A0",
    "rf": "#996633",
    "gigaace": "#2E75B6",
    "dx-link": "#4BACC6",
    "aa-line": "#70AD47",
    "aa-mic": "#548235",
    "aa-amp": "#92D050",
    "comp-video": "#FFC000",
    "vga": "#FABF8F",
    "viscaip": "#B8359F",
    "unused": "#A6A6A6",
}
CATEGORY_COLOR_MAP = {
    "video": "#BBD7FF",
    "audio": "#F8C471",
    "lighting": "#F7B7D2",
    "network": "#C6E0B4",
    "power": "#FAD7AC",
    "security": "#D5A6BD",
    "hardware": "#E2EFDA",
    "misc": "#E4DFEC",
    "music": "#FFE699",
    "usb": "#FFD966",
}
DEFAULT_PROTOCOL_COLOR = "#6C757D"
DEFAULT_CATEGORY_COLOR = "#DDEBF7"
COLLAPSE_OPTIONS = {"none", "protocol", "type"}
ASSET_TABLE_DEFAULT_COLUMNS = ["AssetTag", "Model", "Manufacturer", "Desc", "Usage"]
ASSET_TABLE_LABEL_OVERRIDES = {
    "AssetTag": "Asset Tag",
    "Desc": "Description",
    "SN": "Serial Number",
}


def rebuild_lookup_sets() -> None:
    """Rebuilds lookup dictionaries for asset and cable tags."""
    global ASSET_TAG_LOOKUP, VALID_ASSET_TAGS_NORMALIZED, CABLE_TAG_LOOKUP
    global \
        CABLE_RECORD_TAG_LOOKUP, \
        ALL_KNOWN_TAGS_NORMALIZED, \
        VALID_CABLE_IDS_NORMALIZED
    ASSET_TAG_LOOKUP = dict(zip(df_assets["AssetTagNorm"], df_assets["AssetTag"]))
    VALID_ASSET_TAGS_NORMALIZED = set(ASSET_TAG_LOOKUP.keys())

    CABLE_RECORD_TAG_LOOKUP = {}
    for tag in df_cables["Tag"].dropna():
        norm = normalize_tag_value(tag)
        if norm and norm not in CABLE_RECORD_TAG_LOOKUP:
            CABLE_RECORD_TAG_LOOKUP[norm] = str(tag).strip()
    VALID_CABLE_IDS_NORMALIZED = set(CABLE_RECORD_TAG_LOOKUP.keys())

    CABLE_TAG_LOOKUP = {}
    for tag in pd.concat(
        [df_cables["Tag"], df_cables["SrcTag"], df_cables["DstTag"]]
    ).dropna():
        norm = normalize_tag_value(tag)
        if norm and norm not in CABLE_TAG_LOOKUP:
            CABLE_TAG_LOOKUP[norm] = str(tag).strip()

    ALL_KNOWN_TAGS_NORMALIZED = VALID_ASSET_TAGS_NORMALIZED.union(
        CABLE_TAG_LOOKUP.keys()
    )


class CableFilterResponse(BaseModel):
    cables: List[Dict[str, str]]
    asset_tags: List[str]
    primary_target: str


def normalize_tag_list(tags_value: Optional[str]) -> List[str]:
    """Splits a comma-separated tag string and normalizes each entry."""
    if not tags_value:
        return []
    if not isinstance(tags_value, str):
        tags_value = str(tags_value)
    normalized = []
    for raw_tag in tags_value.split(","):
        norm = normalize_tag_value(raw_tag)
        if norm:
            normalized.append(norm)
    return normalized


def denormalize_tags(normalized_tags: Set[str]) -> Set[str]:
    """Converts normalized tags back to their display form if possible."""
    display_values: Set[str] = set()
    for tag in normalized_tags:
        if not tag:
            continue
        display_values.add(
            ASSET_TAG_LOOKUP.get(tag) or CABLE_TAG_LOOKUP.get(tag) or tag
        )
    return display_values


def canonical_display_tag(tag_value: Optional[str]) -> str:
    """Returns a consistent, display-friendly representation of a tag value."""
    norm = normalize_tag_value(tag_value)
    if not norm:
        return ""
    return ASSET_TAG_LOOKUP.get(norm) or CABLE_TAG_LOOKUP.get(norm) or norm


def is_cable_record_tag(tag_value: Optional[str]) -> bool:
    return normalize_tag_value(tag_value) in VALID_CABLE_IDS_NORMALIZED


def is_asset_tag(tag_value: Optional[str]) -> bool:
    return normalize_tag_value(tag_value) in VALID_ASSET_TAGS_NORMALIZED


def build_junction_node_id(
    current_cable_tag: Optional[str], referenced_cable_tag: Optional[str]
) -> str:
    pair = sorted(
        [
            normalize_tag_value(current_cable_tag),
            normalize_tag_value(referenced_cable_tag),
        ]
    )
    return JUNCTION_NODE_PREFIX + "::".join([part for part in pair if part])


def is_junction_node_id(node_id: str) -> bool:
    return str(node_id).startswith(JUNCTION_NODE_PREFIX)


def resolve_query_target(
    target_tag: Optional[str], cable_id: Optional[str]
) -> Tuple[str, str]:
    target_norm = normalize_tag_value(target_tag)
    cable_norm = normalize_tag_value(cable_id)

    if target_norm and target_norm in ALL_KNOWN_TAGS_NORMALIZED:
        return target_norm, canonical_display_tag(target_norm)
    if target_norm and target_norm in VALID_CABLE_IDS_NORMALIZED:
        return target_norm, canonical_display_tag(target_norm)
    if cable_norm and cable_norm in VALID_CABLE_IDS_NORMALIZED:
        return cable_norm, canonical_display_tag(cable_norm)

    if target_norm or cable_norm:
        unresolved = target_norm or cable_norm
        raise HTTPException(
            status_code=404, detail=f"Unknown asset tag or cable ID: {unresolved}"
        )

    raise HTTPException(
        status_code=400, detail="Target asset tag or cable ID is required."
    )


def rows_for_expansion_target(node_norm: str, directions: Set[str]) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    if is_cable_record_tag(node_norm):
        frames.append(df_cables[df_cables["TagNorm"] == node_norm])
    if "in" in directions:
        frames.append(df_cables[df_cables["DstTagNorm"] == node_norm])
    if "out" in directions:
        frames.append(df_cables[df_cables["SrcTagNorm"] == node_norm])
    if not frames:
        return df_cables.iloc[0:0].copy()
    return pd.concat(frames).drop_duplicates()


def expand_cable_reference_closure(seed_rows: pd.DataFrame) -> pd.DataFrame:
    if seed_rows.empty:
        return seed_rows.copy()

    expanded = seed_rows.copy()
    processed_refs: Set[str] = set()

    while True:
        endpoint_refs = (
            set(expanded["SrcTagNorm"].dropna().tolist())
            | set(expanded["DstTagNorm"].dropna().tolist())
        ) & VALID_CABLE_IDS_NORMALIZED
        pending_refs = endpoint_refs - processed_refs
        if not pending_refs:
            break
        processed_refs.update(pending_refs)
        new_rows = df_cables[df_cables["TagNorm"].isin(pending_refs)]
        if new_rows.empty:
            continue
        expanded = pd.concat([expanded, new_rows]).drop_duplicates()

    return expanded


def build_candidate_cables(expansion_map: Dict[str, Set[str]]) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for node_norm, dirs in expansion_map.items():
        subset = rows_for_expansion_target(node_norm, dirs)
        if not subset.empty:
            frames.append(subset)
    if not frames:
        return df_cables.iloc[0:0].copy()
    return expand_cable_reference_closure(pd.concat(frames).drop_duplicates())


def reload_dataframes() -> None:
    """Reloads the global asset and cable DataFrames and associated lookup sets."""
    global \
        df_assets, \
        df_cables, \
        df_knowledgebase, \
        KB_ACTIVE_TAGS, \
        KB_SEEALSO_MAP, \
        ASSET_TAG_LOOKUP, \
        VALID_ASSET_TAGS_NORMALIZED
    df_assets = load_assets_data()
    df_cables = load_cables_data()
    df_knowledgebase = load_knowledgebase_data()
    KB_ACTIVE_TAGS = build_kb_active_tags(df_knowledgebase)
    KB_SEEALSO_MAP = build_kb_seealso_map(df_knowledgebase)
    rebuild_lookup_sets()
    rebuild_field_option_maps()


def canonicalize_field_key(label: str) -> str:
    if not label:
        return ""
    sanitized = re.sub(r"[^0-9a-zA-Z]+", "_", str(label)).strip("_")
    return sanitized.lower()


def prettify_field_label(label: str) -> str:
    if not label:
        return ""
    original = str(label).strip()
    spaced = re.sub(r"(_)|(?<=[a-z0-9])(?=[A-Z])", " ", original)
    cleaned = re.sub(r"\s+", " ", spaced).strip()
    return cleaned


def rebuild_field_option_maps() -> None:
    """Builds lookup maps for node/edge field selections."""
    global ASSET_FIELD_MAP, ASSET_FIELD_LABELS, CABLE_FIELD_MAP, CABLE_FIELD_LABELS
    global NODE_FIELD_OPTIONS, EDGE_FIELD_OPTIONS

    ASSET_FIELD_MAP = {}
    ASSET_FIELD_LABELS = {"tag": "Tag"}
    excluded_asset_columns = {"AssetTagNorm"}
    for column in df_assets.columns:
        if column in excluded_asset_columns:
            continue
        canonical = canonicalize_field_key(column)
        if not canonical or canonical == "tag":
            continue
        ASSET_FIELD_MAP[canonical] = column
        ASSET_FIELD_LABELS[canonical] = prettify_field_label(column)

    CABLE_FIELD_MAP = {}
    CABLE_FIELD_LABELS = {
        "tag": "Tag",
        "ports": "In-Port → Out-Port",
    }
    excluded_cable_columns = {"TagNorm", "SrcTagNorm", "DstTagNorm"}
    for column in df_cables.columns:
        if column in excluded_cable_columns:
            continue
        canonical = canonicalize_field_key(column)
        if not canonical or canonical in {"tag", "ports"}:
            continue
        CABLE_FIELD_MAP[canonical] = column
        CABLE_FIELD_LABELS[canonical] = prettify_field_label(column)

    # Virtual computed field: Building / Floor / Room / Sector concatenation
    ASSET_FIELD_LABELS["bfrs"] = "BFRS"

    NODE_FIELD_OPTIONS = set(ASSET_FIELD_LABELS.keys())
    EDGE_FIELD_OPTIONS = set(CABLE_FIELD_LABELS.keys())


rebuild_lookup_sets()
rebuild_field_option_maps()


@app.get("/assets/columns")
async def get_asset_columns():
    """Returns metadata for asset table column selection."""
    options = []
    for column in df_assets.columns:
        label = ASSET_TABLE_LABEL_OVERRIDES.get(column, prettify_field_label(column))
        options.append(
            {
                "value": column,
                "label": label,
            }
        )
    defaults: List[str] = []
    for default in ASSET_TABLE_DEFAULT_COLUMNS:
        if default in df_assets.columns:
            defaults.append(default)
        elif default.lower() == "make" and "Model" in df_assets.columns:
            defaults.append("Model")
    if not defaults:
        defaults = ["AssetTag"]
    return {"columns": options, "defaults": defaults}


def _natural_key(s: str) -> List:
    """Sort key that orders embedded integers numerically: '2' < '12' < '23'."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", str(s))]


def clamp(value: float, min_value: float = 0.0, max_value: float = 255.0) -> int:
    return int(max(min_value, min(max_value, value)))


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    value = hex_color.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return (221, 235, 247)
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % tuple(clamp(channel) for channel in rgb)


def lighten_color(hex_color: str, factor: float = 0.65) -> str:
    r, g, b = hex_to_rgb(hex_color)
    r = r + (255 - r) * factor
    g = g + (255 - g) * factor
    b = b + (255 - b) * factor
    return rgb_to_hex((r, g, b))


def hash_color_from_text(value: str, pastel: bool = False) -> str:
    if not value:
        return DEFAULT_CATEGORY_COLOR if pastel else DEFAULT_PROTOCOL_COLOR
    digest = hashlib.md5(value.encode("utf-8")).hexdigest()
    # Use first 6 hex chars
    base_color = f"#{digest[:6]}"
    return lighten_color(base_color, 0.7) if pastel else base_color


def get_protocol_color(protocol_value: Optional[str]) -> str:
    if not protocol_value:
        return DEFAULT_PROTOCOL_COLOR
    key = str(protocol_value).strip().lower()
    if not key:
        return DEFAULT_PROTOCOL_COLOR
    return PROTOCOL_COLOR_MAP.get(key) or hash_color_from_text(key, pastel=False)


def get_category_color(category_value: Optional[str]) -> str:
    if not category_value:
        return DEFAULT_CATEGORY_COLOR
    key = str(category_value).strip().lower()
    if not key:
        return DEFAULT_CATEGORY_COLOR
    return lighten_color(
        CATEGORY_COLOR_MAP.get(key) or hash_color_from_text(key, pastel=True), 0.35
    )


def format_display_value(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    # Render whole-number floats as integers (e.g. "1.0" -> "1")
    if "." in text:
        try:
            f = float(text)
            if f == int(f):
                return str(int(f))
        except (ValueError, OverflowError):
            pass
    return text


def normalize_port_value(value: object) -> str:
    text = format_display_value(value)
    return text


def collect_unique_texts(series: pd.Series) -> List[str]:
    uniques: List[str] = []
    seen = set()
    for raw in series.dropna():
        text = format_display_value(raw)
        if text and text not in seen:
            seen.add(text)
            uniques.append(text)
    return uniques


def build_crosspoint_label(
    port_value: str, subset: pd.DataFrame, fields: List[str]
) -> str:
    label_parts: List[str] = []
    for field_key in fields:
        text = ""
        if field_key == "port":
            text = format_display_value(port_value) or "(No Port)"
        elif field_key == "usage":
            text = ", ".join(collect_unique_texts(subset["Usage"]))
        elif field_key == "protocol":
            text = ", ".join(collect_unique_texts(subset["Protocol"]))
        elif field_key == "tag":
            text = ", ".join(collect_unique_texts(subset["Tag"]))
        elif field_key == "type":
            text = ", ".join(collect_unique_texts(subset["Type"]))
        elif field_key == "notes" and "Notes" in subset.columns:
            text = ", ".join(collect_unique_texts(subset["Notes"]))
        text = text.strip()
        if text:
            label_parts.append(text)
    if not label_parts:
        if format_display_value(port_value):
            label_parts.append(format_display_value(port_value))
        else:
            label_parts.append("(No Port)")
    return " | ".join(label_parts)


def parse_expansion_param(
    expansions: Optional[str],
    default_direction: str,
    target_norm: str,
) -> Dict[str, Set[str]]:
    """
    Parses the expansions query parameter into a mapping of node -> direction set.
    Always ensures the target node has at least the default direction applied.
    """
    direction_map: Dict[str, Set[str]] = {}

    def direction_to_set(direction_value: str) -> Set[str]:
        if direction_value == "in":
            return {"in"}
        if direction_value == "out":
            return {"out"}
        return {"in", "out"}

    direction_map[target_norm] = direction_to_set(default_direction)

    if not expansions:
        return direction_map

    parts = [chunk.strip() for chunk in expansions.split(";") if chunk.strip()]
    for part in parts:
        if ":" in part:
            tag_part, dir_part = part.split(":", 1)
        else:
            tag_part, dir_part = part, "both"

        norm_tag = normalize_tag_value(tag_part)
        if not norm_tag:
            continue
        direction_set = direction_to_set(dir_part.strip().lower())
        if norm_tag not in direction_map:
            direction_map[norm_tag] = set()
        direction_map[norm_tag].update(direction_set)

    return direction_map


def parse_field_selection(
    value: Optional[str], allowed: Set[str], default: List[str]
) -> List[str]:
    if not value:
        return list(default)
    if not isinstance(value, str):
        value = str(value)
    selections = [item.strip().lower() for item in value.split(",") if item.strip()]
    cleaned = [item for item in selections if item in allowed]
    return cleaned or list(default)


def normalize_asset_field_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and np.isnan(value):
        return ""
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return text if text.lower() != "nan" else ""


def get_asset_field_value(
    asset_record: Dict[str, object], field_key: str, fallback_tag: str
) -> str:
    if field_key == "tag":
        return fallback_tag
    if field_key == "bfrs":
        parts = []
        for col in ("Building", "Floor", "Room", "Sector"):
            v = normalize_asset_field_value(asset_record.get(col, "") if asset_record else "")
            if v:
                parts.append(v)
        return "/".join(parts)
    column = ASSET_FIELD_MAP.get(field_key)
    if not column:
        return ""
    if not asset_record:
        return ""
    raw_value = asset_record.get(column, "")
    return normalize_asset_field_value(raw_value)


def get_edge_field_value(row: pd.Series, field_key: str) -> str:
    if field_key == "tag":
        raw = row.get("Tag", "")
        return html.escape(normalize_asset_field_value(raw)) if raw else ""
    if field_key == "ports":
        src_port = normalize_asset_field_value(row.get("SrcPort", ""))
        dst_port = normalize_asset_field_value(row.get("DstPort", ""))
        if src_port and dst_port:
            return f"{html.escape(src_port)} → {html.escape(dst_port)}"
        if src_port:
            return html.escape(src_port)
        if dst_port:
            return html.escape(dst_port)
        return ""
    column = CABLE_FIELD_MAP.get(field_key)
    if not column:
        return ""
    raw = row.get(column, "")
    value = normalize_asset_field_value(raw)
    return html.escape(value) if value else ""


def build_field_option_payload(
    labels: Dict[str, str], defaults: List[str]
) -> Dict[str, object]:
    default_values = [field for field in defaults if field in labels]
    remaining = sorted(
        [field for field in labels.keys() if field not in default_values],
        key=lambda key: labels[key].lower(),
    )
    ordered = default_values + remaining
    return {
        "defaults": default_values,
        "options": [
            {
                "value": field,
                "label": labels[field],
                "selected": field in default_values,
            }
            for field in ordered
        ],
    }


def collapse_label_for_row(row: pd.Series, strategy: str) -> str:
    raw_value = ""
    if strategy == "protocol":
        raw_value = row.get("Protocol", "")
    elif strategy == "type":
        raw_value = row.get("Type", "")
    label = format_display_value(raw_value)
    return label or "Unknown"


def sanitize_port_identifier(label: str, direction: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "_", label.strip().lower())
    if not base:
        base = "unknown"
    return f"{direction}_{base}"


@app.get("/")
async def read_root():
    return {"message": "Welcome to the UAC Tech Documentation API"}


@app.get("/health")
async def health():
    checks = {"status": "ok", "checks": {}}
    try:
        load_assets_data()
        checks["checks"]["assets_data"] = "ok"
    except Exception as e:
        checks["checks"]["assets_data"] = f"error: {e}"
        checks["status"] = "degraded"
    return checks


_reload_history: list = []
_MAX_RELOAD_HISTORY = 50


@app.post("/data/reload")
async def reload_data():
    """Forces the backend to reload asset, cable, and knowledgebase data from avl_data."""
    try:
        reload_dataframes()
        df_net_reload = load_network_data()
        _push_network_targets_to_cuecommander(_build_network_targets(df_net_reload))
        entry = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "status": "ok",
            "assets": len(df_assets),
            "cables": len(df_cables),
            "network": len(df_net_reload),
            "issues": len(df_knowledgebase),
        }
        _reload_history.append(entry)
        if len(_reload_history) > _MAX_RELOAD_HISTORY:
            _reload_history.pop(0)
        return entry
    except Exception as exc:
        entry = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "status": "error",
            "error": str(exc),
        }
        _reload_history.append(entry)
        if len(_reload_history) > _MAX_RELOAD_HISTORY:
            _reload_history.pop(0)
        raise HTTPException(status_code=500, detail=f"Failed to reload data: {exc}")


@app.get("/data/reload-history")
async def get_reload_history():
    """Returns the history of data reload events (most recent last)."""
    return list(reversed(_reload_history))


@app.get("/signal-path")
async def find_signal_path(source: str, target: str, max_hops: int = 10):
    """BFS to find the shortest cable path between two asset tags."""
    src_norm = normalize_tag_value(source)
    dst_norm = normalize_tag_value(target)

    if src_norm not in VALID_ASSET_TAGS_NORMALIZED:
        raise HTTPException(status_code=404, detail=f"Source asset not found: {source}")
    if dst_norm not in VALID_ASSET_TAGS_NORMALIZED:
        raise HTTPException(status_code=404, detail=f"Target asset not found: {target}")
    if src_norm == dst_norm:
        raise HTTPException(
            status_code=400, detail="Source and target must be different assets."
        )

    # Build adjacency: asset_tag_norm -> list of (neighbor_norm, cable_row_dict)
    # Each cable row connects SrcTagNorm -> DstTagNorm
    direct = df_cables[
        df_cables["SrcTagNorm"].notna() & df_cables["DstTagNorm"].notna()
    ].copy()
    # Skip internal route cables (SrcTag == DstTag)
    direct = direct[direct["SrcTagNorm"] != direct["DstTagNorm"]]

    def _display(tag: str) -> str:
        rows = df_assets[df_assets["AssetTagNorm"] == normalize_tag_value(tag)]
        if rows.empty:
            return tag
        return format_display_value(rows.iloc[0]["AssetTag"])

    # BFS
    from collections import deque

    queue: deque = deque()
    queue.append((src_norm, []))  # (current_node_norm, path_of_cable_dicts)
    visited: Set[str] = {src_norm}

    while queue:
        current, path = queue.popleft()
        if len(path) >= max_hops:
            continue
        outbound = direct[direct["SrcTagNorm"] == current]
        for _, row in outbound.iterrows():
            neighbor = row["DstTagNorm"]
            if not neighbor:
                continue
            cable_entry = {
                "from": _display(row["SrcTag"]),
                "to": _display(row["DstTag"]),
                "cable_tag": format_display_value(row.get("Tag", "")),
                "type": format_display_value(row.get("Type", "")),
                "protocol": format_display_value(row.get("Protocol", "")),
                "src_port": format_display_value(row.get("SrcPort", "")),
                "dst_port": format_display_value(row.get("DstPort", "")),
            }
            new_path = path + [cable_entry]
            if neighbor == dst_norm:
                return {
                    "found": True,
                    "source": _display(source),
                    "target": _display(target),
                    "hops": len(new_path),
                    "path": new_path,
                }
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, new_path))

    return {
        "found": False,
        "source": _display(source),
        "target": _display(target),
        "hops": None,
        "path": [],
        "message": f"No signal path found within {max_hops} hops.",
    }


@app.get("/diagram/options")
async def get_diagram_field_options():
    """Exposes available node/edge fields for the frontend multi-select controls."""
    return {
        "node": build_field_option_payload(ASSET_FIELD_LABELS, DEFAULT_NODE_FIELDS),
        "edge": build_field_option_payload(CABLE_FIELD_LABELS, DEFAULT_EDGE_FIELDS),
        "crosspoint": build_field_option_payload(
            CROSSPOINT_HEADER_LABELS, CROSSPOINT_DEFAULT_FIELDS
        ),
    }


def _format_external_connection_rows(
    cables_df: pd.DataFrame,
    partner_tag_col: str,
    target_port_col: str,
    partner_port_col: str,
    is_input: bool,
) -> List[Dict[str, Any]]:
    """Build external-connection rows (inputs or outputs) from a filtered cable DataFrame."""
    if cables_df.empty:
        return []

    partner_assets_tags_norm = cables_df[partner_tag_col][
        ~cables_df[partner_tag_col].apply(is_cable_record_tag)
    ].unique()

    partner_assets_details = df_assets[
        df_assets["AssetTagNorm"].isin(partner_assets_tags_norm)
    ].set_index("AssetTagNorm")

    results = []
    for _, cable_row in cables_df.iterrows():
        partner_norm = cable_row[partner_tag_col]
        if is_cable_record_tag(partner_norm):
            partner_details: Dict[str, Any] = {
                "Manufacturer": "N/A",
                "Model": "Cable Junction",
                "Usage": "Internal Cable Splice",
            }
            partner_display_tag = f"JUNCTION_{canonical_display_tag(cable_row['Tag'])}"
        else:
            partner_details = (
                partner_assets_details.loc[partner_norm].to_dict()
                if partner_norm in partner_assets_details.index
                else {}
            )
            partner_display_tag = canonical_display_tag(partner_norm)

        result_row = {
            "TargetPort": format_display_value(cable_row[target_port_col]),
            ("SourcePort" if is_input else "DestinationPort"): format_display_value(
                cable_row[partner_port_col]
            ),
            "Protocol": format_display_value(cable_row["Protocol"]),
            "CableID": canonical_display_tag(cable_row["Tag"]),
            "PartnerAssetTag": partner_display_tag,
            "PartnerManufacturer": format_display_value(
                partner_details.get("Manufacturer")
            ),
            "PartnerModel": format_display_value(partner_details.get("Model")),
            "PartnerUsage": format_display_value(partner_details.get("Usage")),
        }
        results.append(result_row)

    if results:
        df = pd.DataFrame(results)
        df = clean_dataframe_for_json(df)
        return df.to_dict(orient="records")
    return []


def _build_diagram_connections_payload(target_norm: str) -> Dict[str, Any]:
    """Return inputs, outputs, and internal_routes for a target asset tag (normalized)."""
    all_cables = df_cables[
        (df_cables["SrcTagNorm"] == target_norm)
        | (df_cables["DstTagNorm"] == target_norm)
    ].copy()

    if all_cables.empty:
        return {"inputs": [], "outputs": [], "internal_routes": []}

    # Internal routes: SrcTag == DstTag == this node and Type contains "route"
    route_mask = (
        (all_cables["SrcTagNorm"] == target_norm)
        & (all_cables["DstTagNorm"] == target_norm)
        & all_cables["Type"].str.contains("route", case=False, na=False)
    )
    internal_routes_df = all_cables[route_mask]

    # Passthroughs: SrcTag == DstTag == this node and Type contains "passthrough"
    passthrough_mask = (
        (all_cables["SrcTagNorm"] == target_norm)
        & (all_cables["DstTagNorm"] == target_norm)
        & all_cables["Type"].str.contains("passthrough", case=False, na=False)
    )
    passthroughs_df = all_cables[passthrough_mask]

    # Inputs: cables arriving at this node, excluding internal routes and passthroughs
    inputs_df = all_cables[
        (all_cables["DstTagNorm"] == target_norm) & ~route_mask & ~passthrough_mask
    ].copy()

    # Outputs: cables leaving this node, excluding internal routes and passthroughs
    outputs_df = all_cables[
        (all_cables["SrcTagNorm"] == target_norm) & ~route_mask & ~passthrough_mask
    ].copy()

    # Format internal route rows
    route_rows = []
    for _, row in internal_routes_df.iterrows():
        route_rows.append(
            {
                "SourcePort": format_display_value(row["SrcPort"]),
                "DestinationPort": format_display_value(row["DstPort"]),
                "Protocol": format_display_value(row["Protocol"]),
                "Usage": format_display_value(row.get("Usage", "")),
                "CableID": canonical_display_tag(row["Tag"]),
                "Type": format_display_value(row["Type"]),
            }
        )
    if route_rows:
        route_df = pd.DataFrame(route_rows)
        route_df = clean_dataframe_for_json(route_df)
        route_rows = route_df.to_dict(orient="records")

    # Format passthrough rows (same shape as internal routes)
    passthrough_rows = []
    for _, row in passthroughs_df.iterrows():
        passthrough_rows.append(
            {
                "SourcePort": format_display_value(row["SrcPort"]),
                "DestinationPort": format_display_value(row["DstPort"]),
                "Protocol": format_display_value(row["Protocol"]),
                "Usage": format_display_value(row.get("Usage", "")),
                "CableID": canonical_display_tag(row["Tag"]),
                "Type": format_display_value(row["Type"]),
            }
        )
    if passthrough_rows:
        pt_df = pd.DataFrame(passthrough_rows)
        pt_df = clean_dataframe_for_json(pt_df)
        passthrough_rows = pt_df.to_dict(orient="records")

    return {
        "inputs": _format_external_connection_rows(
            inputs_df, "SrcTagNorm", "DstPort", "SrcPort", is_input=True
        ),
        "outputs": _format_external_connection_rows(
            outputs_df, "DstTagNorm", "SrcPort", "DstPort", is_input=False
        ),
        "internal_routes": route_rows,
        "passthroughs": passthrough_rows,
    }


def _get_partner_details_for_asset(
    target_norm: str, is_input: bool
) -> List[Dict[str, str]]:
    partners: List[Dict[str, str]] = []

    if is_input:
        filtered_cables = df_cables[df_cables["DstTagNorm"] == target_norm]
        partner_tag_col = "SrcTagNorm"
    else:
        filtered_cables = df_cables[df_cables["SrcTagNorm"] == target_norm]
        partner_tag_col = "DstTagNorm"

    # Only consider unique actual asset partners, not cable junctions themselves
    unique_partner_tags = filtered_cables[partner_tag_col][
        ~filtered_cables[partner_tag_col].apply(is_cable_record_tag)
    ].unique()

    for partner_norm in unique_partner_tags:
        partner_asset = df_assets[df_assets["AssetTagNorm"] == partner_norm]
        if not partner_asset.empty:
            record = partner_asset.iloc[0]
            partners.append(
                {
                    "AssetTag": canonical_display_tag(record["AssetTagNorm"]),
                    "Manufacturer": format_display_value(record.get("Manufacturer")),
                    "Model": format_display_value(record.get("Model")),
                    "Usage": format_display_value(record.get("Usage")),
                }
            )
        else:
            # If partner_norm is a valid asset but not in df_assets (e.g. data issue),
            # or it's an unrecognized tag, still list it.
            partners.append(
                {
                    "AssetTag": canonical_display_tag(partner_norm),
                    "Manufacturer": "Unknown",
                    "Model": "Unknown",
                    "Usage": "Unknown",
                }
            )

    return sorted(partners, key=lambda x: x["AssetTag"].lower())


@app.get("/diagram/connections")
async def get_diagram_connections(target_tag: str) -> Dict[str, Any]:
    """
    Returns input connections, output connections, and internal route details for a
    given target asset tag as a single combined payload.  Internal route cables
    (SrcTag == DstTag == target and Type contains 'route') are excluded from both
    the inputs and outputs lists and appear only in internal_routes.
    """
    target_norm = normalize_tag_value(target_tag)
    if not target_norm or target_norm not in VALID_ASSET_TAGS_NORMALIZED:
        raise HTTPException(
            status_code=404, detail=f"Target asset tag not found: {target_tag}"
        )

    return _build_diagram_connections_payload(target_norm)


@app.get("/assets/{asset_tag}/details")
async def get_asset_details(asset_tag: str):
    """
    Returns comprehensive details for a given asset tag, including its properties,
    input/output partners, and relevant knowledge base issues.
    """
    target_norm = normalize_tag_value(asset_tag)
    if not target_norm or target_norm not in VALID_ASSET_TAGS_NORMALIZED:
        raise HTTPException(status_code=404, detail=f"Asset tag not found: {asset_tag}")

    # 1. Get asset properties
    asset_record_df = df_assets[df_assets["AssetTagNorm"] == target_norm]
    if asset_record_df.empty:
        raise HTTPException(status_code=404, detail=f"Asset tag not found: {asset_tag}")

    # Exclude AssetTagNorm which is an internal field
    asset_properties = clean_dataframe_for_json(
        asset_record_df.drop(columns=["AssetTagNorm"]).iloc[0:1]
    ).to_dict(orient="records")[0]

    # 2. Get input partners
    input_partners = _get_partner_details_for_asset(target_norm, is_input=True)

    # 3. Get output partners
    output_partners = _get_partner_details_for_asset(target_norm, is_input=False)

    # 4. Get relevant knowledge base issues
    # Filter for issues where the asset_tag (normalized) is present in the AppliesToAssetTagNorm column
    relevant_issues_df = df_knowledgebase[
        df_knowledgebase["AppliesToAssetTagNorm"].apply(
            lambda x: (
                target_norm in [tag.strip() for tag in x.split(",")]
                if pd.notna(x)
                else False
            )
        )
    ].copy()
    # We only care about IssueID, Title, Category, Subcategory for display
    issue_display_columns = ["IssueID", "Title", "Category", "Subcategory"]
    relevant_issues = clean_dataframe_for_json(
        relevant_issues_df[issue_display_columns]
    ).to_dict(orient="records")

    df_net = load_network_data()
    network_nics = _network_rows_for_tag(df_net, asset_tag)

    # 5. Get licenses for this asset (from avl_data API); strip details if confidential
    licenses_for_asset: list = []
    try:
        raw_licenses = _avl_data_get(f"/licenses?asset_tag={asset_tag}")
        for lic in raw_licenses:
            entry = {
                "id":            lic.get("id"),
                "name":          lic.get("name"),
                "acquired_by":   lic.get("acquired_by"),
                "acquired_date": lic.get("acquired_date"),
                "terms":         lic.get("terms"),
                "expiry_terms":  lic.get("expiry_terms"),
                "expiry_date":   lic.get("expiry_date"),
                "confidential":  lic.get("confidential", False),
            }
            # Only include sensitive details when not flagged confidential
            if not lic.get("confidential", False):
                entry["license_details"] = lic.get("license_details")
            licenses_for_asset.append(entry)
    except HTTPException:
        pass  # avl_data unavailable or returned an error — degrade gracefully

    return {
        "asset": asset_properties,
        "input_partners": input_partners,
        "output_partners": output_partners,
        "knowledge_base_issues": relevant_issues,
        "network": network_nics,
        "licenses": licenses_for_asset,
    }


@app.get("/assets/{asset_tag}/network")
def get_asset_network(asset_tag: str):
    """Returns NIC records for the given asset tag as a flat list."""
    target_norm = normalize_tag_value(asset_tag)
    if not target_norm or target_norm not in VALID_ASSET_TAGS_NORMALIZED:
        raise HTTPException(status_code=404, detail=f"Asset tag not found: {asset_tag}")
    df_net = load_network_data()
    nics = _network_rows_for_tag(df_net, asset_tag)
    display_tag = canonical_display_tag(target_norm)
    return [{"asset_tag": display_tag, **n} for n in nics]


@app.get("/network/search")
def network_search(q: str = Query(..., min_length=1)):
    """
    Search network records by partial IP address or MAC address.

    Detection rules applied to q:
      - Contains '.':        partial IP substring match against the IP column.
      - Contains ':' or '-': MAC address match; both separator styles are
                             normalised to ':' before comparing so the database
                             column format does not matter.

    Returns a list of matching assets ordered by asset tag.  Each item contains
    the asset tag, manufacturer, model, all MAC and IP addresses for that asset,
    and full NIC detail records.
    """
    q = q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="q must not be empty")

    df_net    = load_network_data()
    df_assets = load_assets_data()

    is_ip  = "." in q
    is_mac = ":" in q or "-" in q

    if is_ip:
        mask = df_net["IP"].str.contains(re.escape(q), case=False, na=False)
    elif is_mac:
        q_norm   = q.lower().replace("-", ":")
        mac_norm = df_net["MAC"].str.lower().str.replace("-", ":", regex=False)
        mask     = mac_norm.str.contains(re.escape(q_norm), case=False, na=False)
    else:
        raise HTTPException(
            status_code=400,
            detail="q must contain '.' for an IP address or ':'/'-' for a MAC address",
        )

    matched_tags = df_net.loc[mask, "AssetTagNorm"].unique()
    if len(matched_tags) == 0:
        return []

    tag_display: Dict[str, str] = dict(zip(df_net["AssetTagNorm"], df_net["AssetTag"]))

    def _clean_series(series) -> List[str]:
        seen: Dict[str, None] = {}
        for v in series:
            s = str(v).strip()
            if s and s.lower() not in ("nan", "none", ""):
                seen[s] = None
        return list(seen)

    results = []
    for tag_norm in sorted(matched_tags):
        display_tag  = tag_display.get(tag_norm, tag_norm)
        asset_rows   = df_assets[df_assets["AssetTagNorm"] == tag_norm]
        manufacturer = model = ""
        if not asset_rows.empty:
            r            = asset_rows.iloc[0]
            manufacturer = str(r.get("Manufacturer", "") or "").strip()
            model        = str(r.get("Model",        "") or "").strip()
            if manufacturer.lower() in ("nan", "none", ""): manufacturer = ""
            if model.lower()        in ("nan", "none", ""): model        = ""
        all_rows = df_net[df_net["AssetTagNorm"] == tag_norm]
        results.append({
            "asset_tag":     display_tag,
            "manufacturer":  manufacturer,
            "model":         model,
            "mac_addresses": _clean_series(all_rows["MAC"]),
            "ip_addresses":  _clean_series(all_rows["IP"]),
            "nics":          _network_rows_for_tag(df_net, display_tag),
        })

    return results


def _parse_racku(racku_str: str):
    """Parse a RackU value like 'F23', 'R10', 'F23-3-2-2' into structured fields."""
    s = str(racku_str).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return None
    face_char = s[0].upper()
    face = "Front" if face_char == "F" else ("Rear" if face_char == "R" else "Unknown")
    m = re.search(r"(\d+)", s)
    if not m:
        return None
    u_start = int(m.group(1))
    # Parse optional suffix -divisions-div_start-div_end
    suffix_m = re.search(r"-(\d+)-(\d+)-(\d+)$", s)
    if suffix_m:
        num_div = int(suffix_m.group(1))
        div_start = int(suffix_m.group(2))
        div_end = int(suffix_m.group(3))
    else:
        num_div, div_start, div_end = 1, 1, 1
    x_start = (div_start - 1) / num_div
    x_end = div_end / num_div
    return {"face": face, "u_start": u_start, "x_start": x_start, "x_end": x_end}


def _floorplan_candidates(building: str, floor: str, room: str) -> list:
    """Return candidate filenames ordered most-specific to least-specific."""
    b = building.strip().lower()
    f = floor.strip().lower()
    r = room.strip().lower()
    candidates = []
    if b and f and r:
        candidates.append(f"floorplan_{b}_{f}_r{r}.png")
    if b and f:
        candidates.append(f"floorplan_{b}_{f}.png")
    if b:
        candidates.append(f"floorplan_{b}.png")
    return candidates


@app.get("/location/floorplan")
async def get_location_floorplan(asset_tag: str):
    """Return location info and the best available floorplan image as a base64 data URL."""
    tag_norm = normalize_tag_value(asset_tag)
    if tag_norm not in VALID_ASSET_TAGS_NORMALIZED:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_tag}")

    rows = df_assets[df_assets["AssetTagNorm"] == tag_norm]
    if rows.empty:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_tag}")

    row = rows.iloc[0]
    building = str(row.get("Building", "") or "").strip()
    floor = str(row.get("Floor", "") or "").strip()
    room = str(row.get("Room", "") or "").strip()
    sector_raw = row.get("Sector", "")
    try:
        sector = (
            str(int(float(sector_raw)))
            if sector_raw not in ("", None)
            and str(sector_raw).strip().lower() not in ("nan", "")
            else ""
        )
    except (ValueError, TypeError):
        sector = str(sector_raw).strip()

    _PNG_SIG = b"\x89PNG\r\n\x1a\n"
    for filename in _floorplan_candidates(building, floor, room):
        image_path = _IMAGES_DIR / filename
        if not image_path.is_file():
            continue
        image_bytes = image_path.read_bytes()
        if not image_bytes.startswith(_PNG_SIG):
            continue  # skip files that are not valid PNGs (e.g. mis-named PSDs)
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode(
            "ascii"
        )
        return {
            "image_data_url": data_url,
            "filename": filename,
            "building": building,
            "floor": floor,
            "room": room,
            "sector": sector,
        }

    return {
        "image_data_url": None,
        "filename": None,
        "building": building,
        "floor": floor,
        "room": room,
        "sector": sector,
    }


@app.get("/assets/{asset_tag}/rack-profile")
async def get_rack_profile(asset_tag: str):
    """
    Returns rack profile data for the rack containing the given asset.
    Includes all devices in the same rack with their U positions, parsed for SVG rendering.
    """
    target_norm = normalize_tag_value(asset_tag)
    asset_rows = df_assets[df_assets["AssetTagNorm"] == target_norm]
    if asset_rows.empty:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_tag}")

    rack_tag_raw = asset_rows.iloc[0].get("Rack", "")
    rack_tag = format_display_value(rack_tag_raw)

    # If the asset has no Rack field, check if it IS itself a rack (other assets reference it)
    if not rack_tag:
        is_rack = (
            df_assets["Rack"].astype(str).str.strip().str.upper().eq(target_norm).any()
        )
        if is_rack:
            rack_tag = format_display_value(asset_rows.iloc[0]["AssetTag"])
        else:
            return {
                "rack_tag": None,
                "rack_height": None,
                "devices": [],
                "target_u": None,
            }

    # Resolve rack asset height from Desc field (e.g. "42U rack")
    rack_asset_rows = df_assets[df_assets["AssetTag"].str.upper() == rack_tag.upper()]
    standard_rack_height = None
    if not rack_asset_rows.empty:
        desc = str(rack_asset_rows.iloc[0].get("Desc", ""))
        m = re.search(r"(\d+)\s*[Uu]", desc)
        if m:
            standard_rack_height = int(m.group(1))

    # Get all assets in this rack that have a RackU
    in_rack = df_assets[
        df_assets["Rack"].astype(str).str.strip().str.upper() == rack_tag.upper()
    ].copy()
    in_rack = in_rack[in_rack["RackU"].notna()]
    in_rack = in_rack[in_rack["RackU"].astype(str).str.strip().str.lower() != "nan"]

    # Exclude RackHeight == 0
    def rack_height_val(v):
        try:
            return float(v)
        except (ValueError, TypeError):
            return 1.0

    in_rack = in_rack[in_rack["RackHeight"].apply(rack_height_val) != 0]

    # Resolve conflicts: for same RackU keep highest AcqValue (random on tie)
    import math as _math

    def to_num(v):
        try:
            f = float(v)
            return float("-inf") if _math.isnan(f) else f
        except (ValueError, TypeError):
            return float("-inf")

    if not in_rack.empty:
        in_rack = in_rack.copy()
        in_rack["_cost"] = in_rack["AcqValue"].apply(to_num)
        kept_indices = []
        for _racku, grp in in_rack.groupby("RackU"):
            if len(grp) == 1:
                kept_indices.append(grp.index[0])
            else:
                max_cost = grp["_cost"].max()
                best = grp[grp["_cost"] == max_cost]
                kept_indices.append(best.sample(1).index[0])
        in_rack = in_rack.loc[kept_indices].drop(columns=["_cost"])

    devices = []
    for _, row in in_rack.iterrows():
        parsed = _parse_racku(str(row["RackU"]))
        if parsed is None:
            continue
        u_h = rack_height_val(row.get("RackHeight", 1))
        if u_h <= 0:
            u_h = 1
        u_h = int(round(u_h))
        devices.append(
            {
                "asset_tag": format_display_value(row["AssetTag"]),
                "usage": format_display_value(row.get("Usage", "")),
                "manufacturer": format_display_value(row.get("Manufacturer", "")),
                "model": format_display_value(row.get("Model", "")),
                "face": parsed["face"],
                "u_start": parsed["u_start"],
                "u_height": u_h,
                "x_start": parsed["x_start"],
                "x_end": parsed["x_end"],
                "is_target": row["AssetTag"].strip().upper() == target_norm,
            }
        )

    # Determine target asset's u_start for scroll-to
    target_u = None
    for d in devices:
        if d["is_target"]:
            target_u = d["u_start"]
            break

    return {
        "rack_tag": rack_tag,
        "rack_height": standard_rack_height,
        "devices": devices,
        "target_u": target_u,
    }


@app.get("/knowledgebase/tags")
async def get_knowledgebase_tags():
    """Returns all unique asset tags found on active KB issues, sorted case-insensitively."""
    return {"tags": KB_ACTIVE_TAGS}


@app.get("/knowledgebase/search")
async def search_knowledgebase(
    issue_id: Optional[str] = None,
    tag: List[str] = Query(default=[]),
    freeform: Optional[str] = None,
):
    """
    Search knowledge base issues by IssueID, Tag, or freeform text.
    Multiple tag params are combined with OR semantics.
    Results are sorted by Category, Subcategory, and SortOrder.
    """
    import re

    filtered_kb = df_knowledgebase.copy()

    # Combine issue_id, tag(s), and freeform with OR across criterion groups.
    # Build a boolean mask for each active group, then OR them together.
    masks = []

    # IssueID group: partial case-insensitive match
    if issue_id:
        masks.append(
            filtered_kb["IssueID"]
            .fillna("")
            .astype(str)
            .str.contains(issue_id, case=False, na=False)
        )

    # Tag group: OR across all supplied tags.  Each value is matched against the
    # Tags keyword column (strip leading #) and also against AppliesToAssetTag.
    if tag:
        tag_norms = {t.strip().lstrip("#").upper() for t in tag if t.strip()}
        if tag_norms:

            def _tag_match(row):
                asset_tags = {
                    t.strip().lstrip("#").upper()
                    for t in str(row.get("AppliesToAssetTagNorm", "") or "").split(",")
                }
                kw_tags = {
                    t.strip().lstrip("#").upper()
                    for t in str(row.get("Tags", "") or "").split(",")
                }
                return bool(tag_norms & (asset_tags | kw_tags))

            masks.append(filtered_kb.apply(_tag_match, axis=1))

    # Freeform text search (case-insensitive, whitespace/punctuation ignored)
    if freeform:
        # Normalize search text: remove whitespace and punctuation, lowercase
        def normalize_text(text):
            if pd.isna(text):
                return ""
            text_str = str(text)
            # Remove all non-alphanumeric characters
            return re.sub(r"[^a-z0-9]", "", text_str.lower())

        normalized_search = normalize_text(freeform)

        # Search across all text fields
        text_fields = [
            "IssueID",
            "Category",
            "Subcategory",
            "Title",
            "Symptom",
            "TriggerConditions",
            "LikelyCause",
            "RecoverySteps",
            "AppliesToAssetType",
            "AppliesToAssetTag",
            "Tags",
            "Notes",
        ]

        freeform_mask = pd.Series([False] * len(filtered_kb), index=filtered_kb.index)
        for field in text_fields:
            if field in filtered_kb.columns:
                freeform_mask = freeform_mask | filtered_kb[field].apply(
                    lambda x: normalized_search in normalize_text(x)
                )
        masks.append(freeform_mask)

    if not masks:
        # No criteria supplied — return empty rather than everything
        return []

    # OR all criterion groups together
    combined = masks[0]
    for m in masks[1:]:
        combined = combined | m
    filtered_kb = filtered_kb[combined]

    # Sort by Category, Subcategory, SortOrder
    filtered_kb = filtered_kb.sort_values(
        by=["Category", "Subcategory", "SortOrder"], na_position="last"
    )

    # Return all fields except the normalized tag field
    result_kb = filtered_kb.drop(columns=["AppliesToAssetTagNorm"], errors="ignore")
    processed_kb = clean_dataframe_for_json(result_kb)
    records = processed_kb.to_dict(orient="records")

    # Inject pre-computed bidirectional SeeAlsoResolved into each row
    for record in records:
        issue_key = str(record.get("IssueID") or "").strip().upper()
        record["SeeAlsoResolved"] = KB_SEEALSO_MAP.get(issue_key, [])

    return records


# --- Graphviz DOT Generation Function ---
def generate_dot_string(
    filtered_cables: pd.DataFrame,
    assets_df: pd.DataFrame,
    all_nodes_to_render: Set[str],
    node_fields: List[str],
    edge_fields: List[str],
    color_nodes_by_category: bool,
    color_edges_by_protocol: bool,
    collapse_strategy: str,
) -> str:
    """
    Generates a Graphviz DOT string from filtered cable and asset data,
    with custom node shapes and port displays.
    Ensures all specified nodes in `all_nodes_to_render` are included, even if isolated.
    """
    collapse_mode = collapse_strategy in {"protocol", "type"}
    dot_nodes: Set[str] = set()
    asset_nodes = {str(tag).strip() for tag in all_nodes_to_render if str(tag).strip()}
    node_ports: Dict[str, Dict[str, Dict[str, str]]] = {
        node_tag: {"src": {}, "dst": {}} for node_tag in asset_nodes
    }

    graph_edges: List[Dict[str, object]] = []

    def resolve_endpoint(row: pd.Series, side: str) -> Tuple[str, str, bool]:
        cable_tag = normalize_tag_value(row.get("Tag"))
        endpoint_tag = normalize_tag_value(
            row.get("SrcTag" if side == "src" else "DstTag")
        )
        endpoint_display = canonical_display_tag(endpoint_tag)
        port_value = normalize_asset_field_value(
            row.get("SrcPort" if side == "src" else "DstPort", "")
        )
        if endpoint_tag and endpoint_tag in VALID_CABLE_IDS_NORMALIZED:
            return build_junction_node_id(cable_tag, endpoint_tag), port_value, True
        return endpoint_display, port_value, False

    for _, row in filtered_cables.iterrows():
        src_node, src_port, src_is_junction = resolve_endpoint(row, "src")
        dst_node, dst_port, dst_is_junction = resolve_endpoint(row, "dst")
        if not src_node or not dst_node:
            continue
        graph_edges.append(
            {
                "src_node": src_node,
                "dst_node": dst_node,
                "src_port": src_port,
                "dst_port": dst_port,
                "src_is_junction": src_is_junction,
                "dst_is_junction": dst_is_junction,
                "row": row,
            }
        )
        dot_nodes.add(src_node)
        dot_nodes.add(dst_node)
        if not src_is_junction:
            node_ports.setdefault(src_node, {"src": {}, "dst": {}})
        if not dst_is_junction:
            node_ports.setdefault(dst_node, {"src": {}, "dst": {}})

    dot_nodes.update(asset_nodes)

    if collapse_mode:
        grouped_entries: Dict[Tuple[str, str, str], List[Dict[str, object]]] = {}
        for edge in graph_edges:
            row = edge["row"]
            group_label = collapse_label_for_row(row, collapse_strategy)
            key = (str(edge["src_node"]), str(edge["dst_node"]), group_label)
            grouped_entries.setdefault(key, []).append(edge)

        for (src_node, dst_node, group_label), edges in grouped_entries.items():
            if src_node in node_ports:
                node_ports[src_node]["src"][
                    sanitize_port_identifier(group_label, "out")
                ] = group_label
            if dst_node in node_ports:
                node_ports[dst_node]["dst"][
                    sanitize_port_identifier(group_label, "in")
                ] = group_label
    else:
        for edge in graph_edges:
            if edge["src_node"] in node_ports and edge["src_port"]:
                node_ports[str(edge["src_node"])]["src"][str(edge["src_port"])] = str(
                    edge["src_port"]
                )
            if edge["dst_node"] in node_ports and edge["dst_port"]:
                node_ports[str(edge["dst_node"])]["dst"][str(edge["dst_port"])] = str(
                    edge["dst_port"]
                )

    assets_by_tag = {
        row["AssetTag"]: row.to_dict()
        for _, row in assets_df.iterrows()
        if row.get("AssetTag")
    }

    node_definitions = []
    for node_tag_val in sorted(dot_nodes):
        if is_junction_node_id(node_tag_val):
            node_definitions.append(
                f'  "{node_tag_val}" [shape=point, width=0.14, height=0.14, label="", xlabel="", tooltip="Cable splice/junction"];'
            )
            continue

        asset_record = assets_by_tag.get(node_tag_val, {})
        display_tag = str(node_tag_val).strip()
        category_value = asset_record.get("Category") if asset_record else ""
        node_bg_color = DEFAULT_NODE_BACKGROUND
        if color_nodes_by_category and category_value:
            node_bg_color = get_category_color(category_value)

        center_rows = []
        for field_key in node_fields:
            field_value = get_asset_field_value(asset_record, field_key, display_tag)
            if field_key == "tag":
                center_rows.append(
                    f'<TR><TD ALIGN="CENTER"><B>{html.escape(field_value)}</B></TD></TR>'
                )
                continue
            if not field_value:
                continue
            center_rows.append(
                f'<TR><TD ALIGN="CENTER">{html.escape(field_value)}</TD></TR>'
            )
        if not center_rows:
            center_rows.append(
                f'<TR><TD ALIGN="CENTER"><B>{html.escape(display_tag)}</B></TD></TR>'
            )
        center_content = (
            '<TABLE BORDER="0" CELLBORDER="0" CELLPADDING="1">'
            + "".join(center_rows)
            + "</TABLE>"
        )

        dst_ports_content = ""
        dst_port_items = node_ports.get(node_tag_val, {}).get("dst", {})
        sorted_dst_ports = sorted(
            dst_port_items.items(), key=lambda item: _natural_key(item[1])
        )
        if sorted_dst_ports:
            dst_ports_content = (
                '<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="1">'
            )
            for port_id, label in sorted_dst_ports:
                dst_ports_content += f'<TR><TD PORT="{html.escape(port_id)}" ALIGN="LEFT">{html.escape(label)}</TD></TR>'
            dst_ports_content += "</TABLE>"

        src_ports_content = ""
        src_port_items = node_ports.get(node_tag_val, {}).get("src", {})
        sorted_src_ports = sorted(
            src_port_items.items(), key=lambda item: _natural_key(item[1])
        )
        if sorted_src_ports:
            src_ports_content = (
                '<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="1">'
            )
            for port_id, label in sorted_src_ports:
                src_ports_content += f'<TR><TD PORT="{html.escape(port_id)}" ALIGN="RIGHT">{html.escape(label)}</TD></TR>'
            src_ports_content += "</TABLE>"

        node_label_html = f'''<
        <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="4" BGCOLOR="white">
          <TR>
            <TD BORDER="1" WIDTH="40">{dst_ports_content}</TD>
            <TD BGCOLOR="{node_bg_color}" ALIGN="CENTER">
              {center_content}
            </TD>
            <TD BORDER="1" WIDTH="40">{src_ports_content}</TD>
          </TR>
        </TABLE>
        >'''
        node_definitions.append(
            f'  "{node_tag_val}" [label={node_label_html}, shape=plain];'
        )

    dot_edges = []
    if collapse_mode:
        for (src_node, dst_node, group_label), edges in grouped_entries.items():
            if not src_node or not dst_node:
                continue
            src_port_id = sanitize_port_identifier(group_label, "out")
            dst_port_id = sanitize_port_identifier(group_label, "in")
            count = len(edges)
            edge_label = f"{html.escape(group_label)} ({count})"
            edge_color_value = ""
            if color_edges_by_protocol and collapse_strategy == "protocol":
                edge_color_value = get_protocol_color(group_label)
            edge_attributes = [f'label="{edge_label}"']
            if edge_color_value:
                edge_attributes.append(f'color="{edge_color_value}"')
                edge_attributes.append(f'fontcolor="{edge_color_value}"')
            # Passthrough cables are bi-directional
            all_passthrough = all(
                str(e["row"].get("Type", "")).lower().find("passthrough") != -1
                for e in edges
            )
            if all_passthrough:
                edge_attributes.append('dir=both')
            attr_text = " [" + ", ".join(edge_attributes) + "]"
            from_port = (
                f'"{src_node}":"{src_port_id}"'
                if src_node in node_ports
                else f'"{src_node}"'
            )
            to_port = (
                f'"{dst_node}":"{dst_port_id}"'
                if dst_node in node_ports
                else f'"{dst_node}"'
            )
            dot_edges.append(f"  {from_port} -> {to_port}{attr_text};")
    else:
        for edge in graph_edges:
            row = edge["row"]
            label_parts = []
            for field_key in edge_fields:
                value = get_edge_field_value(row, field_key)
                if value:
                    label_parts.append(value)
            edge_label = "\\n".join(label_parts) if label_parts else ""
            edge_color_value = ""
            if color_edges_by_protocol:
                edge_color_value = get_protocol_color(row.get("Protocol"))
            edge_attributes = []
            if edge_label:
                edge_attributes.append(f'label="{edge_label}"')
            if edge_color_value:
                edge_attributes.append(f'color="{edge_color_value}"')
                edge_attributes.append(f'fontcolor="{edge_color_value}"')
            # Passthrough cables are bi-directional
            if str(row.get("Type", "")).lower().find("passthrough") != -1:
                edge_attributes.append('dir=both')

            from_port = (
                f'"{edge["src_node"]}":"{html.escape(str(edge["src_port"]))}"'
                if edge["src_node"] in node_ports and edge["src_port"]
                else f'"{edge["src_node"]}"'
            )
            to_port = (
                f'"{edge["dst_node"]}":"{html.escape(str(edge["dst_port"]))}"'
                if edge["dst_node"] in node_ports and edge["dst_port"]
                else f'"{edge["dst_node"]}"'
            )
            attr_text = ""
            if edge_attributes:
                attr_text = " [" + ", ".join(edge_attributes) + "]"
            dot_edges.append(f"  {from_port} -> {to_port}{attr_text};")

    dot_string = "digraph G {\n  rankdir=LR;\n  node [fontsize=10];\n  edge [fontsize=8];\n"  # Added rankdir and default font sizes
    dot_string += "\n".join(node_definitions)
    dot_string += "\n"
    dot_string += "\n".join(dot_edges)
    dot_string += "\n}"
    return dot_string


@app.get("/assets/search", response_model=List[Dict[str, str]])
async def search_assets(
    asset_tag: Optional[str] = None,
    manufacturer: Optional[str] = None,
    model: Optional[str] = None,
    building: Optional[str] = None,
    floor: Optional[str] = None,
    room: Optional[str] = None,
    sector: Optional[str] = None,
    purc_from: Optional[str] = None,
    invoice: Optional[str] = None,
    in_service_only: bool = True,
):
    """
    Search for assets by asset tag, manufacturer, model, location, or financial fields.
    Optionally filter to only in-service items (default: True).
    """
    filtered_assets = df_assets.copy()

    if in_service_only:
        filtered_assets = filtered_assets[
            filtered_assets["InService"].fillna("").astype(str).str.strip().str.upper()
            .isin({"Y", "YES", "1", "TRUE"})
        ]

    if asset_tag:
        filtered_assets = filtered_assets[
            filtered_assets["AssetTag"].str.contains(asset_tag, case=False, na=False)
        ]
    if manufacturer:
        filtered_assets = filtered_assets[
            filtered_assets["Manufacturer"].str.contains(manufacturer, case=False, na=False)
        ]
    if model:
        filtered_assets = filtered_assets[
            filtered_assets["Model"].str.contains(model, case=False, na=False)
        ]
    if building and "Building" in filtered_assets.columns:
        filtered_assets = filtered_assets[
            filtered_assets["Building"].fillna("").astype(str).str.contains(building, case=False, na=False)
        ]
    if floor and "Floor" in filtered_assets.columns:
        filtered_assets = filtered_assets[
            filtered_assets["Floor"].fillna("").astype(str).str.contains(floor, case=False, na=False)
        ]
    if room and "Room" in filtered_assets.columns:
        filtered_assets = filtered_assets[
            filtered_assets["Room"].fillna("").astype(str).str.contains(room, case=False, na=False)
        ]
    if sector and "Sector" in filtered_assets.columns:
        filtered_assets = filtered_assets[
            filtered_assets["Sector"].fillna("").astype(str).str.contains(sector, case=False, na=False)
        ]
    if purc_from and "PurcFrom" in filtered_assets.columns:
        filtered_assets = filtered_assets[
            filtered_assets["PurcFrom"].fillna("").astype(str).str.contains(purc_from, case=False, na=False)
        ]
    if invoice and "Invoice" in filtered_assets.columns:
        filtered_assets = filtered_assets[
            filtered_assets["Invoice"].fillna("").astype(str).str.contains(invoice, case=False, na=False)
        ]

    filtered_assets = filtered_assets.drop(columns=["AssetTagNorm"], errors="ignore")
    processed_assets = clean_dataframe_for_json(filtered_assets)
    return processed_assets.to_dict(orient="records")


@app.get("/assets/tags")
async def list_asset_tags():
    """Returns the list of known asset tags for dropdowns/selections."""
    tags = sorted(
        [canonical_display_tag(tag) for tag in VALID_ASSET_TAGS_NORMALIZED],
        key=lambda value: value.lower(),
    )
    return {"tags": tags}


@app.get("/assets/linked")
async def get_linked_assets(tag: str, direction: str = "outbound"):
    """Returns the list of directly connected assets for the given tag."""
    norm = normalize_tag_value(tag)
    if not norm:
        raise HTTPException(status_code=400, detail="Asset tag is required.")
    if norm not in ALL_KNOWN_TAGS_NORMALIZED:
        raise HTTPException(status_code=404, detail=f"Unknown asset tag: {tag}")

    direction_value = direction.lower()
    if direction_value not in {"inbound", "outbound", "both"}:
        raise HTTPException(
            status_code=400, detail="Direction must be inbound, outbound, or both."
        )

    peers: Set[str] = set()
    if direction_value in {"outbound", "both"}:
        outbound_rows = df_cables[df_cables["SrcTagNorm"] == norm]
        for raw in outbound_rows["DstTag"].tolist():
            canonical = canonical_display_tag(raw)
            if canonical:
                peers.add(canonical)
    if direction_value in {"inbound", "both"}:
        inbound_rows = df_cables[df_cables["DstTagNorm"] == norm]
        for raw in inbound_rows["SrcTag"].tolist():
            canonical = canonical_display_tag(raw)
            if canonical:
                peers.add(canonical)

    sorted_peers = sorted(peers, key=lambda value: value.lower())
    return {
        "tag": canonical_display_tag(tag),
        "direction": direction_value,
        "peers": sorted_peers,
    }


@app.get("/cables/filter", response_model=CableFilterResponse)
async def filter_cables(
    target_tag: Optional[str] = None,
    cable_id: Optional[str] = None,
    direction: str = "both",  # "in", "out", "both"
    cable_type: Optional[str] = None,
    protocol: Optional[str] = None,
    visible_asset_tags: Optional[str] = Query(None),  # Comma-separated string
    additional_asset_tags: Optional[str] = Query(None),  # New: Comma-separated string
    expansions: Optional[str] = Query(None),  # Node expansion directives
    node_fields: Optional[str] = Query(None),
    edge_fields: Optional[str] = Query(None),
    hidden_cable_ids: Optional[str] = Query(
        None
    ),  # Comma-separated cable IDs to suppress
    exclude_internal_routes: bool = True,
    include_physical_routes: bool = Query(True),
    include_logical_routes: bool = Query(False),
    include_passthroughs: bool = Query(False),
):
    """
    Filter cables based on a target asset tag, direction, optional cable type,
    an optional list of visible asset tags, and an optional list of additional asset tags.
    """

    if direction not in ["in", "out", "both"]:
        raise HTTPException(
            status_code=400, detail="Direction must be 'in', 'out', or 'both'."
        )

    target_norm, primary_target = resolve_query_target(target_tag, cable_id)

    expansion_value = expansions if isinstance(expansions, str) else (expansions or "")
    expansion_map = parse_expansion_param(expansion_value, direction, target_norm)
    broadly_involved_asset_tags_norm: Set[str] = set(expansion_map.keys())

    if visible_asset_tags:
        visible_norm_list = normalize_tag_list(visible_asset_tags)
        broadly_involved_asset_tags_norm.update(visible_norm_list)

    if additional_asset_tags:
        additional_norm_list = normalize_tag_list(additional_asset_tags)
        invalid_tags = [
            tag for tag in additional_norm_list if tag not in ALL_KNOWN_TAGS_NORMALIZED
        ]
        if invalid_tags:
            display_invalid = [canonical_display_tag(tag) for tag in invalid_tags]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid additional asset tags: {', '.join(display_invalid)}. Please check your input.",
            )
        broadly_involved_asset_tags_norm.update(additional_norm_list)

    candidate_cables = build_candidate_cables(expansion_map)

    # Apply cable type filtering
    if cable_type:
        candidate_cables = candidate_cables[
            candidate_cables["Type"].str.contains(cable_type, case=False, na=False)
        ]
    if protocol:
        candidate_cables = candidate_cables[
            candidate_cables["Protocol"].str.contains(protocol, case=False, na=False)
        ]

    # Suppress explicitly hidden cable IDs.
    if hidden_cable_ids:
        hidden_ids_norm = {
            normalize_tag_value(t) for t in hidden_cable_ids.split(",") if t.strip()
        }
        candidate_cables = candidate_cables[
            ~candidate_cables["TagNorm"].isin(hidden_ids_norm)
        ]

    # Exclude internal routes (where SrcTag == DstTag and Type contains "route")
    if exclude_internal_routes:
        candidate_cables = candidate_cables[
            ~(
                (candidate_cables["SrcTagNorm"] == candidate_cables["DstTagNorm"])
                & (candidate_cables["Type"].str.contains("route", case=False, na=False))
            )
        ]

    # Filter by physical/logical route type.
    # Self-referential route cables (SrcTag==DstTag) are excluded separately by
    # exclude_internal_routes above; do not strip them here when that flag is False.
    # A protocol filter already scopes results precisely, so include logical routes in that case.
    is_logical = candidate_cables["Type"].str.contains("route", case=False, na=False)
    is_self_route = (candidate_cables["SrcTagNorm"] == candidate_cables["DstTagNorm"]) & is_logical
    effective_include_logical = include_logical_routes or bool(protocol)
    if not effective_include_logical:
        candidate_cables = candidate_cables[~is_logical | is_self_route]
    if not include_physical_routes:
        candidate_cables = candidate_cables[is_logical]

    # Filter passthroughs (Type contains "passthrough")
    if not include_passthroughs:
        is_passthrough = candidate_cables["Type"].str.contains("passthrough", case=False, na=False)
        candidate_cables = candidate_cables[~is_passthrough]

    # If we were given an explicit visible set, only include cables whose endpoints are visible.
    if visible_asset_tags:
        visible_tags_set = set(normalize_tag_list(visible_asset_tags))
        candidate_cables = candidate_cables[
            (
                candidate_cables["SrcTagNorm"].isin(visible_tags_set)
                | candidate_cables["SrcTagNorm"].isin(VALID_CABLE_IDS_NORMALIZED)
            )
            & (
                candidate_cables["DstTagNorm"].isin(visible_tags_set)
                | candidate_cables["DstTagNorm"].isin(VALID_CABLE_IDS_NORMALIZED)
            )
        ]

    discovered_asset_tags: Set[str] = set()
    for raw_tag in candidate_cables["SrcTagNorm"].tolist():
        if raw_tag in VALID_CABLE_IDS_NORMALIZED:
            continue
        canonical = canonical_display_tag(raw_tag)
        if canonical:
            discovered_asset_tags.add(canonical)
    for raw_tag in candidate_cables["DstTagNorm"].tolist():
        if raw_tag in VALID_CABLE_IDS_NORMALIZED:
            continue
        canonical = canonical_display_tag(raw_tag)
        if canonical:
            discovered_asset_tags.add(canonical)
    discovered_asset_tags.update(
        {
            canonical_display_tag(tag)
            for tag in broadly_involved_asset_tags_norm
            if is_asset_tag(tag)
        }
    )

    # Canonicalize Src/Dst tags for downstream consumers (tables, diagram parsing).
    candidate_cables["SrcTag"] = candidate_cables["SrcTag"].apply(canonical_display_tag)
    candidate_cables["DstTag"] = candidate_cables["DstTag"].apply(canonical_display_tag)

    cleaned_asset_tags = sorted(
        [tag for tag in (str(t).strip() for t in discovered_asset_tags) if tag],
        key=lambda x: x.lower(),
    )

    candidate_cables = candidate_cables.drop(
        columns=["TagNorm", "SrcTagNorm", "DstTagNorm"], errors="ignore"
    )
    processed_cables = clean_dataframe_for_json(candidate_cables)
    return {
        "cables": processed_cables.to_dict(orient="records"),
        "asset_tags": cleaned_asset_tags,
        "primary_target": primary_target,
    }


def compute_graph_elements(
    filtered_cables: pd.DataFrame,
    assets_df: pd.DataFrame,
    all_nodes_to_render: Set[str],
    node_fields: List[str],
    edge_fields: List[str],
    color_nodes_by_category: bool,
    color_edges_by_protocol: bool,
    collapse_strategy: str,
) -> Dict[str, Any]:
    """
    Builds a Cytoscape-compatible graph from filtered cable and asset data.
    Returns {"nodes": [...], "edges": [...]}.
    Mirrors generate_dot_string's logic but outputs JSON instead of DOT.
    """
    collapse_mode = collapse_strategy in {"protocol", "type"}
    asset_nodes = {str(tag).strip() for tag in all_nodes_to_render if str(tag).strip()}
    node_ports: Dict[str, Dict[str, Dict[str, str]]] = {
        tag: {"src": {}, "dst": {}} for tag in asset_nodes
    }
    graph_edges: List[Dict[str, object]] = []

    def resolve_endpoint(row: pd.Series, side: str) -> Tuple[str, str, bool]:
        cable_tag = normalize_tag_value(row.get("Tag"))
        endpoint_tag = normalize_tag_value(row.get("SrcTag" if side == "src" else "DstTag"))
        endpoint_display = canonical_display_tag(endpoint_tag)
        port_value = normalize_asset_field_value(row.get("SrcPort" if side == "src" else "DstPort", ""))
        if endpoint_tag and endpoint_tag in VALID_CABLE_IDS_NORMALIZED:
            return build_junction_node_id(cable_tag, endpoint_tag), port_value, True
        return endpoint_display, port_value, False

    all_nodes: Set[str] = set(asset_nodes)
    for _, row in filtered_cables.iterrows():
        src_node, src_port, src_is_junc = resolve_endpoint(row, "src")
        dst_node, dst_port, dst_is_junc = resolve_endpoint(row, "dst")
        if not src_node or not dst_node:
            continue
        graph_edges.append({
            "src_node": src_node, "dst_node": dst_node,
            "src_port": src_port, "dst_port": dst_port,
            "src_is_junction": src_is_junc, "dst_is_junction": dst_is_junc,
            "row": row,
        })
        all_nodes.add(src_node)
        all_nodes.add(dst_node)
        if not src_is_junc:
            node_ports.setdefault(src_node, {"src": {}, "dst": {}})
        if not dst_is_junc:
            node_ports.setdefault(dst_node, {"src": {}, "dst": {}})

    grouped_entries: Dict[Tuple[str, str, str], List[Dict[str, object]]] = {}
    if collapse_mode:
        for edge in graph_edges:
            row = edge["row"]
            gl = collapse_label_for_row(row, collapse_strategy)
            grouped_entries.setdefault((str(edge["src_node"]), str(edge["dst_node"]), gl), []).append(edge)
        for (src_node, dst_node, gl), _ in grouped_entries.items():
            if src_node in node_ports:
                node_ports[src_node]["src"][sanitize_port_identifier(gl, "out")] = gl
            if dst_node in node_ports:
                node_ports[dst_node]["dst"][sanitize_port_identifier(gl, "in")] = gl
    else:
        for edge in graph_edges:
            if edge["src_node"] in node_ports and edge["src_port"]:
                node_ports[str(edge["src_node"])]["src"][str(edge["src_port"])] = str(edge["src_port"])
            if edge["dst_node"] in node_ports and edge["dst_port"]:
                node_ports[str(edge["dst_node"])]["dst"][str(edge["dst_port"])] = str(edge["dst_port"])

    assets_by_tag = {row["AssetTag"]: row.to_dict() for _, row in assets_df.iterrows() if row.get("AssetTag")}

    # Stable port ID used in both node port declarations and edge sourcePort/targetPort
    def _pid(node: str, side: str, label: str) -> str:
        return f"{node}::{side}::{re.sub(r'[^A-Za-z0-9_]', '_', str(label))}"

    # Sizing constants (must match the CSS port row height)
    PORT_COL_W   = 80
    CENTER_W     = 160
    PORT_ROW_H   = 22
    CENTER_ROW_H = 18
    V_PAD        = 16

    # --- Bidirectional barycenter port ordering (Sugiyama-style) ---
    # Pre-build junction hop maps so barycenter looks through cable-splice nodes
    # to reach the real asset endpoint on either side.
    _junc_fwd: Dict[str, List[Tuple[str, str]]] = {}  # junction -> [(real_dst, dst_port)]
    _junc_bwd: Dict[str, List[Tuple[str, str]]] = {}  # junction -> [(real_src, src_port)]
    for _e in graph_edges:
        _sn, _sp = str(_e["src_node"]), str(_e["src_port"])
        _dn, _dp = str(_e["dst_node"]), str(_e["dst_port"])
        if is_junction_node_id(_dn) and not is_junction_node_id(_sn):
            _junc_bwd.setdefault(_dn, []).append((_sn, _sp))
        if is_junction_node_id(_sn) and not is_junction_node_id(_dn):
            _junc_fwd.setdefault(_sn, []).append((_dn, _dp))

    def _make_rank_map(ports_by_node: Dict[str, List[str]]) -> Dict[Tuple[str, str], int]:
        return {(node, lbl): i for node, lst in ports_by_node.items() for i, lbl in enumerate(lst)}

    def _fwd_bary(node: str, lbl: str, in_rank: Dict) -> float:
        """Out-port barycenter: avg in-port rank of connected neighbours (junction-transparent)."""
        ranks = []
        for e in graph_edges:
            if str(e["src_node"]) != node or str(e["src_port"]) != lbl:
                continue
            dn, dp = str(e["dst_node"]), str(e["dst_port"])
            if is_junction_node_id(dn):
                for rdn, rdp in _junc_fwd.get(dn, []):
                    if (rdn, rdp) in in_rank:
                        ranks.append(in_rank[(rdn, rdp)])
            elif (dn, dp) in in_rank:
                ranks.append(in_rank[(dn, dp)])
        return sum(ranks) / len(ranks) if ranks else float("inf")

    def _bwd_bary(node: str, lbl: str, out_rank: Dict) -> float:
        """In-port barycenter: avg out-port rank of feeding neighbours (junction-transparent)."""
        ranks = []
        for e in graph_edges:
            if str(e["dst_node"]) != node or str(e["dst_port"]) != lbl:
                continue
            sn, sp = str(e["src_node"]), str(e["src_port"])
            if is_junction_node_id(sn):
                for rsn, rsp in _junc_bwd.get(sn, []):
                    if (rsn, rsp) in out_rank:
                        ranks.append(out_rank[(rsn, rsp)])
            elif (sn, sp) in out_rank:
                ranks.append(out_rank[(sn, sp)])
        return sum(ranks) / len(ranks) if ranks else float("inf")

    non_junc_nodes = [n for n in all_nodes if not is_junction_node_id(n)]

    # Seed both sides with natural sort
    in_ports_by_node: Dict[str, List[str]] = {
        n: sorted(node_ports.get(n, {"dst": {}})["dst"].values(), key=_natural_key)
        for n in non_junc_nodes
    }
    out_ports_by_node: Dict[str, List[str]] = {
        n: sorted(node_ports.get(n, {"src": {}})["src"].values(), key=_natural_key)
        for n in non_junc_nodes
    }

    # Two bidirectional sweeps: each forward pass tightens out-ports using the current
    # in-port ranks; each backward pass tightens in-ports using the new out-port ranks.
    for _ in range(2):
        in_rank = _make_rank_map(in_ports_by_node)
        out_ports_by_node = {
            n: sorted(
                node_ports.get(n, {"src": {}})["src"].values(),
                key=lambda lbl, n=n: (_fwd_bary(n, lbl, in_rank), _natural_key(lbl)),
            )
            for n in non_junc_nodes
        }
        out_rank = _make_rank_map(out_ports_by_node)
        in_ports_by_node = {
            n: sorted(
                node_ports.get(n, {"dst": {}})["dst"].values(),
                key=lambda lbl, n=n: (_bwd_bary(n, lbl, out_rank), _natural_key(lbl)),
            )
            for n in non_junc_nodes
        }

    # Final forward sweep using the converged in-port order
    in_rank = _make_rank_map(in_ports_by_node)
    out_ports_by_node = {
        n: sorted(
            node_ports.get(n, {"src": {}})["src"].values(),
            key=lambda lbl, n=n: (_fwd_bary(n, lbl, in_rank), _natural_key(lbl)),
        )
        for n in non_junc_nodes
    }
    # --- end port ordering ---

    cy_nodes: List[Dict] = []
    for node_tag in sorted(all_nodes):
        if is_junction_node_id(node_tag):
            cy_nodes.append({"data": {
                "id": node_tag, "label": "•", "display_tag": node_tag,
                "is_junction": True, "bg_color": "#888888",
                "in_ports": [], "out_ports": [], "fields": {},
                "node_width": 12, "node_height": 12,
            }})
            continue

        asset_record = assets_by_tag.get(node_tag, {})
        display_tag = str(node_tag).strip()
        bg_color = DEFAULT_NODE_BACKGROUND
        if color_nodes_by_category and asset_record.get("Category"):
            bg_color = get_category_color(asset_record["Category"])

        fields: Dict[str, str] = {}
        for field_key in node_fields:
            val = get_asset_field_value(asset_record, field_key, display_tag)
            if val:
                fields[field_key] = val

        in_ports  = in_ports_by_node.get(node_tag, [])
        out_ports = out_ports_by_node.get(node_tag, [])

        has_ports = bool(in_ports or out_ports)
        node_width = CENTER_W + (PORT_COL_W * 2 if has_ports else 0)
        center_height  = len(fields) * CENTER_ROW_H + V_PAD
        max_port_rows  = max(len(in_ports), len(out_ports), 0)
        port_height    = max_port_rows * PORT_ROW_H + V_PAD if max_port_rows else 0
        node_height    = max(center_height, port_height, 44)

        # ELK port declarations — positions are from the node's top-left corner.
        # Using FIXED_POS so ELK routes edges from/to exactly these coordinates,
        # which match the HTML overlay port row positions (justify-content:center).
        elk_ports: List[Dict] = []
        for i, lbl in enumerate(in_ports):
            py = node_height / 2.0 - len(in_ports) * PORT_ROW_H / 2.0 + i * PORT_ROW_H + PORT_ROW_H / 2.0
            elk_ports.append({"id": _pid(node_tag, "in", lbl),
                               "x": 0.0, "y": py,
                               "properties": {"port.side": "WEST"}})
        for i, lbl in enumerate(out_ports):
            py = node_height / 2.0 - len(out_ports) * PORT_ROW_H / 2.0 + i * PORT_ROW_H + PORT_ROW_H / 2.0
            elk_ports.append({"id": _pid(node_tag, "out", lbl),
                               "x": float(node_width), "y": py,
                               "properties": {"port.side": "EAST"}})

        cy_nodes.append({"data": {
            "id": node_tag, "display_tag": display_tag,
            "is_junction": False, "bg_color": bg_color,
            "fields": fields, "in_ports": in_ports, "out_ports": out_ports,
            "node_width": node_width, "node_height": node_height,
            "ports": elk_ports,
            "properties": {"portConstraints": "FIXED_POS"},
        }})

    cy_edges: List[Dict] = []
    if collapse_mode:
        for (src_node, dst_node, group_label), edges in grouped_entries.items():
            if not src_node or not dst_node:
                continue
            count = len(edges)
            color = DEFAULT_PROTOCOL_COLOR
            if color_edges_by_protocol and collapse_strategy == "protocol":
                color = get_protocol_color(group_label)
            all_pt = all("passthrough" in str(e["row"].get("Type", "")).lower() for e in edges)
            edge_data: Dict[str, Any] = {
                "id": f"collapsed::{src_node}::{dst_node}::{group_label}",
                "source": src_node, "target": dst_node,
                "label": f"{group_label} ({count})",
                "color": color, "bidirectional": all_pt,
                "collapsed": True, "count": count, "group_label": group_label,
                "cable_id": "", "src_port": group_label, "dst_port": group_label,
                "protocol": group_label if collapse_strategy == "protocol" else "",
                "type": group_label if collapse_strategy == "type" else "",
            }
            if not is_junction_node_id(src_node):
                edge_data["sourcePort"] = _pid(src_node, "out", group_label)
            if not is_junction_node_id(dst_node):
                edge_data["targetPort"] = _pid(dst_node, "in", group_label)
            cy_edges.append({"data": edge_data})
    else:
        for edge in graph_edges:
            row = edge["row"]
            label_parts = []
            for field_key in edge_fields:
                raw = get_edge_field_value(row, field_key)
                if raw:
                    clean = raw.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
                    label_parts.append(clean)
            color = get_protocol_color(row.get("Protocol")) if color_edges_by_protocol else DEFAULT_PROTOCOL_COLOR
            is_pt = "passthrough" in str(row.get("Type", "")).lower()
            cable_id = canonical_display_tag(normalize_tag_value(str(row.get("Tag", ""))))
            edge_id = cable_id or f"{edge['src_node']}::{edge['dst_node']}"
            edge_data = {
                "id": edge_id, "source": edge["src_node"], "target": edge["dst_node"],
                "label": "\n".join(label_parts),
                "color": color, "bidirectional": is_pt, "collapsed": False,
                "cable_id": cable_id,
                "src_port": edge["src_port"] or "", "dst_port": edge["dst_port"] or "",
                "protocol": str(row.get("Protocol", "") or ""),
                "type":     str(row.get("Type",     "") or ""),
                "usage":    str(row.get("Usage",    "") or ""),
            }
            if edge["src_port"] and not edge["src_is_junction"]:
                edge_data["sourcePort"] = _pid(edge["src_node"], "out", edge["src_port"])
            if edge["dst_port"] and not edge["dst_is_junction"]:
                edge_data["targetPort"] = _pid(edge["dst_node"], "in", edge["dst_port"])
            cy_edges.append({"data": edge_data})

    return {"nodes": cy_nodes, "edges": cy_edges}



@app.get("/graph/json")
async def get_graph_json(
    target_tag: Optional[str] = None,
    cable_id: Optional[str] = None,
    direction: str = "both",
    cable_type: Optional[str] = None,
    protocol: Optional[str] = None,
    visible_asset_tags: Optional[str] = Query(None),
    additional_asset_tags: Optional[str] = Query(None),
    expansions: Optional[str] = Query(None),
    node_fields: Optional[str] = Query(None),
    edge_fields: Optional[str] = Query(None),
    hidden_cable_ids: Optional[str] = Query(None),
    color_nodes_by_category: bool = Query(False),
    color_edges_by_protocol: bool = Query(False),
    collapse_strategy: Optional[str] = Query("none"),
    exclude_internal_routes: bool = True,
    include_physical_routes: bool = Query(True),
    include_logical_routes: bool = Query(False),
    include_passthroughs: bool = Query(False),
):
    """Returns Cytoscape-compatible graph JSON for the diagram frontend."""
    target_norm, _ = resolve_query_target(target_tag, cable_id)
    expansion_value = expansions if isinstance(expansions, str) else (expansions or "")
    expansion_map = parse_expansion_param(expansion_value, direction, target_norm)
    selected_node_fields = parse_field_selection(node_fields, NODE_FIELD_OPTIONS, DEFAULT_NODE_FIELDS)
    selected_edge_fields = parse_field_selection(edge_fields, EDGE_FIELD_OPTIONS, DEFAULT_EDGE_FIELDS)

    broadly_involved = set(expansion_map.keys())
    if additional_asset_tags:
        extra = normalize_tag_list(additional_asset_tags if isinstance(additional_asset_tags, str) else str(additional_asset_tags))
        invalid = [t for t in extra if t not in ALL_KNOWN_TAGS_NORMALIZED]
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid additional asset tags: {', '.join(canonical_display_tag(t) for t in invalid)}")
        broadly_involved.update(extra)

    candidate_cables = build_candidate_cables(expansion_map)

    if cable_type:
        candidate_cables = candidate_cables[candidate_cables["Type"].str.contains(cable_type, case=False, na=False)]
    if protocol:
        candidate_cables = candidate_cables[candidate_cables["Protocol"].str.contains(protocol, case=False, na=False)]
    if hidden_cable_ids:
        hidden_norm = {normalize_tag_value(t) for t in hidden_cable_ids.split(",") if t.strip()}
        candidate_cables = candidate_cables[~candidate_cables["TagNorm"].isin(hidden_norm)]

    if exclude_internal_routes:
        candidate_cables = candidate_cables[
            ~((candidate_cables["SrcTagNorm"] == candidate_cables["DstTagNorm"])
              & candidate_cables["Type"].str.contains("route", case=False, na=False))
        ]

    is_logical = candidate_cables["Type"].str.contains("route", case=False, na=False)
    is_self_route = (candidate_cables["SrcTagNorm"] == candidate_cables["DstTagNorm"]) & is_logical
    effective_include_logical = include_logical_routes or bool(protocol) or (collapse_strategy or "none").lower() in ("protocol", "type")
    if not effective_include_logical:
        candidate_cables = candidate_cables[~is_logical | is_self_route]
    if not include_physical_routes:
        candidate_cables = candidate_cables[is_logical]
    if not include_passthroughs:
        candidate_cables = candidate_cables[~candidate_cables["Type"].str.contains("passthrough", case=False, na=False)]

    visible_norm_set = set(normalize_tag_list(visible_asset_tags)) if visible_asset_tags else set()
    if visible_norm_set:
        filtered_cables = candidate_cables[
            (candidate_cables["SrcTagNorm"].isin(visible_norm_set) | candidate_cables["SrcTagNorm"].isin(VALID_CABLE_IDS_NORMALIZED))
            & (candidate_cables["DstTagNorm"].isin(visible_norm_set) | candidate_cables["DstTagNorm"].isin(VALID_CABLE_IDS_NORMALIZED))
        ].copy()
    else:
        filtered_cables = candidate_cables.copy()

    filtered_cables["SrcTag"] = filtered_cables["SrcTag"].apply(canonical_display_tag)
    filtered_cables["DstTag"] = filtered_cables["DstTag"].apply(canonical_display_tag)

    candidate_asset_nodes_norm = {t for t in set(filtered_cables["SrcTagNorm"]) | set(filtered_cables["DstTagNorm"]) if is_asset_tag(t)}
    candidate_asset_nodes_norm.update({t for t in broadly_involved if is_asset_tag(t)})
    if visible_norm_set:
        final_asset_nodes_norm = candidate_asset_nodes_norm & visible_norm_set
        final_asset_nodes_norm.update({t for t in expansion_map if is_asset_tag(t)})
    else:
        final_asset_nodes_norm = candidate_asset_nodes_norm
    final_nodes_to_render = denormalize_tags(final_asset_nodes_norm)

    if not final_nodes_to_render and filtered_cables.empty:
        return {"nodes": [], "edges": [], "empty": True}

    graph_assets = df_assets[df_assets["AssetTag"].isin(final_nodes_to_render)]
    collapse_value = (collapse_strategy or "none").lower()
    if collapse_value not in COLLAPSE_OPTIONS:
        raise HTTPException(status_code=400, detail="Invalid collapse strategy. Choose none, protocol, or type.")

    return compute_graph_elements(
        filtered_cables, graph_assets, final_nodes_to_render,
        selected_node_fields, selected_edge_fields,
        color_nodes_by_category, color_edges_by_protocol, collapse_value,
    )


@app.get("/graphviz/dot")
async def get_graphviz_dot(
    target_tag: Optional[str] = None,
    cable_id: Optional[str] = None,
    direction: str = "both",
    cable_type: Optional[str] = None,
    protocol: Optional[str] = None,
    visible_asset_tags: Optional[str] = Query(None),  # Comma-separated string
    additional_asset_tags: Optional[str] = Query(None),  # New: Comma-separated string
    expansions: Optional[str] = Query(None),  # Node expansion directives
    node_fields: Optional[str] = Query(None),  # Comma-separated node label fields
    edge_fields: Optional[str] = Query(None),  # Comma-separated edge label fields
    hidden_cable_ids: Optional[str] = Query(
        None
    ),  # Comma-separated cable IDs to suppress
    color_nodes_by_category: bool = Query(False),
    color_edges_by_protocol: bool = Query(False),
    collapse_strategy: Optional[str] = Query("none"),
    exclude_internal_routes: bool = True,
    include_physical_routes: bool = Query(True),
    include_logical_routes: bool = Query(False),
    include_passthroughs: bool = Query(False),
):
    """
    Generates a Graphviz DOT string for filtered cables and assets.
    """
    # TEMPORARY: Return hardcoded SVG for debugging
    # return Response(content='<svg width="100" height="100"><circle cx="50" cy="50" r="40" stroke="black" stroke-width="3" fill="red" /></svg>', media_type="image/svg+xml")

    target_norm, _ = resolve_query_target(target_tag, cable_id)

    expansion_value = expansions if isinstance(expansions, str) else (expansions or "")
    expansion_map = parse_expansion_param(expansion_value, direction, target_norm)
    selected_node_fields = parse_field_selection(
        node_fields, NODE_FIELD_OPTIONS, DEFAULT_NODE_FIELDS
    )
    selected_edge_fields = parse_field_selection(
        edge_fields, EDGE_FIELD_OPTIONS, DEFAULT_EDGE_FIELDS
    )
    broadly_involved_asset_tags_norm = set(expansion_map.keys())
    if additional_asset_tags:
        additional_tags_list = normalize_tag_list(
            additional_asset_tags
            if isinstance(additional_asset_tags, str)
            else str(additional_asset_tags)
        )
        invalid_tags = [
            tag for tag in additional_tags_list if tag not in ALL_KNOWN_TAGS_NORMALIZED
        ]
        if invalid_tags:
            display_invalid = [canonical_display_tag(tag) for tag in invalid_tags]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid additional asset tags: {', '.join(display_invalid)}. Please check your input.",
            )
        broadly_involved_asset_tags_norm.update(additional_tags_list)

    candidate_cables = build_candidate_cables(expansion_map)

    if cable_type:
        candidate_cables = candidate_cables[
            candidate_cables["Type"].str.contains(cable_type, case=False, na=False)
        ]
    if protocol:
        candidate_cables = candidate_cables[
            candidate_cables["Protocol"].str.contains(protocol, case=False, na=False)
        ]

    # Suppress explicitly hidden cable IDs.
    if hidden_cable_ids:
        hidden_ids_norm = {
            normalize_tag_value(t) for t in hidden_cable_ids.split(",") if t.strip()
        }
        candidate_cables = candidate_cables[
            ~candidate_cables["TagNorm"].isin(hidden_ids_norm)
        ]

    # Exclude internal routes (where SrcTag == DstTag and Type contains "route")
    if exclude_internal_routes:
        candidate_cables = candidate_cables[
            ~(
                (candidate_cables["SrcTagNorm"] == candidate_cables["DstTagNorm"])
                & (candidate_cables["Type"].str.contains("route", case=False, na=False))
            )
        ]

    # Filter by physical/logical route type.
    # Self-referential route cables (SrcTag==DstTag) are excluded separately by
    # exclude_internal_routes above; do not strip them here when that flag is False.
    # A protocol filter or protocol collapse view scopes results precisely; include logical routes.
    is_logical = candidate_cables["Type"].str.contains("route", case=False, na=False)
    is_self_route = (candidate_cables["SrcTagNorm"] == candidate_cables["DstTagNorm"]) & is_logical
    effective_include_logical = include_logical_routes or bool(protocol) or (
        (collapse_strategy or "none").lower() in ("protocol", "type")
    )
    if not effective_include_logical:
        candidate_cables = candidate_cables[~is_logical | is_self_route]
    if not include_physical_routes:
        candidate_cables = candidate_cables[is_logical]

    # Filter passthroughs (Type contains "passthrough")
    if not include_passthroughs:
        is_passthrough = candidate_cables["Type"].str.contains("passthrough", case=False, na=False)
        candidate_cables = candidate_cables[~is_passthrough]

    visible_norm_set = (
        set(normalize_tag_list(visible_asset_tags)) if visible_asset_tags else set()
    )
    if visible_norm_set:
        filtered_cables = candidate_cables[
            (
                candidate_cables["SrcTagNorm"].isin(visible_norm_set)
                | candidate_cables["SrcTagNorm"].isin(VALID_CABLE_IDS_NORMALIZED)
            )
            & (
                candidate_cables["DstTagNorm"].isin(visible_norm_set)
                | candidate_cables["DstTagNorm"].isin(VALID_CABLE_IDS_NORMALIZED)
            )
        ].copy()
    else:
        filtered_cables = candidate_cables.copy()

    # Canonicalize tag casing for all rendered edges/nodes.
    filtered_cables["SrcTag"] = filtered_cables["SrcTag"].apply(canonical_display_tag)
    filtered_cables["DstTag"] = filtered_cables["DstTag"].apply(canonical_display_tag)

    candidate_asset_nodes_norm = {
        tag
        for tag in set(filtered_cables["SrcTagNorm"].tolist())
        | set(filtered_cables["DstTagNorm"].tolist())
        if is_asset_tag(tag)
    }
    candidate_asset_nodes_norm.update(
        {tag for tag in broadly_involved_asset_tags_norm if is_asset_tag(tag)}
    )
    if visible_norm_set:
        final_asset_nodes_norm = candidate_asset_nodes_norm.intersection(
            visible_norm_set
        )
        final_asset_nodes_norm.update(
            {tag for tag in expansion_map.keys() if is_asset_tag(tag)}
        )
    else:
        final_asset_nodes_norm = candidate_asset_nodes_norm
    final_nodes_to_render = denormalize_tags(final_asset_nodes_norm)

    # Handle truly empty graph (no nodes to render)
    if not final_nodes_to_render and filtered_cables.empty:
        empty_dot_string = (
            'digraph G { label="No assets found to display."; labelloc="t"; }'
        )
        try:
            dot_source = graphviz.Source(empty_dot_string)
            svg_output = dot_source.pipe(format="svg").decode("utf-8")
            return Response(content=svg_output, media_type="image/svg+xml")
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error rendering empty graph SVG: {e}"
            )

    # graph_assets will contain full details for all `final_nodes_to_render`
    graph_assets = df_assets[df_assets["AssetTag"].isin(final_nodes_to_render)]

    # Call generate_dot_string with the *explicitly requested* nodes to render and their filtered cables
    collapse_value = (collapse_strategy or "none").lower()
    if collapse_value not in COLLAPSE_OPTIONS:
        raise HTTPException(
            status_code=400,
            detail="Invalid collapse strategy. Choose none, protocol, or type.",
        )

    dot_string = generate_dot_string(
        filtered_cables,
        graph_assets,
        final_nodes_to_render,
        selected_node_fields,
        selected_edge_fields,
        color_nodes_by_category,
        color_edges_by_protocol,
        collapse_value,
    )

    # Try rendering the DOT string to SVG
    try:
        dot_source = graphviz.Source(dot_string)  # Create a Graphviz Source object
        svg_output = dot_source.pipe(format="svg").decode(
            "utf-8"
        )  # Render to SVG and decode
        return Response(content=svg_output, media_type="image/svg+xml")  # Return as SVG
    except Exception as e:
        print(f"Error rendering Graphviz DOT to SVG: {e}")
        # If rendering fails, return a 500 error
        raise HTTPException(
            status_code=500, detail=f"Error rendering Graphviz SVG: {e}"
        )


@app.get("/crosspoint/matrix")
async def get_crosspoint_matrix(
    source_tag: str,
    target_tag: str,
    header_fields: Optional[str] = Query(None),
    protocol: Optional[str] = Query(None),
):
    source_norm = normalize_tag_value(source_tag)
    target_norm = normalize_tag_value(target_tag)
    if not source_norm or not target_norm:
        raise HTTPException(
            status_code=400, detail="Source and Target asset tags are required."
        )
    if source_norm not in ALL_KNOWN_TAGS_NORMALIZED:
        raise HTTPException(
            status_code=404, detail=f"Unknown source asset tag: {source_tag}"
        )
    if target_norm not in ALL_KNOWN_TAGS_NORMALIZED:
        raise HTTPException(
            status_code=404, detail=f"Unknown target asset tag: {target_tag}"
        )

    selected_fields = parse_field_selection(
        header_fields, CROSSPOINT_HEADER_FIELDS, CROSSPOINT_DEFAULT_FIELDS
    )
    base_pairs = df_cables[
        (df_cables["SrcTagNorm"] == source_norm)
        & (df_cables["DstTagNorm"] == target_norm)
    ].copy()

    protocol_display_map: Dict[str, str] = {}
    for raw_value in base_pairs["Protocol"]:
        text = format_display_value(raw_value)
        if not text:
            continue
        canon = text.lower()
        if canon not in protocol_display_map:
            protocol_display_map[canon] = text

    selected_protocol = format_display_value(protocol).lower()
    if selected_protocol and selected_protocol not in protocol_display_map:
        protocol_display_map[selected_protocol] = (
            protocol.upper() if protocol else selected_protocol.upper()
        )

    # Prepare canonical port columns for consistent matching
    base_pairs = base_pairs.assign(
        SrcPortSafe=base_pairs["SrcPort"].apply(normalize_port_value),
        DstPortSafe=base_pairs["DstPort"].apply(normalize_port_value),
    )

    row_ports = sorted({value for value in base_pairs["SrcPortSafe"]})
    column_ports = sorted({value for value in base_pairs["DstPortSafe"]})

    row_groups: Dict[str, pd.DataFrame] = {
        str(port): group for port, group in base_pairs.groupby("SrcPortSafe")
    }
    col_groups: Dict[str, pd.DataFrame] = {
        str(port): group for port, group in base_pairs.groupby("DstPortSafe")
    }

    connection_map: Dict[Tuple[str, str], Set[str]] = {}
    for _, row in base_pairs.iterrows():
        key = (row["SrcPortSafe"], row["DstPortSafe"])
        proto = format_display_value(row.get("Protocol"))
        canon_proto = proto.lower() if proto else ""
        if key not in connection_map:
            connection_map[key] = set()
        connection_map[key].add(canon_proto)

    empty_subset = base_pairs.iloc[0:0]
    rows_payload = [
        {
            "port": port,
            "label": build_crosspoint_label(
                port, row_groups.get(port, empty_subset), selected_fields
            ),
        }
        for port in row_ports
    ]
    columns_payload = [
        {
            "port": port,
            "label": build_crosspoint_label(
                port, col_groups.get(port, empty_subset), selected_fields
            ),
        }
        for port in column_ports
    ]

    matrix: List[List[bool]] = []
    if row_ports and column_ports:
        for row_port in row_ports:
            row_values: List[bool] = []
            for col_port in column_ports:
                proto_set = connection_map.get((row_port, col_port), set())
                if not proto_set:
                    row_values.append(False)
                elif not selected_protocol:
                    row_values.append(True)
                else:
                    row_values.append(selected_protocol in proto_set)
            matrix.append(row_values)

    protocol_options = [{"value": "", "label": "All Protocols"}]
    for canon, display in sorted(
        protocol_display_map.items(), key=lambda item: item[1].lower()
    ):
        protocol_options.append(
            {
                "value": canon,
                "label": display,
            }
        )

    return {
        "source_tag": canonical_display_tag(source_tag),
        "target_tag": canonical_display_tag(target_tag),
        "header_fields": selected_fields,
        "protocol": selected_protocol,
        "protocols": protocol_options,
        "rows": rows_payload,
        "columns": columns_payload,
        "matrix": matrix,
    }


# ---------------------------------------------------------------------------
# Dashboard — Route Comparison
# ---------------------------------------------------------------------------

_CUECOMMANDER_BASE: str = os.environ.get(
    "CUECOMMANDER_BASE",
    "http://cumu-g001.local:1880",
).rstrip("/")
_CUECOMMANDER_TIMEOUT_S: int = 5

# Adapter registry: name -> comparison function.
# Each function receives a DataFrame of route cable rows for one device and
# returns {"status", "exceptions", "total_routes_checked"[, "error"]}.
_ROUTE_ADAPTERS: Dict[str, Callable] = {}


def _route_adapter(name: str) -> Callable:
    """Decorator to register a route-comparison adapter."""

    def decorator(fn: Callable) -> Callable:
        _ROUTE_ADAPTERS[name] = fn
        return fn

    return decorator


# Maps normalised asset tag -> adapter type string.
# Add an entry here when a new routing device is commissioned and a
# CueCommander flow exists for it.
_ROUTE_ADAPTER_FOR_ASSET: Dict[str, str] = {
    "2507-0700": "videohub",
    # "ZVKU-A001": excluded — Kramer VS-88DT API makes device unstable
    # "ZVIU-E004": excluded — BMD DeckLink Quad 2 has no viable API
    # Dante audio routing will be handled as a virtual section, not per-asset
}

# Asset tags explicitly excluded from route monitoring.
# These have route cables in the data but no safe/viable API for verification.
_ROUTE_EXCLUDED_ASSETS: Set[str] = {"ZVKU-A001", "ZVIU-E004"}


_NODERED_API_TOKEN: str = os.environ.get("NODERED_API_TOKEN", "vn-api-changeme")


def _fetch_cuecommander_json(path: str) -> Any:
    """GET JSON from CueCommander. Raises on any network or HTTP error."""
    url = _CUECOMMANDER_BASE + path
    req = _urllib_request.Request(url, headers={"Accept": "application/json"})
    with _urllib_request.urlopen(req, timeout=_CUECOMMANDER_TIMEOUT_S) as resp:
        return _json.loads(resp.read().decode())


def _fetch_nodered_json(path: str) -> Any:
    """GET JSON from Node-RED vocalnames API (includes auth token)."""
    url = _CUECOMMANDER_BASE + path
    req = _urllib_request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Api-Token": _NODERED_API_TOKEN,
        },
    )
    with _urllib_request.urlopen(req, timeout=_CUECOMMANDER_TIMEOUT_S) as resp:
        return _json.loads(resp.read().decode())


def _post_nodered_json(path: str, body: Optional[dict] = None) -> Any:
    """POST to Node-RED vocalnames API with auth token. Returns parsed JSON."""
    import urllib.error as _urllib_error

    url = _CUECOMMANDER_BASE + path
    data = _json.dumps(body or {}).encode()
    req = _urllib_request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Api-Token": _NODERED_API_TOKEN,
        },
    )
    with _urllib_request.urlopen(req, timeout=_CUECOMMANDER_TIMEOUT_S) as resp:
        return _json.loads(resp.read().decode())


def _parse_port_number(port_str: Any) -> Optional[int]:
    """
    Extract the port number from strings like 'in_1', 'out_1_HDbT', 'in_01'.
    Splits on '_' and returns the first numeric segment after the prefix.
    """
    if port_str is None:
        return None
    s = str(port_str).strip()
    if not s or s.lower() in ("nan", "none", "nat", ""):
        return None
    parts = s.split("_")
    for part in parts[1:]:  # skip the 'in' / 'out' prefix
        try:
            return int(part)
        except ValueError:
            continue
    return None


@_route_adapter("videohub")
def _videohub_adapter(routes_df: pd.DataFrame) -> dict:
    """
    Compare VideoHub cable records against CueCommander's cross-point state.
    API: GET /api/videohub/crosspoints -> {"crosspoints": [{"input": N, "output": N}]}
    """
    import urllib.error as _urllib_error

    try:
        data = _fetch_cuecommander_json("/api/videohub/crosspoints")
        live_map: Dict[int, int] = {
            cp["output"]: cp["input"] for cp in data.get("crosspoints", [])
        }
    except _urllib_error.HTTPError as exc:
        # Read the JSON body for a specific message (e.g. "Videohub data not available")
        try:
            body = _json.loads(exc.read().decode())
            error_msg = body.get("error", str(exc))
        except Exception:
            error_msg = str(exc)
        return {
            "status": "unavailable",
            "error": error_msg,
            "exceptions": [],
            "total_routes_checked": 0,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "error": str(exc),
            "exceptions": [],
            "total_routes_checked": 0,
        }

    exceptions: List[dict] = []
    for _, row in routes_df.iterrows():
        output_num = _parse_port_number(row.get("DstPort"))
        input_num = _parse_port_number(row.get("SrcPort"))

        if output_num is None:
            exceptions.append(
                {
                    "severity": "warning",
                    "cable_tag": str(row.get("Tag", "")),
                    "asset_tag": str(row.get("SrcTag", "")),
                    "output_port": str(row.get("DstPort", "")),
                    "input_port": str(row.get("SrcPort", "")),
                    "expected_input": input_num,
                    "actual_input": None,
                    "message": f"Cannot parse output port '{row.get('DstPort', '')}' — skipped",
                }
            )
            continue

        live_input = live_map.get(output_num)
        if live_input is None:
            exceptions.append(
                {
                    "severity": "warning",
                    "cable_tag": str(row.get("Tag", "")),
                    "asset_tag": str(row.get("SrcTag", "")),
                    "output_port": str(row.get("DstPort", "")),
                    "input_port": str(row.get("SrcPort", "")),
                    "expected_input": input_num,
                    "actual_input": None,
                    "message": f"Output {output_num}: not present in live routing table",
                }
            )
        elif input_num != live_input:
            exceptions.append(
                {
                    "severity": "warning",
                    "cable_tag": str(row.get("Tag", "")),
                    "asset_tag": str(row.get("SrcTag", "")),
                    "output_port": str(row.get("DstPort", "")),
                    "input_port": str(row.get("SrcPort", "")),
                    "expected_input": input_num,
                    "actual_input": live_input,
                    "message": f"Output {output_num}: expected input {input_num}, live has input {live_input}",
                }
            )

    status = (
        "critical"
        if any(e["severity"] == "critical" for e in exceptions)
        else "warning"
        if exceptions
        else "ok"
    )
    return {
        "status": status,
        "exceptions": exceptions,
        "total_routes_checked": len(routes_df),
    }


def _asset_meta(df_assets: pd.DataFrame, asset_tag: str) -> Dict[str, str]:
    """Return model and usage strings for an asset tag, or empty strings."""
    row = df_assets[df_assets["AssetTagNorm"] == asset_tag.strip().upper()]
    if row.empty:
        return {"model": "", "usage": ""}
    r = row.iloc[0]
    model = str(r.get("Model", "") or "").strip()
    usage = str(r.get("Usage", "") or "").strip()
    return {
        "model": model if model.lower() not in ("nan", "") else "",
        "usage": usage if usage.lower() not in ("nan", "") else "",
    }


@app.get("/dashboard/crosspoint")
def get_dashboard_crosspoint():
    """
    Compare all defined route cables against live routing state from CueCommander.
    Groups route cables by routing device; each device is checked by its registered
    adapter. Devices in _ROUTE_EXCLUDED_ASSETS are silently omitted.
    """
    df_cables = load_cables_data()
    df_assets = load_assets_data()

    route_mask = (df_cables["Type"].astype(str).str.strip().str.lower() == "route") & (
        df_cables["SrcTagNorm"] == df_cables["DstTagNorm"]
    )
    route_df = df_cables[route_mask].copy()

    # Drop excluded assets before building panels
    route_df = route_df[
        ~route_df["SrcTagNorm"].isin({t.upper() for t in _ROUTE_EXCLUDED_ASSETS})
    ]

    if route_df.empty:
        return {
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "status": "ok",
            "message": "No route cables defined",
            "panels": [],
        }

    panels: List[dict] = []
    for asset_norm, group in route_df.groupby("SrcTagNorm"):
        asset_tag = str(group.iloc[0]["SrcTag"])
        meta = _asset_meta(df_assets, asset_tag)
        adapter_type = _ROUTE_ADAPTER_FOR_ASSET.get(str(asset_norm))

        if adapter_type is None:
            panels.append(
                {
                    "asset_tag": asset_tag,
                    **meta,
                    "adapter": None,
                    "status": "pending",
                    "total_routes_defined": len(group),
                    "total_routes_checked": 0,
                    "exceptions": [],
                    "message": f"No monitoring adapter configured for {asset_tag}",
                }
            )
            continue

        adapter_fn = _ROUTE_ADAPTERS.get(adapter_type)
        if adapter_fn is None:
            panels.append(
                {
                    "asset_tag": asset_tag,
                    **meta,
                    "adapter": adapter_type,
                    "status": "pending",
                    "total_routes_defined": len(group),
                    "total_routes_checked": 0,
                    "exceptions": [],
                    "message": f"Adapter '{adapter_type}' not yet implemented",
                }
            )
            continue

        result = adapter_fn(group)
        panels.append(
            {
                "asset_tag": asset_tag,
                **meta,
                "adapter": adapter_type,
                "total_routes_defined": len(group),
                **result,
            }
        )

    statuses = [p["status"] for p in panels]
    if all(s in ("unavailable", "pending") for s in statuses):
        overall = "unavailable"
    elif "critical" in statuses:
        overall = "critical"
    elif "warning" in statuses:
        overall = "warning"
    else:
        overall = "ok"

    return {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "status": overall,
        "panels": panels,
    }


@app.get("/api/network/targets")
def get_network_targets():
    """
    Returns all Monitor=Yes rows from the network table that have an IP address.
    This is the canonical source of truth for monitored nodes.  The webapp
    backend pushes this list to CueCommander (POST /api/network/targets) each
    time the dashboard is fetched or data is reloaded — CueCommander does not
    call this endpoint directly.
    """
    df = load_network_data()
    targets = _build_network_targets(df)
    return {
        "targets": targets,
        "total": len(targets),
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def _push_network_targets_to_cuecommander(targets: List[dict]) -> None:
    """Push Monitor=Yes target list to CueCommander. Fire-and-forget; errors are silently ignored."""
    try:
        _post_nodered_json("/api/network/targets", {"targets": targets})
    except Exception:
        pass


def _build_network_targets(df_net: pd.DataFrame) -> List[dict]:
    """Extract Monitor=Yes rows with IPs from a loaded network DataFrame."""
    targets: List[dict] = []
    for _, row in df_net[df_net["Monitor"] == "Yes"].iterrows():
        ip = str(row.get("IP", "") or "").strip()
        if not ip:
            continue
        tag = str(row.get("AssetTag", "") or "").strip()
        nic = str(row.get("NIC", "") or "").strip()
        usage = str(row.get("Usage", "") or "").strip()
        targets.append(
            {
                "asset_tag": tag,
                "nic": nic or None,
                "ip": ip,
                "usage": usage or None,
                "related_issue_ids": _parse_issue_ids(row.get("RelatedIssueId")),
            }
        )
    return targets


@app.get("/dashboard/network")
def get_dashboard_network():
    """
    Network monitoring panel for the operational dashboard.

    Config exceptions (Monitor=Yes but no IP) are derived from the network table.

    Ping results come from CueCommander GET /api/network/status.
    Returns status='unavailable' for that section if CueCommander is unreachable.
    """
    df_net = load_network_data()
    df_assets = load_assets_data()

    # Push current target list to CueCommander so it knows what to ping.
    # Webapp is the source of truth for network targets; CC never calls us.
    _push_network_targets_to_cuecommander(_build_network_targets(df_net))

    # --- Config exceptions: Monitor=Yes rows with no IP ---
    monitor_rows = df_net[df_net["Monitor"] == "Yes"]
    no_ip_rows = monitor_rows[monitor_rows["IP"] == ""]

    config_exceptions: List[dict] = []
    for _, r in no_ip_rows.iterrows():
        tag = str(r.get("AssetTag", "") or "").strip()
        # Look up model/usage from asset table for context
        meta = _asset_meta(df_assets, tag)
        config_exceptions.append(
            {
                "asset_tag": tag,
                "nic": str(r.get("NIC", "") or "").strip() or None,
                "model": meta["model"],
                "usage": meta["usage"] or str(r.get("Usage", "") or "").strip(),
                "severity": "warning",
                "issue": "Monitor=Yes but no IP configured",
            }
        )

    # --- Ping results from CueCommander ---
    ping_panel: dict
    try:
        raw = _fetch_cuecommander_json("/api/network/status")

        # Enrich each result with asset name from assets table
        # CueCommander shape: { asset_tag, nic, ip, packets_sent, packets_received,
        #                       avg_ms, loss_pct, status }
        # status values: "ok" | "high_latency" | "down" | "unknown"
        results = raw.get("results", [])
        for item in results:
            tag = str(item.get("asset_tag", "") or "").strip()
            meta = _asset_meta(df_assets, tag)
            item.setdefault("model", meta["model"])
            item.setdefault("usage", meta["usage"])

        down = [r for r in results if r.get("status") == "down"]
        hi_lat = [r for r in results if r.get("status") == "high_latency"]

        ping_status = "critical" if down else "warning" if hi_lat else "ok"
        ping_panel = {
            "status": ping_status,
            "total_monitored": len(results),
            "down_count": len(down),
            "high_latency_count": len(hi_lat),
            "results": results,
            "generated_at": raw.get("generated_at"),
        }
    except Exception as exc:
        ping_panel = {
            "status": "unavailable",
            "error": str(exc),
            "exceptions": [],
            "total_monitored": 0,
        }

    # Overall status
    statuses = [
        "warning" if config_exceptions else "ok",
        ping_panel["status"],
    ]
    overall = (
        "unavailable"
        if all(s == "unavailable" for s in statuses)
        else "critical"
        if "critical" in statuses
        else "warning"
        if "warning" in statuses
        else "ok"
    )

    # Flat top-level keys for test compatibility
    ping_results = ping_panel.get("results") if ping_panel["status"] != "unavailable" else None
    ping_error = ping_panel.get("error") if ping_panel["status"] == "unavailable" else None

    response: Dict[str, Any] = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "status": overall,
        "config_exceptions": config_exceptions,
        "ping": ping_panel,
        "ping_results": ping_results,
    }
    if ping_error is not None:
        response["ping_error"] = ping_error
    return response


# ---------------------------------------------------------------------------
# Dashboard — Klang Mix Consistency
# ---------------------------------------------------------------------------


@app.get("/dashboard/klang")
def get_dashboard_klang():
    """
    Klang mix-consistency panel for the operational dashboard.

    Proxies to Node-RED vocalnames API:
      GET /api/klang/status          — sweep state + result availability
      GET /api/klang/reportmixvariances — stored variance report (if available)

    The panel always returns immediately. If no results exist yet, status is
    'unavailable'. The frontend Rebuild button triggers POST /dashboard/klang/buildconsensus.
    """
    try:
        status_data = _fetch_nodered_json("/api/klang/status")
    except Exception as exc:
        return {
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "status": "unavailable",
            "error": f"Node-RED unreachable: {exc}",
            "sweep": None,
            "variances": None,
        }

    sweep_panel = {
        "active": status_data.get("sweep_active", False),
        "started_at": status_data.get("sweep_started_at"),
        "mix_current": status_data.get("sweep_mix_current", 0),
    }

    variances_panel = None
    mixes_panel = None
    panel_status = "unavailable"

    if status_data.get("results_available"):
        try:
            var_data = _fetch_nodered_json("/api/klang/reportmixvariances")
            total = var_data.get("total_variances", 0)
            criticals = [
                v
                for v in var_data.get("variances", [])
                if v.get("severity") == "critical"
            ]
            panel_status = (
                "critical" if criticals else ("warning" if total > 0 else "ok")
            )
            variances_panel = {
                "generated_at": var_data.get("generated_at"),
                "total_variances": total,
                "critical_count": len(criticals),
                "variances": var_data.get("variances", []),
                "note": var_data.get("note"),
            }
        except Exception as exc:
            panel_status = "unavailable"
            variances_panel = {"error": str(exc)}

        try:
            mm_data = _fetch_nodered_json("/api/klang/reportmastermix")
            if mm_data.get("mixes"):
                mixes_panel = {
                    "mix_count": mm_data.get("mix_count", 0),
                    "phase": mm_data.get("phase"),
                    "mixes": mm_data["mixes"],
                }
        except Exception:
            pass
    elif status_data.get("sweep_active"):
        panel_status = "pending"

    return {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "status": panel_status,
        "sweep": sweep_panel,
        "variances": variances_panel,
        "mixes": mixes_panel,
    }


@app.post("/dashboard/klang/setvariance")
def post_dashboard_klang_setvariance(body: dict):
    """Proxy POST /api/klang/setvariance to Node-RED."""
    try:
        result = _post_nodered_json("/api/klang/setvariance", body)
        return result
    except Exception as exc:
        return {"ok": False, "error": f"Node-RED unreachable: {exc}"}


@app.post("/dashboard/klang/buildconsensus")
def post_dashboard_klang_buildconsensus():
    """
    Trigger a Klang sweep + consensus build.
    Proxies POST /api/klang/buildconsensus to Node-RED.
    Returns 202 with estimated duration, or 409 if sweep already active.
    """
    try:
        result = _post_nodered_json("/api/klang/buildconsensus")
        return result
    except Exception as exc:
        import urllib.error as _ue

        if isinstance(exc, _ue.HTTPError) and exc.code == 409:
            body = _json.loads(exc.read().decode())
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=409, content=body)
        return {"ok": False, "error": f"Node-RED unreachable: {exc}"}


MANUALS_BASE_URL = os.environ.get("MANUALS_BASE_URL", "http://localhost:80")
_ASSET_TAG_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


@app.get("/manuals/{asset_tag}")
def get_manuals(asset_tag: str):
    """Proxy manuals lookup to the media_arts_home server."""
    if not _ASSET_TAG_RE.match(asset_tag):
        raise HTTPException(status_code=400, detail="Invalid asset tag")

    base = MANUALS_BASE_URL.rstrip("/")
    url = f"{base}/api/manuals/{asset_tag}"
    try:
        with _urllib_request.urlopen(url, timeout=5) as resp:
            data = _json.loads(resp.read().decode())

        # Rewrite relative paths to absolute URLs, rejecting anything that
        # isn't a simple absolute path (no protocol-relative or external URLs).
        for manual in data.get("manuals", []):
            raw = manual.get("url", "")
            if raw.startswith("/") and not raw.startswith("//"):
                manual["url"] = f"{base}{raw}"
            elif not raw.startswith("http"):
                manual["url"] = ""  # drop anything unexpected

        return data
    except _urllib_error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Manuals service unreachable: {exc}")


# ── Glossary ──────────────────────────────────────────────────────────────────


@app.get("/glossary/topics")
async def get_glossary_topics():
    """Returns all unique glossary topics, sorted case-insensitively."""
    return _avl_data_get("/glossary/topics")


@app.get("/glossary")
async def get_glossary(topic: Optional[str] = None):
    """Returns glossary entries from avl_data, optionally filtered by topic."""
    path = f"/glossary?topic={topic}" if topic else "/glossary"
    rows = _avl_data_get(path)
    return [
        {
            "topic":      r.get("topic") or "",
            "term":       r.get("term") or "",
            "sense":      r.get("sense") or "",
            "see_also":   r.get("see_also") or "",
            "definition": r.get("definition") or "",
        }
        for r in rows
    ]
