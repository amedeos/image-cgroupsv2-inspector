"""
Deep Scan Module
================

Heuristic detection of cgroup v1 references in container images.
Scans entrypoint scripts, sourced scripts, and binaries for patterns
that indicate the image may not work correctly on cgroup v2 systems.

Confidence levels:
- high:   pattern found directly in the ENTRYPOINT/CMD script
- medium: pattern found in a script sourced/executed by the entrypoint
- low:    pattern found via `strings` on a binary
"""

from __future__ import annotations

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Cgroup v1 controller paths (directories under /sys/fs/cgroup/)
# These directories exist ONLY in cgroup v1 and NOT in unified cgroup v2.
# ---------------------------------------------------------------------------
CGROUPV1_CONTROLLER_DIRS = (
    "/sys/fs/cgroup/memory/",
    "/sys/fs/cgroup/cpu/",
    "/sys/fs/cgroup/cpuacct/",
    "/sys/fs/cgroup/blkio/",
    "/sys/fs/cgroup/devices/",
    "/sys/fs/cgroup/freezer/",
    "/sys/fs/cgroup/net_cls/",
    "/sys/fs/cgroup/net_prio/",
    "/sys/fs/cgroup/perf_event/",
    "/sys/fs/cgroup/hugetlb/",
    "/sys/fs/cgroup/pids/",
    "/sys/fs/cgroup/rdma/",
    "/sys/fs/cgroup/cpu,cpuacct/",
    "/sys/fs/cgroup/net_cls,net_prio/",
)

# ---------------------------------------------------------------------------
# Cgroup v1 control files — names that are exclusive to v1.
# These file names do NOT exist under the cgroup v2 unified hierarchy.
# ---------------------------------------------------------------------------
CGROUPV1_FILE_NAMES = (
    # Memory controller (v1)
    "memory.limit_in_bytes",
    "memory.usage_in_bytes",
    "memory.max_usage_in_bytes",
    "memory.soft_limit_in_bytes",
    "memory.failcnt",
    "memory.memsw.limit_in_bytes",
    "memory.memsw.usage_in_bytes",
    "memory.kmem.limit_in_bytes",
    "memory.kmem.usage_in_bytes",
    # CPU controller (v1)
    "cpu.cfs_quota_us",
    "cpu.cfs_period_us",
    "cpu.shares",
    "cpu.rt_runtime_us",
    "cpu.rt_period_us",
    # CPU accounting (v1 only — merged into cpu in v2)
    "cpuacct.usage",
    "cpuacct.usage_percpu",
    "cpuacct.stat",
    # Block I/O (v1 name; v2 uses "io")
    "blkio.weight",
    "blkio.throttle.read_bps_device",
    "blkio.throttle.write_bps_device",
    "blkio.throttle.read_iops_device",
    "blkio.throttle.write_iops_device",
)

# ---------------------------------------------------------------------------
# Compiled regex that matches ANY of the above patterns in a text line.
# Used by the scan functions to test whether a line contains a v1 reference.
# ---------------------------------------------------------------------------
_PATTERN_STRINGS = list(CGROUPV1_CONTROLLER_DIRS) + list(CGROUPV1_FILE_NAMES)

# Sort longest-first so that e.g. "/sys/fs/cgroup/cpu,cpuacct/" matches
# before "/sys/fs/cgroup/cpu/".
_PATTERN_STRINGS.sort(key=len, reverse=True)
CGROUPV1_REGEX = re.compile("|".join(re.escape(p) for p in _PATTERN_STRINGS))


def find_cgroupv1_patterns(text: str) -> list[str]:
    """Return de-duplicated cgroup v1 patterns found in *text*.

    Args:
        text: Content to scan (file content, strings output, etc.)

    Returns:
        List of unique matched pattern strings, in order of first occurrence.
    """
    seen: dict[str, None] = {}
    for match in CGROUPV1_REGEX.finditer(text):
        pattern = match.group(0)
        if pattern not in seen:
            seen[pattern] = None
    return list(seen)


# ---------------------------------------------------------------------------
# Cgroup v2 control files — names that are exclusive to the unified hierarchy.
# If these appear in the SAME file as v1 patterns, the code likely handles
# both cgroup versions (v2-aware).
# ---------------------------------------------------------------------------
CGROUPV2_FILE_NAMES = (
    # Unified hierarchy detection
    "cgroup.controllers",
    "cgroup.subtree_control",
    "cgroup.type",
    # Memory controller (v2)
    "memory.max",
    "memory.current",
    "memory.high",
    "memory.low",
    "memory.min",
    "memory.swap.max",
    "memory.swap.current",
    # CPU controller (v2)
    "cpu.max",
    "cpu.weight",
    "cpu.pressure",
    # I/O controller (v2 — replaces blkio)
    "io.max",
    "io.weight",
    "io.pressure",
    # PIDs controller (same name in v2 but in unified hierarchy)
    "pids.max",
    "pids.current",
)

CGROUPV2_CONTROLLER_PATHS = (
    "/sys/fs/cgroup/cgroup.controllers",
    "/sys/fs/cgroup/cgroup.subtree_control",
)

