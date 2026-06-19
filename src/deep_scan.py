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

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

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
# Use negative lookbehind/lookahead to prevent matching v2 patterns
# that are substrings of v1 patterns (e.g. "io.weight" inside "blkio.weight",
# "memory.max" inside "memory.max_usage_in_bytes").
CGROUPV2_REGEX = re.compile("|".join(rf"(?<![a-z]){re.escape(p)}(?![a-z_])" for p in _V2_PATTERN_STRINGS))


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
_SET_PATTERN = re.compile(
    r"""(?:^|\s)set\s+--\s+["']?([^\s"'#;$]+)["']?""",
    re.MULTILINE,
)

_DEFAULT_PATH_DIRS = (
    "usr/local/sbin",
    "usr/local/bin",
    "usr/sbin",
    "usr/bin",
    "sbin",
    "bin",
)

_MAX_SOURCE_DEPTH = 5
_MAX_SCRIPT_SIZE = 1 * 1024 * 1024  # 1 MB

# Common interpreter paths to skip when collecting binaries for strings scan.
# These appear in ENTRYPOINT/CMD but are never the application binary.
_INTERPRETER_PATHS = frozenset(
    {
        "/bin/bash",
        "/bin/sh",
        "/bin/dash",
        "/bin/zsh",
        "/usr/bin/bash",
        "/usr/bin/sh",
        "/usr/bin/dash",
        "/usr/bin/zsh",
        "/usr/bin/env",
        "/bin/env",
    }
)


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
    extra_path_dirs: tuple[str, ...] | None = None,
) -> Path | None:
    """Resolve a script reference to an actual file in the extracted rootfs.

    Handles:
    - Absolute paths: /usr/local/bin/entrypoint.sh
    - Relative paths: ./helpers.sh (resolved relative to `relative_to`)
    - Bare commands: searched in _DEFAULT_PATH_DIRS + extra_path_dirs
    - Shell variable paths: ${SCRIPT_DIR}/helpers.sh, $DIR/helpers.sh
      → extracts the filename and tries relative resolution against
        the directory of the sourcing script

    Returns:
        Resolved Path if the file exists and is readable, None otherwise.
    """
    # Handle paths containing shell variables
    if "$" in script_ref:
        # Try to extract the filename portion after the last /
        # e.g. "${SCRIPT_DIR}/cgroup-helpers.sh" → "cgroup-helpers.sh"
        if "/" in script_ref:
            filename = script_ref.rsplit("/", 1)[-1]
            # If the filename itself contains a variable, give up
            if "$" in filename:
                return None
            # Try to resolve the filename relative to the sourcing script's dir
            if relative_to:
                candidate = relative_to / filename
                try:
                    resolved = candidate.resolve()
                    if str(resolved).startswith(str(extract_path.resolve())) and resolved.is_file():
                        return resolved
                except (OSError, ValueError):
                    pass
        return None

    # Bare command name (no "/" and no "$"): try relative_to first, then PATH dirs
    if "/" not in script_ref:
        if relative_to:
            candidate = relative_to / script_ref
            try:
                resolved = candidate.resolve()
                if str(resolved).startswith(str(extract_path.resolve())) and resolved.is_file():
                    return resolved
            except (OSError, ValueError):
                pass
        search_dirs = _DEFAULT_PATH_DIRS
        if extra_path_dirs:
            search_dirs = extra_path_dirs + _DEFAULT_PATH_DIRS
        for path_dir in search_dirs:
            candidate = extract_path / path_dir / script_ref
            try:
                resolved = candidate.resolve()
                if str(resolved).startswith(str(extract_path.resolve())) and resolved.is_file():
                    return resolved
            except (OSError, ValueError):
                continue
        return None

    if script_ref.startswith("/"):
        candidate = extract_path / script_ref.lstrip("/")
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


_MAX_BINARY_SIZE = 200 * 1024 * 1024  # 200 MB

_STRINGS_MIN_LENGTH = 8


def _is_elf_binary(file_path: Path) -> bool:
    """Check if a file is an ELF binary by reading its magic bytes."""
    try:
        with open(file_path, "rb") as f:
            magic = f.read(4)
        return magic == b"\x7fELF"
    except OSError:
        return False


