"""Pure data aggregation for the HTML report: reads the tool CSV and returns a structured dict."""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

CSV_TIMESTAMP_SUFFIX_RE = re.compile(r"-\d{8}-\d{6}$")

_RUNTIMES = ("java", "node", "dotnet", "go")


def _derive_target(csv_path: Path) -> str:
    stem = csv_path.stem
    return CSV_TIMESTAMP_SUFFIX_RE.sub("", stem)


def _parse_bool_field(value: str) -> bool:
    return value.strip().lower() == "true"


def _build_consumer(row: dict) -> dict:
    return {
        "source": row.get("source", ""),
        "namespace": row.get("namespace", ""),
        "object_type": row.get("object_type", ""),
        "object_name": row.get("object_name", ""),
        "container_name": row.get("container_name", ""),
        "registry_org": row.get("registry_org", ""),
        "registry_repo": row.get("registry_repo", ""),
    }


def _runtime_fields(rows: list[dict], runtime: str) -> dict:
    binary_key = f"{runtime}_binary"
    version_key = f"{runtime}_version"
    compat_key = f"{runtime}_cgroup_v2_compatible"

    for row in rows:
        val = row.get(binary_key, "")
        if val and val != "None":
            result = {
                "binary": row.get(binary_key, ""),
                "version": row.get(version_key, ""),
                "compatible": row.get(compat_key, ""),
            }
            if runtime == "go":
                result["modules"] = row.get("go_modules", "")
            return result

    result = {
        "binary": "None",
        "version": "None",
        "compatible": "N/A",
    }
    if runtime == "go":
        result["modules"] = "None"
    return result


def _deep_scan_fields(rows: list[dict]) -> dict:
    for row in rows:
        if _parse_bool_field(row.get("deep_scan_match", "")):
            sources_raw = row.get("deep_scan_sources", "")
            patterns_raw = row.get("deep_scan_patterns", "")
            v2_raw = row.get("deep_scan_v2_aware", "")
            return {
                "match": True,
                "confidence": row.get("deep_scan_confidence", ""),
                "sources": [s for s in sources_raw.split("|") if s] if sources_raw else [],
                "patterns": [p for p in patterns_raw.split("|") if p] if patterns_raw else [],
                "v2_aware": _parse_bool_field(v2_raw),
            }

    return {
        "match": False,
        "confidence": "",
        "sources": [],
        "patterns": [],
        "v2_aware": None,
    }


def _compute_overall_status(runtime_data: dict, deep_scan_data: dict) -> str:
    compatibles = [runtime_data[rt]["compatible"] for rt in _RUNTIMES]

    has_no = any(c == "No" for c in compatibles)
    has_deep_v1_only = deep_scan_data["match"] and deep_scan_data["v2_aware"] is False
    has_needs_review = any(c in ("Needs Review", "Unknown") for c in compatibles)
    has_yes = any(c == "Yes" for c in compatibles)

    if has_no or has_deep_v1_only:
        return "incompatible"
    if has_needs_review:
        return "needs_review"
    if has_yes:
        return "compatible"
    return "unknown"


def _compute_source_mode(sources: set[str]) -> str:
    if not sources:
        return "unknown"
    if sources == {"openshift"}:
        return "openshift"
    if sources == {"registry"}:
        return "registry"
    return "mixed"


def build_report_context(
    csv_path: Path,
    tool_version: str,
    target: str | None = None,
    generated_at: str | None = None,
) -> dict:
    """Read the CSV produced by the tool and return a structured dict for HTML rendering.

    Pure function; no side effects other than reading the input file.
    """
    if target is None:
        target = _derive_target(csv_path)
    if generated_at is None:
        generated_at = datetime.now().isoformat(timespec="seconds")

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    error_rows: dict[str, list[dict]] = {}
    image_rows: dict[str, list[dict]] = {}
    sources: set[str] = set()

    for row in rows:
        if row.get("analysis_error", "").strip():
            error_rows.setdefault(row["image_name"], []).append(row)
        else:
            image_rows.setdefault(row["image_name"], []).append(row)
            sources.add(row.get("source", ""))

    images = []
    for img_name in sorted(image_rows):
        img_group = image_rows[img_name]
        runtime_data = {rt: _runtime_fields(img_group, rt) for rt in _RUNTIMES}
        deep_scan_data = _deep_scan_fields(img_group)
        overall_status = _compute_overall_status(runtime_data, deep_scan_data)
        consumers = [_build_consumer(r) for r in img_group]

        entry = {
            "image_name": img_name,
            "image_id": img_group[0].get("image_id", ""),
            "used_by_count": len(consumers),
            "consumers": consumers,
            **runtime_data,
            "deep_scan": deep_scan_data,
            "overall_status": overall_status,
        }
        images.append(entry)

    errors = []
    for img_name in sorted(error_rows):
        err_group = error_rows[img_name]
        errors.append(
            {
                "image_name": img_name,
                "error": err_group[0].get("analysis_error", ""),
                "consumers": [_build_consumer(r) for r in err_group],
            }
        )

    by_overall = {"compatible": 0, "incompatible": 0, "needs_review": 0, "unknown": 0}
    for img in images:
        by_overall[img["overall_status"]] += 1

    by_compat = {
        "java": {"yes": 0, "no": 0, "unknown": 0, "na": 0},
        "node": {"yes": 0, "no": 0, "unknown": 0, "na": 0},
        "dotnet": {"yes": 0, "no": 0, "unknown": 0, "na": 0},
        "go": {"yes": 0, "no": 0, "needs_review": 0, "none": 0},
    }
    for img in images:
        for rt in _RUNTIMES:
            compat_val = img[rt]["compatible"]
            if rt == "go":
                mapping = {"Yes": "yes", "No": "no", "Needs Review": "needs_review"}
                key = mapping.get(compat_val, "none")
            else:
                mapping = {"Yes": "yes", "No": "no", "Unknown": "unknown"}
                key = mapping.get(compat_val, "na")
            by_compat[rt][key] += 1

    ds_matches = [img for img in images if img["deep_scan"]["match"]]
    ds_enabled = any(row.get("deep_scan_match", "").strip() for row in rows)
    ds_v1_only = sum(1 for img in ds_matches if img["deep_scan"]["v2_aware"] is False)
    ds_v2_aware = sum(1 for img in ds_matches if img["deep_scan"]["v2_aware"] is True)
    ds_by_conf = {"high": 0, "medium": 0, "low": 0}
    for img in ds_matches:
        conf = img["deep_scan"]["confidence"].lower()
        if conf in ds_by_conf:
            ds_by_conf[conf] += 1

    unique_image_names = {img["image_name"] for img in images}
    total_error_rows = sum(len(g) for g in error_rows.values())

    return {
        "metadata": {
            "target": target,
            "generated_at": generated_at,
            "tool_version": tool_version,
            "csv_filename": csv_path.name,
            "source_mode": _compute_source_mode(sources),
        },
        "summary": {
            "total_images": len(unique_image_names),
            "total_rows": len(rows),
            "with_errors": total_error_rows,
            "by_overall_status": by_overall,
            "by_compatibility": by_compat,
            "deep_scan": {
                "enabled": ds_enabled,
                "matches": len(ds_matches),
                "v1_only": ds_v1_only,
                "v2_aware": ds_v2_aware,
                "by_confidence": ds_by_conf,
            },
        },
        "images": images,
        "errors": errors,
    }