_V2_PATTERN_STRINGS = list(CGROUPV2_FILE_NAMES) + list(CGROUPV2_CONTROLLER_PATHS)
_V2_PATTERN_STRINGS.sort(key=len, reverse=True)
CGROUPV2_REGEX = re.compile("|".join(re.escape(p) for p in _V2_PATTERN_STRINGS))


def find_cgroupv2_patterns(text: str) -> list[str]:
    """Return de-duplicated cgroup v2 patterns found in *text*.

    Args:
        text: Content to scan.

    Returns:
        List of unique matched v2 pattern strings, in order of first occurrence.
    """
    seen: dict[str, None] = {}
    for match in CGROUPV2_REGEX.finditer(text):
        pattern = match.group(0)
        if pattern not in seen:
            seen[pattern] = None
    return list(seen)


# ---------------------------------------------------------------------------
# Patterns for detecting sourced/executed scripts in shell scripts
# ---------------------------------------------------------------------------
_SOURCE_PATTERN = re.compile(
    r"""(?:^|\s)(?:source|\.)\s+["']?([^\s"'#;]+)["']?""",
    re.MULTILINE,
)
_EXEC_PATTERN = re.compile(
    r"""(?:^|\s)exec\s+["']?([^\s"'#;$]+)["']?""",
    re.MULTILINE,
)

_MAX_SOURCE_DEPTH = 5
_MAX_SCRIPT_SIZE = 1 * 1024 * 1024  # 1 MB


def _is_shell_script(file_path: Path) -> bool:
    """Check if a file is likely a shell script.

    A file is considered a shell script if:
    - It has a shell-like extension (.sh, .bash), OR
    - Its first line is a shell shebang (#!/bin/bash, #!/bin/sh, #!/usr/bin/env bash)
    """
    if file_path.suffix in (".sh", ".bash"):
        return True
    try:
        with open(file_path, "r", errors="replace") as f:
            first_line = f.readline(256)
        return bool(re.match(r"^#!\s*/(?:usr/)?(?:bin/)?(?:env\s+)?(?:ba)?sh", first_line))
    except (OSError, UnicodeDecodeError):
        return False


def _resolve_script_in_rootfs(
    script_ref: str,
    extract_path: Path,
    relative_to: Path | None = None,
) -> Path | None:
    """Resolve a script reference to an actual file in the extracted rootfs.

    Handles:
    - Absolute paths: /usr/local/bin/entrypoint.sh → extract_path/usr/local/bin/entrypoint.sh
    - Relative paths: ./helpers.sh → resolved relative to `relative_to` directory
    - Paths with shell variable references like ${SCRIPT_DIR}/file.sh are resolved
      by trying common expansions, but ultimately skipped if unresolvable.

    Returns:
        Resolved Path if the file exists and is readable, None otherwise.
    """
    if "$" in script_ref and not script_ref.startswith("/"):
        return None

    if script_ref.startswith("/"):
        candidate = extract_path / script_ref.lstrip("/")
    elif relative_to:
        candidate = relative_to / script_ref
    else:
        candidate = extract_path / script_ref

    try:
        resolved = candidate.resolve()
        if not str(resolved).startswith(str(extract_path.resolve())):
            return None
        if resolved.is_file():
            return resolved
    except (OSError, ValueError):
        pass

    return None


def _read_script_content(file_path: Path) -> str | None:
    """Read a script file's content, returning None if unreadable or too large."""
    try:
        if file_path.stat().st_size > _MAX_SCRIPT_SIZE:
            return None
        with open(file_path, "r", errors="replace") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _extract_sourced_paths(content: str) -> list[str]:
    """Extract file paths from source/. and exec statements in a shell script."""
    paths: list[str] = []
    for match in _SOURCE_PATTERN.finditer(content):
        paths.append(match.group(1))
    for match in _EXEC_PATTERN.finditer(content):
        path = match.group(1)
        if "/" in path:
            paths.append(path)
    return paths


