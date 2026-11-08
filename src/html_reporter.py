"""Data aggregation and HTML rendering for the cgroup v2 compatibility report."""

from __future__ import annotations

import csv
import math
import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

CSV_TIMESTAMP_SUFFIX_RE = re.compile(r"-\d{8}-\d{6}$")

_RUNTIMES = ("java", "node", "dotnet", "go")

# Colors for pie chart slices and status-based UI styling. Keys should match
# the values produced by the overall_status classifier. If a new status is
# introduced in the future, add it here; if missing, _DEFAULT_STATUS_COLOR
# is used as a neutral fallback so the chart still renders.
STATUS_COLORS = {
    "compatible": "#28a745",
    "incompatible": "#dc3545",
    "needs_review": "#ffc107",
    "not_applicable": "#6c757d",
}
_DEFAULT_STATUS_COLOR = "#adb5bd"


def _build_pie_chart_slices(by_status: dict[str, int]) -> list[dict]:
    """Compute inline-SVG slice data for the overall-status pie chart.

    Args:
        by_status: mapping of status name to image count (any subset of
            STATUS_COLORS keys, plus potentially future unknown keys).

    Returns:
        List of slice dicts, one per non-zero bucket, ordered as the input
        dict iterates. Zero-count buckets are omitted. Returns [] when
        total is zero.

    Each slice dict has:
        status:      str — bucket name
        count:       int — raw count
        percentage:  float — rounded to 2 decimals
        path:        str — SVG path string drawing the slice against a
                     circle centered at (100, 100) with radius 80
        color:       str — hex color from STATUS_COLORS (or default)

    Special cases:
        - Single non-zero slice: path is a full circle (two 180° arcs)
          since a degenerate 0-length arc is not valid SVG.
    """
    total = sum(by_status.values())
    if total == 0:
        return []

    cx, cy, r = 100, 100, 80
    nonzero = [(status, count) for status, count in by_status.items() if count > 0]

    if len(nonzero) == 1:
        status, count = nonzero[0]
        path = f"M {cx},{cy - r} A {r},{r} 0 1,1 {cx},{cy + r} A {r},{r} 0 1,1 {cx},{cy - r} Z"
        return [
            {
                "status": status,
                "count": count,
                "percentage": 100.0,
                "path": path,
                "color": STATUS_COLORS.get(status, _DEFAULT_STATUS_COLOR),
            }
        ]

    slices = []
    start_angle = -math.pi / 2

    for status, count in nonzero:
        fraction = count / total
        angle = 2 * math.pi * fraction
        end_angle = start_angle + angle

        x1 = cx + r * math.cos(start_angle)
        y1 = cy + r * math.sin(start_angle)
        x2 = cx + r * math.cos(end_angle)
        y2 = cy + r * math.sin(end_angle)

        large_arc = 1 if angle > math.pi else 0
        path = f"M {cx},{cy} L {x1:.3f},{y1:.3f} A {r},{r} 0 {large_arc},1 {x2:.3f},{y2:.3f} Z"

        slices.append(
            {
                "status": status,
                "count": count,
                "percentage": round(100 * count / total, 2),
                "path": path,
                "color": STATUS_COLORS.get(status, _DEFAULT_STATUS_COLOR),
            }
        )
        start_angle = end_angle

    return slices


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


# Recognised runtime compatibility values and the bucket each one feeds, for
# both the overall status and the "By runtime" counts. Anything else (N/A,
# empty, malformed) is not counted. The template builds its click filters from
# this map (exact match on hidden raw-value columns), so a clicked cell always
# shows exactly its count. The template renders one column per bucket.
_COMPAT_BUCKETS = {"Yes": "yes", "No": "no", "Unknown": "needs_review", "Needs Review": "needs_review"}


def _compute_overall_status(runtime_data: dict, deep_scan_data: dict) -> str:
    buckets = {_COMPAT_BUCKETS.get(runtime_data[rt]["compatible"]) for rt in _RUNTIMES}
    has_deep_v1_only = deep_scan_data["match"] and deep_scan_data["v2_aware"] is False

    if "no" in buckets or has_deep_v1_only:
        return "incompatible"
    if "needs_review" in buckets:
        return "needs_review"
    if "yes" in buckets:
        return "compatible"
    return "not_applicable"