def _run_strings(file_path: Path, debug: bool = False) -> str | None:
    """Run the `strings` command on a binary file.

    Args:
        file_path: Path to the binary file.
        debug: Enable debug output.

    Returns:
        The strings output as a single string, or None if strings fails
        or the binary is too large.
    """
    import subprocess

    try:
        file_size = file_path.stat().st_size
        if file_size > _MAX_BINARY_SIZE:
            logger.debug("Binary too large for strings: %d bytes > %d", file_size, _MAX_BINARY_SIZE)
            if debug:
                print(f"      [DEBUG] Binary too large for strings: {file_size} bytes > {_MAX_BINARY_SIZE}")
            return None
        if file_size == 0:
            return None
    except OSError:
        return None

    try:
        result = subprocess.run(
            ["strings", f"-n{_STRINGS_MIN_LENGTH}", str(file_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.debug("strings command failed: %s", result.stderr[:200])
            if debug:
                print(f"      [DEBUG] strings command failed: {result.stderr[:200]}")
            return None
        return result.stdout
    except FileNotFoundError:
        logger.debug("'strings' command not found in PATH")
        if debug:
            print("      [DEBUG] 'strings' command not found in PATH")
        return None
    except subprocess.TimeoutExpired:
        logger.debug("strings command timed out")
        if debug:
            print("      [DEBUG] strings command timed out")
        return None
    except Exception as e:
        logger.debug("strings error: %s", e)
        if debug:
            print(f"      [DEBUG] strings error: {e}")
        return None


def scan_binary_strings(
    extract_path: Path,
    binary_refs: list[str],
    debug: bool = False,
) -> tuple[list, bool]:
    """Scan binary files via `strings` for cgroup v1 references.

    For each binary reference:
    1. Resolve it in the extracted rootfs
    2. Verify it's an ELF binary
    3. Run `strings` on it
    4. Check the output for cgroup v1 patterns
    5. Check for cgroup v2 patterns (v2-awareness)

    Args:
        extract_path: Path to the extracted container rootfs.
        binary_refs: List of container paths to check (e.g. ["/usr/bin/cadvisor"]).
        debug: Enable debug output.

    Returns:
        Tuple of (matches, v2_aware):
        - matches: list of DeepScanMatch objects with confidence="low"
        - v2_aware: True if any binary contains both v1 and v2 patterns
    """
    from .image_analyzer import DeepScanMatch

    matches: list[DeepScanMatch] = []
    v2_aware = False
    scanned_binaries: set[str] = set()

    for binary_ref in binary_refs:
        resolved = _resolve_script_in_rootfs(binary_ref, extract_path)
        if resolved is None:
            logger.debug("Could not resolve binary in rootfs: %s", binary_ref)
            if debug:
                print(f"      [DEBUG] Could not resolve binary in rootfs: {binary_ref}")
            continue

        real_path_str = str(resolved.resolve())
        if real_path_str in scanned_binaries:
            continue
        scanned_binaries.add(real_path_str)

        if not _is_elf_binary(resolved):
            logger.debug("Not an ELF binary, skipping: %s", binary_ref)
            if debug:
                print(f"      [DEBUG] Not an ELF binary, skipping: {binary_ref}")
            continue

        try:
            size_mb = resolved.stat().st_size / (1024 * 1024)
            logger.debug("Running strings on binary: %s (%.1f MB)", binary_ref, size_mb)
        except OSError:
            logger.debug("Running strings on binary: %s", binary_ref)
        if debug:
            try:
                size_mb = resolved.stat().st_size / (1024 * 1024)
                print(f"      [DEBUG] Running strings on binary: {binary_ref} ({size_mb:.1f} MB)")
            except OSError:
                print(f"      [DEBUG] Running strings on binary: {binary_ref}")

        strings_output = _run_strings(resolved, debug=debug)
        if strings_output is None:
            continue

        v1_patterns = find_cgroupv1_patterns(strings_output)
        if v1_patterns:
            source = f"binary:{binary_ref}"
            for pattern in v1_patterns:
                matches.append(
                    DeepScanMatch(
                        source=source,
                        pattern=pattern,
                        confidence="low",
                    )
                )
            logger.debug("  Found %d cgroup v1 patterns in %s", len(v1_patterns), binary_ref)
            if debug:
                print(f"      [DEBUG]   Found {len(v1_patterns)} cgroup v1 patterns in {binary_ref}")

            v2_patterns = find_cgroupv2_patterns(strings_output)
            if v2_patterns:
                v2_aware = True
                logger.debug("  Also found %d cgroup v2 patterns — v2-aware", len(v2_patterns))
                if debug:
                    print(f"      [DEBUG]   Also found {len(v2_patterns)} cgroup v2 patterns → v2-aware")
        else:
            logger.debug("  No cgroup v1 patterns found in %s", binary_ref)
            if debug:
                print(f"      [DEBUG]   No cgroup v1 patterns found in {binary_ref}")

    return matches, v2_aware


def _extract_sourced_paths(content: str) -> list[str]:
    """Extract file paths from source/., exec, and set -- statements in a shell script."""
    paths: list[str] = []
    for match in _SOURCE_PATTERN.finditer(content):
        paths.append(match.group(1))
    for match in _EXEC_PATTERN.finditer(content):
        paths.append(match.group(1))
    for match in _SET_PATTERN.finditer(content):
        paths.append(match.group(1))
    return paths


def scan_entrypoint_scripts(
    extract_path: Path,
    entrypoint_cmd: list[str],
    debug: bool = False,
    extra_path_dirs: tuple[str, ...] | None = None,
) -> tuple[list, bool, list[str]]:
    """Scan entrypoint/CMD scripts for cgroup v1 references.

    Resolves the entrypoint to a file in the extracted rootfs, scans it
    for cgroup v1 patterns, then follows source/exec chains to scan
    referenced scripts. ELF binaries discovered via exec chains are
    collected and returned for separate strings scanning.

    Args:
        extract_path: Path to the extracted container rootfs.
        entrypoint_cmd: Combined ENTRYPOINT + CMD as a list of strings
            (e.g. ["/entrypoint.sh", "arg1"]).
        debug: Enable debug output.

    Returns:
        Tuple of (matches, v2_aware, discovered_binaries):
        - matches: list of DeepScanMatch objects
        - v2_aware: True if ANY scanned file contains both v1 AND v2 patterns
        - discovered_binaries: list of container paths to ELF binaries
          found via exec chains (to be scanned with strings)
    """
    from .image_analyzer import DeepScanMatch

    matches: list[DeepScanMatch] = []
    v2_aware = False
    scanned_files: set[str] = set()
    discovered_binaries: list[str] = []

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
            logger.debug("Max source depth reached at %s", container_path)
            if debug:
                print(f"      [DEBUG] Max source depth reached at {container_path}")
            return
        scanned_files.add(real_path_str)

        content = _read_script_content(file_path)
        if content is None:
            logger.debug("Cannot read script: %s", container_path)
            if debug:
                print(f"      [DEBUG] Cannot read script: {container_path}")
            return

        logger.debug("Scanning script: %s (confidence=%s, depth=%d)", container_path, confidence, depth)
        if debug:
            print(f"      [DEBUG] Scanning script: {container_path} (confidence={confidence}, depth={depth})")

        v1_patterns = find_cgroupv1_patterns(content)
        if v1_patterns:
            for pattern in v1_patterns:
                matches.append(
                    DeepScanMatch(
                        source=container_path,
                        pattern=pattern,
                        confidence=confidence,
                    )
                )
            logger.debug("  Found %d cgroup v1 patterns in %s", len(v1_patterns), container_path)
            if debug:
                print(f"      [DEBUG]   Found {len(v1_patterns)} cgroup v1 patterns in {container_path}")

            v2_patterns = find_cgroupv2_patterns(content)
            if v2_patterns:
                v2_aware = True
                logger.debug("  Also found %d cgroup v2 patterns — v2-aware", len(v2_patterns))
                if debug:
                    print(f"      [DEBUG]   Also found {len(v2_patterns)} cgroup v2 patterns → v2-aware")

        sourced_paths = _extract_sourced_paths(content)
        for sourced_ref in sourced_paths:
            resolved = _resolve_script_in_rootfs(
                sourced_ref,
                extract_path,
                relative_to=file_path.parent,
                extra_path_dirs=extra_path_dirs,
            )
            if resolved is None:
                continue

            if _is_shell_script(resolved):
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
            elif _is_elf_binary(resolved):
                try:
                    rel = resolved.relative_to(extract_path.resolve())
                    binary_container_path = f"/{rel}"
                except ValueError:
                    binary_container_path = sourced_ref

                if binary_container_path not in _INTERPRETER_PATHS:
                    discovered_binaries.append(binary_container_path)
                    logger.debug("  Discovered ELF binary via exec chain: %s", binary_container_path)
                    if debug:
                        print(f"      [DEBUG]   Discovered ELF binary via exec chain: {binary_container_path}")

    if not entrypoint_cmd:
        logger.debug("No entrypoint/cmd to scan")
        if debug:
            print("      [DEBUG] No entrypoint/cmd to scan")
        return matches, v2_aware, discovered_binaries

    entrypoint_ref = entrypoint_cmd[0]

    logger.debug("Entrypoint reference: %s", entrypoint_ref)
    logger.debug("Full entrypoint+cmd: %s", entrypoint_cmd)
    if debug:
        print(f"      [DEBUG] Entrypoint reference: {entrypoint_ref}")
        print(f"      [DEBUG] Full entrypoint+cmd: {entrypoint_cmd}")

    resolved = _resolve_script_in_rootfs(entrypoint_ref, extract_path, extra_path_dirs=extra_path_dirs)
    if resolved is None:
        logger.debug("Could not resolve entrypoint in rootfs: %s", entrypoint_ref)
        if debug:
            print(f"      [DEBUG] Could not resolve entrypoint in rootfs: {entrypoint_ref}")
        return matches, v2_aware, discovered_binaries

    if not _is_shell_script(resolved):
        logger.debug("Entrypoint is not a shell script: %s", entrypoint_ref)
        if debug:
            print(f"      [DEBUG] Entrypoint is not a shell script: {entrypoint_ref}")
        return matches, v2_aware, discovered_binaries

    _scan_script(resolved, entrypoint_ref, confidence="high", depth=0)

    for arg in entrypoint_cmd[1:]:
        if "/" in arg and not arg.startswith("-"):
            arg_resolved = _resolve_script_in_rootfs(arg, extract_path, extra_path_dirs=extra_path_dirs)
            if arg_resolved and _is_shell_script(arg_resolved) and str(arg_resolved.resolve()) not in scanned_files:
                _scan_script(arg_resolved, arg, confidence="high", depth=0)

    return matches, v2_aware, discovered_binaries


def run_deep_scan(
    extract_path: Path,
    image_name: str,
    entrypoint: list[str] | None = None,
    cmd: list[str] | None = None,
    debug: bool = False,
    extra_path_dirs: tuple[str, ...] | None = None,
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
    logger.debug("Deep scan enabled for %s", image_name)
    logger.debug("Extract path: %s", extract_path)
    logger.debug("ENTRYPOINT: %s", entrypoint)
    logger.debug("CMD: %s", cmd)
    logger.debug("Loaded %d cgroup v1 patterns", len(_PATTERN_STRINGS))
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
    exec_discovered_binaries: list[str] = []
    if combined:
        script_matches, scripts_v2_aware, exec_discovered_binaries = scan_entrypoint_scripts(
            extract_path=extract_path,
            entrypoint_cmd=combined,
            debug=debug,
            extra_path_dirs=extra_path_dirs,
        )
        all_matches.extend(script_matches)
        if scripts_v2_aware:
            v2_aware = True

    # Step 4: Binary strings scanning
    # Scan binaries from two sources:
    # 1. ENTRYPOINT/CMD arguments that are ELF binaries (not shell scripts)
    # 2. ELF binaries discovered via exec chains in entrypoint scripts
    # Skip common interpreters (bash, sh, etc.) that are never the application
    binary_refs: list[str] = []
    for ref in combined:
        if "/" not in ref or ref.startswith("-"):
            continue
        if ref in _INTERPRETER_PATHS:
            logger.debug("Skipping interpreter binary: %s", ref)
            if debug:
                print(f"      [DEBUG] Skipping interpreter binary: {ref}")
            continue
        resolved = _resolve_script_in_rootfs(ref, extract_path)
        if resolved is not None and not _is_shell_script(resolved) and _is_elf_binary(resolved):
            binary_refs.append(ref)

    for ref in exec_discovered_binaries:
        if ref not in binary_refs:
            binary_refs.append(ref)

    if binary_refs:
        logger.debug("Binary refs to scan with strings: %s", binary_refs)
        if debug:
            print(f"      [DEBUG] Binary refs to scan with strings: {binary_refs}")
        binary_matches, binary_v2_aware = scan_binary_strings(
            extract_path=extract_path,
            binary_refs=binary_refs,
            debug=debug,
        )
        all_matches.extend(binary_matches)
        if binary_v2_aware:
            v2_aware = True

    return all_matches, v2_aware
