"""Smoke tests for the tool version single source of truth."""

import re
import tomllib
from pathlib import Path

from src import __version__

# PEP 440-ish: X.Y.Z with optional pre/post/dev suffix tolerated.
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([.\-+].+)?$")


def test_version_is_well_formed():
    """__version__ must follow X.Y.Z."""
    assert _VERSION_RE.match(__version__), f"__version__={__version__!r} does not match X.Y.Z"


def test_pyproject_version_matches_sot():
    """pyproject.toml `version` must equal src.__version__."""
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    assert pyproject["project"]["version"] == __version__, (
        f"pyproject.toml version ({pyproject['project']['version']!r}) "
        f"is out of sync with src.__version__ ({__version__!r}). "
        "Update both together."
    )


def test_main_script_uses_sot():
    """The main script must import TOOL_VERSION from src, not hardcode it."""
    main = Path("image-cgroupsv2-inspector").read_text()
    assert "from src import __version__ as TOOL_VERSION" in main, (
        "Main script must import TOOL_VERSION from src.__version__ (single SoT)."
    )
    assert 'TOOL_VERSION = "' not in main, "Main script should not redefine TOOL_VERSION as a literal."