_STATUS_BUCKETS = ("compatible", "incompatible", "needs_review", "not_applicable")

_GROUP_FIELDS = ("namespace", "registry_org", "registry_repo")


def _add_to_group(groups: dict[str, dict[str, int]], values: list[str], status: str) -> None:
    for val in values:
        if val not in groups:
            groups[val] = {s: 0 for s in _STATUS_BUCKETS}
        groups[val][status] += 1


def _sorted_groups(groups: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Most incompatible first, then most needs-review, then by name."""
    return dict(sorted(groups.items(), key=lambda kv: (-kv[1]["incompatible"], -kv[1]["needs_review"], kv[0])))


def _compute_source_mode(sources: set[str]) -> str:
    if not sources:
        return "unknown"
    if sources == {"openshift"}:
        return "openshift"
    if sources == {"quay"}:
        return "quay"
    if sources == {"jfrog"}:
        return "jfrog"
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
    by_group: dict[str, dict[str, dict[str, int]]] = {f: {} for f in _GROUP_FIELDS}

    for img_name in sorted(image_rows):
        img_group = image_rows[img_name]
        runtime_data = {rt: _runtime_fields(img_group, rt) for rt in _RUNTIMES}
        deep_scan_data = _deep_scan_fields(img_group)
        overall_status = _compute_overall_status(runtime_data, deep_scan_data)
        consumers = [_build_consumer(r) for r in img_group]

        # Split on "|" like the template's hidden-column filter, so a group's
        # count and the rows its click shows always agree.
        group_vals = {f: sorted({v for c in consumers for v in c[f].split("|") if v}) for f in _GROUP_FIELDS}
        for field, vals in group_vals.items():
            _add_to_group(by_group[field], vals, overall_status)

        entry = {
            "image_name": img_name,
            "image_id": img_group[0].get("image_id", ""),
            "used_by_count": len(consumers),
            "consumers": consumers,
            "namespace_values": "|".join(group_vals["namespace"]),
            "registry_org_values": "|".join(group_vals["registry_org"]),
            "registry_repo_values": "|".join(group_vals["registry_repo"]),
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

    by_overall = {s: 0 for s in _STATUS_BUCKETS}
    for img in images:
        by_overall[img["overall_status"]] += 1

    by_compat = {rt: {b: 0 for b in dict.fromkeys(_COMPAT_BUCKETS.values())} for rt in _RUNTIMES}
    for img in images:
        for rt in _RUNTIMES:
            bucket = _COMPAT_BUCKETS.get(img[rt]["compatible"])
            if bucket is not None:
                by_compat[rt][bucket] += 1

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

    summary = {
        "total_images": len(unique_image_names),
        "total_rows": len(rows),
        "with_errors": total_error_rows,
        "by_overall_status": by_overall,
        "by_compatibility": by_compat,
        "by_namespace": _sorted_groups(by_group["namespace"]),
        "by_registry_org": _sorted_groups(by_group["registry_org"]),
        "by_registry_repo": _sorted_groups(by_group["registry_repo"]),
        "deep_scan": {
            "enabled": ds_enabled,
            "matches": len(ds_matches),
            "v1_only": ds_v1_only,
            "v2_aware": ds_v2_aware,
            "by_confidence": ds_by_conf,
        },
    }
    summary["pie_chart_slices"] = _build_pie_chart_slices(summary["by_overall_status"])

    return {
        "metadata": {
            "target": target,
            "generated_at": generated_at,
            "tool_version": tool_version,
            "csv_filename": csv_path.name,
            "source_mode": _compute_source_mode(sources),
        },
        "summary": summary,
        "images": images,
        "errors": errors,
        "compat_buckets": _COMPAT_BUCKETS,
    }


def render_html_report(context: dict) -> str:
    """Apply the Jinja2 template to the context and return HTML as a string.

    Template file is ``src/templates/report.html.j2``.  Assets in
    ``src/templates/assets/`` are inlined via ``{% include %}``.
    """
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report.html.j2")
    return template.render(context)


def generate_html_report(
    csv_path: Path,
    html_path: Path,
    tool_version: str,
    target: str | None = None,
    generated_at: str | None = None,
) -> None:
    """Build context from CSV, render to HTML, and write to *html_path*."""
    context = build_report_context(csv_path, tool_version, target, generated_at)
    html = render_html_report(context)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html)
