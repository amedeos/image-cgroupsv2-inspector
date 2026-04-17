"""Tests for the HTML report context builder."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.html_reporter import build_report_context, generate_html_report, render_html_report

FIXTURE_CSV = Path("tests/fixtures/sample_report.csv")
SNAPSHOT_PATH = Path("tests/fixtures/expected_context.json")

CSV_HEADER = (
    "source,container_name,namespace,object_type,object_name,"
    "registry_org,registry_repo,image_name,image_id,"
    "java_binary,java_version,java_cgroup_v2_compatible,"
    "node_binary,node_version,node_cgroup_v2_compatible,"
    "dotnet_binary,dotnet_version,dotnet_cgroup_v2_compatible,"
    "go_binary,go_version,go_cgroup_v2_compatible,go_modules,"
    "deep_scan_match,deep_scan_confidence,deep_scan_sources,"
    "deep_scan_patterns,deep_scan_v2_aware,analysis_error\n"
)

FIXED_TS = "2026-04-17T12:00:00"


def _ctx() -> dict:
    return build_report_context(
        csv_path=FIXTURE_CSV,
        tool_version="2.0.0",
        target="sample-target",
        generated_at=FIXED_TS,
    )


def test_build_context_snapshot():
    ctx = _ctx()
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT_PATH.write_text(json.dumps(ctx, indent=2, sort_keys=True) + "\n")
        return
    expected = json.loads(SNAPSHOT_PATH.read_text())
    assert ctx == expected


def test_build_context_aggregates_by_image_name():
    ctx = _ctx()
    java_old = next(img for img in ctx["images"] if img["image_name"] == "registry.example/myorg/java-old:v1")
    assert java_old["used_by_count"] == 3
    assert len(java_old["consumers"]) == 3


def test_build_context_separates_errors():
    ctx = _ctx()
    error_names = [e["image_name"] for e in ctx["errors"]]
    image_names = [i["image_name"] for i in ctx["images"]]

    assert "registry.example/myorg/broken:v1" in error_names
    assert "registry.example/myorg/broken:v1" not in image_names
    assert len(ctx["errors"]) == 1
    assert "manifest unknown" in ctx["errors"][0]["error"]


@pytest.mark.parametrize(
    ("image_name", "expected_status"),
    [
        ("registry.example/myorg/java-app:v1", "compatible"),
        ("registry.example/myorg/java-old:v1", "incompatible"),
        ("registry.example/myorg/node-new:v1", "compatible"),
        ("registry.example/myorg/dotnet:v1", "compatible"),
        ("registry.example/myorg/go-modern:v1", "compatible"),
        ("registry.example/myorg/go-old:v1", "incompatible"),
        ("registry.example/myorg/go-review:v1", "needs_review"),
        ("registry.example/myorg/ds-v1only:v1", "incompatible"),
        ("registry.example/myorg/ds-v2aware:v1", "compatible"),
        ("registry.example/myorg/java-unknown:v1", "needs_review"),
        ("registry.example/myorg/nginx-base:v1", "not_applicable"),
    ],
)
def test_build_context_overall_status(image_name: str, expected_status: str):
    ctx = _ctx()
    img = next(i for i in ctx["images"] if i["image_name"] == image_name)
    assert img["overall_status"] == expected_status


def test_build_context_target_derivation(tmp_path: Path):
    csv_with_ts = tmp_path / "myorg-20260417-111443.csv"
    csv_with_ts.write_text(CSV_HEADER)
    ctx = build_report_context(csv_path=csv_with_ts, tool_version="2.0.0", generated_at=FIXED_TS)
    assert ctx["metadata"]["target"] == "myorg"

    csv_plain = tmp_path / "sample_report.csv"
    csv_plain.write_text(CSV_HEADER)
    ctx2 = build_report_context(csv_path=csv_plain, tool_version="2.0.0", generated_at=FIXED_TS)
    assert ctx2["metadata"]["target"] == "sample_report"


def test_build_context_source_mode(tmp_path: Path):
    ctx_mixed = _ctx()
    assert ctx_mixed["metadata"]["source_mode"] == "mixed"

    os_csv = tmp_path / "os_only.csv"
    os_csv.write_text(
        CSV_HEADER
        + "openshift,c,ns,Deployment,d,,,img:v1,sha256:x,"
        + "None,None,N/A,None,None,N/A,None,None,N/A,None,None,N/A,None,false,,,,,\n"
    )
    ctx_os = build_report_context(csv_path=os_csv, tool_version="2.0.0", generated_at=FIXED_TS)
    assert ctx_os["metadata"]["source_mode"] == "openshift"

    reg_csv = tmp_path / "reg_only.csv"
    reg_csv.write_text(
        CSV_HEADER
        + "registry,,,,,org,repo,img:v1,sha256:x,"
        + "None,None,N/A,None,None,N/A,None,None,N/A,None,None,N/A,None,false,,,,,\n"
    )
    ctx_reg = build_report_context(csv_path=reg_csv, tool_version="2.0.0", generated_at=FIXED_TS)
    assert ctx_reg["metadata"]["source_mode"] == "registry"


def test_build_context_empty_csv(tmp_path: Path):
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text(CSV_HEADER)
    ctx = build_report_context(csv_path=empty_csv, tool_version="2.0.0", generated_at=FIXED_TS)
    assert ctx["summary"]["total_images"] == 0
    assert ctx["summary"]["total_rows"] == 0
    assert ctx["metadata"]["source_mode"] == "unknown"
    assert ctx["images"] == []
    assert ctx["errors"] == []


# ---------------------------------------------------------------------------
# HTML rendering tests
# ---------------------------------------------------------------------------


def test_render_html_contains_key_markers():
    ctx = _ctx()
    html = render_html_report(ctx)

    assert '<table id="images-table"' in html
    assert '<table id="errors-table"' in html
    assert "sample-target" in html
    assert "java-app" in html
    assert "java-old" in html
    assert "ds-v1only" in html
    assert "manifest unknown" in html
    assert "dataTables_wrapper" in html
    assert "jQuery" in html
    assert "status-not_applicable" in html


def test_render_html_empty_csv(tmp_path: Path):
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text(CSV_HEADER)
    ctx = build_report_context(csv_path=empty_csv, tool_version="2.0.0", generated_at=FIXED_TS)
    html = render_html_report(ctx)

    assert "No errors." in html
    assert "Images (0)" in html


def test_build_context_not_applicable_for_runtimeless_image():
    """An image with no detected runtime and no deep-scan match
    is classified as 'not_applicable', not 'unknown'."""
    ctx = build_report_context(
        csv_path=Path("tests/fixtures/sample_report.csv"),
        tool_version="2.0.0",
        target="sample-target",
        generated_at="2026-04-17T12:00:00",
    )
    nginx = next(img for img in ctx["images"] if img["image_name"] == "registry.example/myorg/nginx-base:v1")
    assert nginx["overall_status"] == "not_applicable"
    assert nginx["java"]["compatible"] == "N/A"
    assert nginx["node"]["compatible"] == "N/A"
    assert nginx["dotnet"]["compatible"] == "N/A"
    assert nginx["go"]["compatible"] == "N/A"
    assert nginx["deep_scan"]["match"] is False


def _render_fixture_html():
    ctx = build_report_context(
        csv_path=FIXTURE_CSV,
        tool_version="2.0.0",
        target="sample-target",
        generated_at=FIXED_TS,
    )
    return render_html_report(ctx)


# ---------------------------------------------------------------------------
# Pie chart context tests
# ---------------------------------------------------------------------------


def test_pie_chart_slices_present_and_nonzero_only():
    ctx = _ctx()
    slices = ctx["summary"]["pie_chart_slices"]
    assert len(slices) == 4
    for s in slices:
        assert s["count"] > 0
        assert 0 < s["percentage"] <= 100
        assert s["path"].startswith("M 100,100 L ") or "A 80,80" in s["path"]
        assert s["color"].startswith("#")
        assert set(s.keys()) == {"status", "count", "percentage", "path", "color"}


def test_pie_chart_percentages_sum_to_100():
    ctx = _ctx()
    slices = ctx["summary"]["pie_chart_slices"]
    assert abs(sum(s["percentage"] for s in slices) - 100.0) < 0.05


def test_pie_chart_helper_single_slice_full_circle():
    from src.html_reporter import _build_pie_chart_slices

    slices = _build_pie_chart_slices({"compatible": 5, "incompatible": 0, "needs_review": 0, "not_applicable": 0})
    assert len(slices) == 1
    assert slices[0]["percentage"] == 100.0
    assert "A 80,80" in slices[0]["path"]
    assert slices[0]["path"].count("A 80,80") == 2


def test_pie_chart_helper_empty():
    from src.html_reporter import _build_pie_chart_slices

    assert _build_pie_chart_slices({}) == []
    assert _build_pie_chart_slices({"compatible": 0, "incompatible": 0}) == []


def test_pie_chart_helper_unknown_status_gets_fallback_color():
    from src.html_reporter import _DEFAULT_STATUS_COLOR, _build_pie_chart_slices

    slices = _build_pie_chart_slices({"future_status": 1, "compatible": 1})
    colors = {s["status"]: s["color"] for s in slices}
    assert colors["future_status"] == _DEFAULT_STATUS_COLOR
    assert colors["compatible"] == "#28a745"


# ---------------------------------------------------------------------------
# HTML marker tests for interactive features
# ---------------------------------------------------------------------------


def test_render_html_has_pie_chart():
    html = _render_fixture_html()
    assert '<svg viewBox="0 0 200 200"' in html
    assert 'class="pie-slice"' in html
    assert "chart-legend" in html
    for status in ("compatible", "incompatible", "needs_review", "not_applicable"):
        assert 'data-filter-status="' + status + '"' in html


def test_render_html_has_filter_banner():
    html = _render_fixture_html()
    assert 'id="filter-banner"' in html
    assert 'id="clear-filters"' in html
    assert 'style="display: none;"' in html


def test_render_html_status_cards_are_clickable():
    html = _render_fixture_html()
    for status in ("compatible", "incompatible", "needs_review", "not_applicable"):
        assert 'data-filter-status="' + status + '"' in html
    assert "total-card" in html
    assert 'data-filter-clear="true"' in html


def test_generate_html_report_writes_file(tmp_path: Path):
    out = tmp_path / "report.html"
    generate_html_report(
        csv_path=FIXTURE_CSV,
        html_path=out,
        tool_version="2.0.0",
        target="test-target",
        generated_at=FIXED_TS,
    )
    assert out.exists()
    content = out.read_text()
    assert len(content) > 1024
    assert content.startswith("<!DOCTYPE html>")


def test_generate_html_report_creates_parent_dirs(tmp_path: Path):
    out = tmp_path / "nested" / "deep" / "r.html"
    generate_html_report(
        csv_path=FIXTURE_CSV,
        html_path=out,
        tool_version="2.0.0",
        target="test-target",
        generated_at=FIXED_TS,
    )
    assert out.exists()
    assert out.read_text().startswith("<!DOCTYPE html>")
