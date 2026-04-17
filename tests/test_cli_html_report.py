"""Test CLI integration for --html-report flag."""

import importlib.machinery
import importlib.util
import logging
import subprocess
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).parent.parent / "image-cgroupsv2-inspector"


def _load_inspector_module():
    loader = importlib.machinery.SourceFileLoader("inspector_main", str(_SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("inspector_main", loader, origin=str(_SCRIPT_PATH))
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(_SCRIPT_PATH)
    spec.loader.exec_module(mod)
    return mod


def test_html_report_flag_in_help():
    """--help mentions --html-report."""
    result = subprocess.run(
        [sys.executable, "image-cgroupsv2-inspector", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--html-report" in result.stdout


def test_maybe_generate_html_report_disabled(tmp_path):
    """When enabled=False, no HTML is written even if csv exists."""
    mod = _load_inspector_module()
    csv = tmp_path / "out.csv"
    csv.write_text("source\n")
    mod._maybe_generate_html_report(
        csv_path=str(csv),
        output_dir=str(tmp_path),
        tool_version="2.0.0",
        target="test",
        enabled=False,
        logger=logging.getLogger("test"),
    )
    assert not (tmp_path / "html").exists()


def test_maybe_generate_html_report_enabled(tmp_path):
    """When enabled=True, HTML is written under <output_dir>/html/."""
    mod = _load_inspector_module()
    csv_src = Path("tests/fixtures/sample_report.csv")
    csv_dst = tmp_path / "run.csv"
    csv_dst.write_bytes(csv_src.read_bytes())

    mod._maybe_generate_html_report(
        csv_path=str(csv_dst),
        output_dir=str(tmp_path),
        tool_version="2.0.0",
        target="test-target",
        enabled=True,
        logger=logging.getLogger("test"),
    )
    html_path = tmp_path / "html" / "run.html"
    assert html_path.exists()
    assert html_path.stat().st_size > 1024
    content = html_path.read_text()
    assert "<!DOCTYPE html>" in content
    assert "test-target" in content


def test_maybe_generate_html_report_survives_errors(tmp_path):
    """If generation fails, the function must NOT raise (CSV is primary output)."""
    mod = _load_inspector_module()
    mod._maybe_generate_html_report(
        csv_path=str(tmp_path / "nonexistent.csv"),
        output_dir=str(tmp_path),
        tool_version="2.0.0",
        target="x",
        enabled=True,
        logger=logging.getLogger("test"),
    )


# ---------------------------------------------------------------------------
# --report-only tests
# ---------------------------------------------------------------------------


def test_report_only_generates_html(tmp_path):
    """--report-only against an existing CSV generates HTML and exits 0."""
    csv_dst = tmp_path / "mycluster-20260417-120000.csv"
    csv_dst.write_bytes(Path("tests/fixtures/sample_report.csv").read_bytes())

    result = subprocess.run(
        [
            sys.executable,
            "image-cgroupsv2-inspector",
            "--report-only",
            str(csv_dst),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    expected_html = tmp_path / "html" / "mycluster-20260417-120000.html"
    assert expected_html.exists()
    assert expected_html.stat().st_size > 1024


def test_report_only_with_output_dir(tmp_path):
    """--report-only respects --output-dir."""
    csv_dst = tmp_path / "scan.csv"
    csv_dst.write_bytes(Path("tests/fixtures/sample_report.csv").read_bytes())
    custom_out = tmp_path / "custom_output"

    result = subprocess.run(
        [
            sys.executable,
            "image-cgroupsv2-inspector",
            "--report-only",
            str(csv_dst),
            "--output-dir",
            str(custom_out),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    expected_html = custom_out / "html" / "scan.html"
    assert expected_html.exists()


def test_report_only_missing_file(tmp_path):
    """--report-only with a non-existent file exits 1."""
    result = subprocess.run(
        [
            sys.executable,
            "image-cgroupsv2-inspector",
            "--report-only",
            str(tmp_path / "does-not-exist.csv"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "not found" in result.stdout.lower() or "not found" in result.stderr.lower()


def test_report_only_rejects_analyze(tmp_path):
    """--report-only is incompatible with --analyze."""
    csv_dst = tmp_path / "scan.csv"
    csv_dst.write_bytes(Path("tests/fixtures/sample_report.csv").read_bytes())

    result = subprocess.run(
        [
            sys.executable,
            "image-cgroupsv2-inspector",
            "--report-only",
            str(csv_dst),
            "--analyze",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "incompatible" in result.stdout.lower() or "incompatible" in result.stderr.lower()


def test_report_only_rejects_wrong_extension(tmp_path):
    """--report-only rejects files that don't end in .csv."""
    wrong = tmp_path / "scan.txt"
    wrong.write_text("not a csv")

    result = subprocess.run(
        [
            sys.executable,
            "image-cgroupsv2-inspector",
            "--report-only",
            str(wrong),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
