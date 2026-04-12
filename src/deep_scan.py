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


def run_deep_scan(
    extract_path: Path,
    image_name: str,
    debug: bool = False,
) -> list:
    """Run all deep-scan heuristics on an extracted container rootfs.

    This is the main entry point called by ImageAnalyzer when --deep-scan
    is enabled. Currently returns an empty list; steps 3 and 4 will add
    the actual entrypoint and binary scanning logic.

    Args:
        extract_path: Path to the extracted container rootfs.
        image_name: Image name (for debug logging).
        debug: Enable debug output.

    Returns:
        List of DeepScanMatch objects (from image_analyzer module).
    """
    if debug:
        print(f"      [DEBUG] Deep scan enabled for {image_name}")
        print(f"      [DEBUG] Extract path: {extract_path}")
        print(f"      [DEBUG] Loaded {len(_PATTERN_STRINGS)} cgroup v1 patterns")
    return []