def scan_entrypoint_scripts(
    extract_path: Path,
    entrypoint_cmd: list[str],
    debug: bool = False,
) -> tuple[list, bool]:
    """Scan entrypoint/CMD scripts for cgroup v1 references.

    Resolves the entrypoint to a file in the extracted rootfs, scans it
    for cgroup v1 patterns, then follows source/exec chains to scan
    referenced scripts.

    Args:
        extract_path: Path to the extracted container rootfs.
        entrypoint_cmd: Combined ENTRYPOINT + CMD as a list of strings
            (e.g. ["/entrypoint.sh", "arg1"]).
        debug: Enable debug output.

    Returns:
        Tuple of (matches, v2_aware):
        - matches: list of DeepScanMatch objects
        - v2_aware: True if ANY scanned file contains both v1 AND v2 patterns
    """
    from .image_analyzer import DeepScanMatch

    matches: list[DeepScanMatch] = []
    v2_aware = False
    scanned_files: set[str] = set()

    def _scan_script(
        file_path: Path,
        container_path: str,
        confidence: str,
        depth: int = 0,
    ) -> None:
        nonlocal v2_aware

        real_path_str = str(file_path.resolve())
        if real_path_str in scanned_files:
            return
        if depth > _MAX_SOURCE_DEPTH:
            if debug:
                print(f"      [DEBUG] Max source depth reached at {container_path}")
            return
        scanned_files.add(real_path_str)

        content = _read_script_content(file_path)
        if content is None:
            if debug:
                print(f"      [DEBUG] Cannot read script: {container_path}")
            return

        if debug:
            print(f"      [DEBUG] Scanning script: {container_path} (confidence={confidence}, depth={depth})")

        v1_patterns = find_cgroupv1_patterns(content)
        if v1_patterns:
            for pattern in v1_patterns:
                matches.append(DeepScanMatch(
                    source=container_path,
                    pattern=pattern,
                    confidence=confidence,
                ))
            if debug:
                print(f"      [DEBUG]   Found {len(v1_patterns)} cgroup v1 patterns in {container_path}")

            v2_patterns = find_cgroupv2_patterns(content)
            if v2_patterns:
                v2_aware = True
                if debug:
                    print(f"      [DEBUG]   Also found {len(v2_patterns)} cgroup v2 patterns → v2-aware")

        sourced_paths = _extract_sourced_paths(content)
        for sourced_ref in sourced_paths:
            resolved = _resolve_script_in_rootfs(
                sourced_ref,
                extract_path,
                relative_to=file_path.parent,
            )
            if resolved and _is_shell_script(resolved):
                try:
                    rel = resolved.relative_to(extract_path.resolve())
                    sourced_container_path = f"/{rel}"
                except ValueError:
                    sourced_container_path = sourced_ref

                _scan_script(
                    resolved,
                    sourced_container_path,
                    confidence="medium",
                    depth=depth + 1,
                )

    if not entrypoint_cmd:
        if debug:
            print("      [DEBUG] No entrypoint/cmd to scan")
        return matches, v2_aware

    entrypoint_ref = entrypoint_cmd[0]

    if debug:
        print(f"      [DEBUG] Entrypoint reference: {entrypoint_ref}")
        print(f"      [DEBUG] Full entrypoint+cmd: {entrypoint_cmd}")

    if "/" not in entrypoint_ref:
        if debug:
            print(f"      [DEBUG] Skipping non-path entrypoint: {entrypoint_ref}")
        return matches, v2_aware

    resolved = _resolve_script_in_rootfs(entrypoint_ref, extract_path)
    if resolved is None:
        if debug:
            print(f"      [DEBUG] Could not resolve entrypoint in rootfs: {entrypoint_ref}")
        return matches, v2_aware

    if not _is_shell_script(resolved):
        if debug:
            print(f"      [DEBUG] Entrypoint is not a shell script: {entrypoint_ref}")
        return matches, v2_aware

    _scan_script(resolved, entrypoint_ref, confidence="high", depth=0)

    for arg in entrypoint_cmd[1:]:
        if "/" in arg and not arg.startswith("-"):
            arg_resolved = _resolve_script_in_rootfs(arg, extract_path)
            if arg_resolved and _is_shell_script(arg_resolved) and str(arg_resolved.resolve()) not in scanned_files:
                _scan_script(arg_resolved, arg, confidence="high", depth=0)

    return matches, v2_aware


def run_deep_scan(
    extract_path: Path,
    image_name: str,
    entrypoint: list[str] | None = None,
    cmd: list[str] | None = None,
    debug: bool = False,
) -> tuple[list, bool]:
    """Run all deep-scan heuristics on an extracted container rootfs.

    Args:
        extract_path: Path to the extracted container rootfs.
        image_name: Image name (for debug logging).
        entrypoint: ENTRYPOINT from image config (list of strings or None).
        cmd: CMD from image config (list of strings or None).
        debug: Enable debug output.

    Returns:
        Tuple of (matches, v2_aware):
        - matches: list of DeepScanMatch objects
        - v2_aware: True if any scanned source has both v1 and v2 patterns
    """
    if debug:
        print(f"      [DEBUG] Deep scan enabled for {image_name}")
        print(f"      [DEBUG] Extract path: {extract_path}")
        print(f"      [DEBUG] ENTRYPOINT: {entrypoint}")
        print(f"      [DEBUG] CMD: {cmd}")
        print(f"      [DEBUG] Loaded {len(_PATTERN_STRINGS)} cgroup v1 patterns")

    all_matches: list = []
    v2_aware = False

    combined: list[str] = []
    if entrypoint:
        combined.extend(entrypoint)
    if cmd:
        combined.extend(cmd)

    # Step 3: Entrypoint script scanning
    if combined:
        script_matches, scripts_v2_aware = scan_entrypoint_scripts(
            extract_path=extract_path,
            entrypoint_cmd=combined,
            debug=debug,
        )
        all_matches.extend(script_matches)
        if scripts_v2_aware:
            v2_aware = True

    # Step 4 (future): Binary strings scanning will be added here

    return all_matches, v2_aware
