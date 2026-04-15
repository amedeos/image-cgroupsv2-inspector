"""
Go Scan Module
==============

Deterministic Go binary cgroups v2 compatibility analysis.

Detects Go binaries in container images by running ``go version`` and
``go version -m`` from the host machine against extracted binaries.
This replaces the heuristic ``strings`` + grep approach with precise
version-based detection.

Compatibility matrix:
- Go >= 1.19: native cgroups v2 support in the Go runtime.
- Go < 1.19 + v2-aware cgroup module at sufficient version: compatible.
- Go < 1.19 + v2-aware cgroup module below minimum version: needs review.
- Go < 1.19 + no v2-aware modules: not compatible.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

GO_V2_RUNTIME_VERSION = (1, 19)

GO_V2_AWARE_MODULES = {
    "go.uber.org/automaxprocs": "v1.5.0",
    "github.com/KimMachineGun/automemlimit": "v0.1.0",
    "github.com/containerd/cgroups": "v1.0.0",
    "github.com/opencontainers/runc/libcontainer/cgroups": "v1.1.0",
}

_GO_VERSION_RE = re.compile(r"go(\d+)\.(\d+)")
_GO_DEP_RE = re.compile(r"^\s+dep\s+(\S+)\s+(v\S+)", re.MULTILINE)


@dataclass
class GoBinaryInfo:
    """Result of analyzing a Go binary with ``go version`` and ``go version -m``."""

    path: str
    go_version: str
    modules: dict[str, str] = field(default_factory=dict)
    is_compatible: bool | None = None
    compliance_reason: str = ""


def parse_go_version(version_str: str) -> tuple[int | None, int | None]:
    """Parse ``'go1.22.5'`` -> ``(1, 22)``, ``'go1.18'`` -> ``(1, 18)``."""
    match = _GO_VERSION_RE.match(version_str)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def semver_gte(version_a: str, version_b: str) -> bool:
    """Check if *version_a* >= *version_b* (simple semver with v-prefix)."""
    def parse(v: str) -> tuple[int, ...]:
        return tuple(int(p) for p in v.lstrip("v").split(".")[:3])
    try:
        return parse(version_a) >= parse(version_b)
    except (ValueError, IndexError):
        return False


def check_go_compatibility(
    go_version: str,
    modules: dict[str, str],
) -> tuple[bool | None, str]:
    """Determine Go binary cgroups v2 compatibility.

    Args:
        go_version: Version string from ``go version``, e.g. ``"go1.22.5"``.
        modules: All dependency modules from ``go version -m``.

    Returns:
        Tuple of (is_compatible, reason).
    """
    major, minor = parse_go_version(go_version)

    if major is None:
        return None, f"Cannot parse Go version: {go_version}"

    if (major, minor) >= GO_V2_RUNTIME_VERSION:
        return True, f"Go {major}.{minor} >= 1.19: runtime native v2 support"

    for mod_path, min_version in GO_V2_AWARE_MODULES.items():
        if mod_path in modules:
            detected_version = modules[mod_path]
            short_name = mod_path.rsplit("/", 1)[-1]
            if semver_gte(detected_version, min_version):
                return True, (
                    f"Go {major}.{minor} < 1.19, but {short_name} "
                    f"{detected_version} >= {min_version} provides v2 support"
                )
            else:
                return None, (
                    f"Go {major}.{minor} < 1.19, {short_name} "
                    f"{detected_version} < {min_version}: needs review"
                )

    return False, f"Go {major}.{minor} < 1.19, no v2-aware cgroup modules detected"


def get_go_version(binary_path: str, debug: bool = False) -> str | None:
    """Run ``go version <binary_path>`` and return the Go version string.

    Returns:
        The Go version (e.g. ``"go1.22.5"``), or None if the binary
        is not a Go binary or ``go`` is not available.
    """
    try:
        result = subprocess.run(
            ["go", "version", binary_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if debug:
            logger.debug("go version %s → exit=%d, stdout=%s", binary_path, result.returncode, result.stdout[:200])
        if result.returncode != 0:
            return None
        # Output format: "/path/to/binary: go1.22.5"
        match = _GO_VERSION_RE.search(result.stdout)
        if match:
            return f"go{match.group(1)}.{match.group(2)}"
        # Try extracting fuller version (with patch) from output
        full_match = re.search(r"(go\d+\.\d+(?:\.\d+)?)", result.stdout)
        if full_match:
            return full_match.group(1)
        return None
    except FileNotFoundError:
        logger.debug("'go' command not found in PATH")
        return None
    except subprocess.TimeoutExpired:
        logger.debug("go version timed out for %s", binary_path)
        return None
    except Exception as e:
        logger.debug("go version error for %s: %s", binary_path, e)
        return None


def get_go_module_info(binary_path: str, debug: bool = False) -> dict[str, str]:
    """Run ``go version -m <binary_path>`` and parse all module dependencies.

    Returns:
        Dict of module_path -> version for all ``dep`` lines.
    """
    modules: dict[str, str] = {}
    try:
        result = subprocess.run(
            ["go", "version", "-m", binary_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if debug:
            logger.debug("go version -m %s → exit=%d", binary_path, result.returncode)
        if result.returncode != 0:
            return modules

        for match in _GO_DEP_RE.finditer(result.stdout):
            modules[match.group(1)] = match.group(2)

        return modules
    except FileNotFoundError:
        logger.debug("'go' command not found in PATH")
        return modules
    except subprocess.TimeoutExpired:
        logger.debug("go version -m timed out for %s", binary_path)
        return modules
    except Exception as e:
        logger.debug("go version -m error for %s: %s", binary_path, e)
        return modules


def find_go_binaries(
    extract_path: Path,
    entrypoint: list[str] | None,
    cmd: list[str] | None,
    debug: bool = False,
) -> list[tuple[str, str, str]]:
    """Identify Go binaries among entrypoint/cmd references.

    For each reference in entrypoint + cmd, resolves it in the extracted
    rootfs and runs ``go version`` on it. If it succeeds, the binary is
    a Go binary.

    Args:
        extract_path: Path to the extracted container rootfs.
        entrypoint: ENTRYPOINT from image config.
        cmd: CMD from image config.
        debug: Enable debug output.

    Returns:
        List of (container_path, extracted_path, go_version) tuples.
    """
    from .deep_scan import _INTERPRETER_PATHS, _is_elf_binary, _resolve_script_in_rootfs

    combined: list[str] = []
    if entrypoint:
        combined.extend(entrypoint)
    if cmd:
        combined.extend(cmd)

    if not combined:
        return []

    results: list[tuple[str, str, str]] = []
    checked: set[str] = set()

    for ref in combined:
        if "/" not in ref or ref.startswith("-"):
            continue
        if ref in _INTERPRETER_PATHS:
            continue

        resolved = _resolve_script_in_rootfs(ref, extract_path)
        if resolved is None:
            logger.debug("Could not resolve in rootfs: %s", ref)
            if debug:
                print(f"      [DEBUG] Could not resolve in rootfs: {ref}")
            continue

        real_path = str(resolved.resolve())
        if real_path in checked:
            continue
        checked.add(real_path)

        if not _is_elf_binary(resolved):
            continue

        go_ver = get_go_version(real_path, debug=debug)
        if go_ver is not None:
            try:
                rel = resolved.relative_to(extract_path.resolve())
                container_path = f"/{rel}"
            except ValueError:
                container_path = ref
            results.append((container_path, real_path, go_ver))
            logger.debug("Go binary found: %s → %s", container_path, go_ver)
            if debug:
                print(f"      [DEBUG] Go binary found: {container_path} → {go_ver}")

    # Also check binaries discovered via exec chains in entrypoint scripts
    from .deep_scan import scan_entrypoint_scripts

    _, _, discovered_binaries = scan_entrypoint_scripts(
        extract_path=extract_path,
        entrypoint_cmd=combined,
        debug=debug,
    )

    for bin_ref in discovered_binaries:
        resolved = _resolve_script_in_rootfs(bin_ref, extract_path)
        if resolved is None:
            continue
        real_path = str(resolved.resolve())
        if real_path in checked:
            continue
        checked.add(real_path)

        if not _is_elf_binary(resolved):
            continue

        go_ver = get_go_version(real_path, debug=debug)
        if go_ver is not None:
            try:
                rel = resolved.relative_to(extract_path.resolve())
                container_path = f"/{rel}"
            except ValueError:
                container_path = bin_ref
            results.append((container_path, real_path, go_ver))
            logger.debug("Go binary found (exec chain): %s → %s", container_path, go_ver)
            if debug:
                print(f"      [DEBUG] Go binary found (exec chain): {container_path} → {go_ver}")

    return results
