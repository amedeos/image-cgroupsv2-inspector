"""Tests for the deep_scan module — cgroup v1 pattern registry and matching."""

import pytest

from src.deep_scan import (
    CGROUPV1_CONTROLLER_DIRS,
    CGROUPV1_FILE_NAMES,
    CGROUPV1_REGEX,
    find_cgroupv1_patterns,
    run_deep_scan,
)


class TestCgroupV1Patterns:
    """Verify pattern constants are well-formed."""

    def test_controller_dirs_end_with_slash(self):
        for d in CGROUPV1_CONTROLLER_DIRS:
            assert d.endswith("/"), f"{d} should end with /"

    def test_controller_dirs_start_with_sys(self):
        for d in CGROUPV1_CONTROLLER_DIRS:
            assert d.startswith("/sys/fs/cgroup/"), f"{d} should start with /sys/fs/cgroup/"

    def test_file_names_no_slashes(self):
        for f in CGROUPV1_FILE_NAMES:
            assert "/" not in f, f"{f} should not contain slashes"

    def test_no_duplicates_in_dirs(self):
        assert len(CGROUPV1_CONTROLLER_DIRS) == len(set(CGROUPV1_CONTROLLER_DIRS))

    def test_no_duplicates_in_files(self):
        assert len(CGROUPV1_FILE_NAMES) == len(set(CGROUPV1_FILE_NAMES))


class TestCgroupV1Regex:
    """Verify the compiled regex matches expected patterns."""

    @pytest.mark.parametrize("pattern", [
        "/sys/fs/cgroup/memory/",
        "/sys/fs/cgroup/cpu/",
        "/sys/fs/cgroup/cpuacct/",
        "/sys/fs/cgroup/blkio/",
        "memory.limit_in_bytes",
        "cpu.cfs_quota_us",
        "cpuacct.usage",
        "blkio.weight",
    ])
    def test_matches_v1_patterns(self, pattern):
        assert CGROUPV1_REGEX.search(pattern) is not None

    @pytest.mark.parametrize("text", [
        "memory.max",           # cgroup v2
        "cpu.max",              # cgroup v2
        "io.max",               # cgroup v2
        "/sys/fs/cgroup/",      # just the base dir, not v1-specific
        "cgroup.controllers",   # cgroup v2
        "cgroup.subtree_control",  # cgroup v2
        "some random text",
    ])
    def test_does_not_match_v2_or_generic(self, text):
        assert CGROUPV1_REGEX.search(text) is None


class TestFindCgroupV1Patterns:
    """Tests for find_cgroupv1_patterns()."""

    def test_empty_string(self):
        assert find_cgroupv1_patterns("") == []

    def test_single_match(self):
        text = 'cat /sys/fs/cgroup/memory/memory.limit_in_bytes'
        result = find_cgroupv1_patterns(text)
        assert "/sys/fs/cgroup/memory/" in result
        assert "memory.limit_in_bytes" in result

    def test_multiple_matches_deduplicated(self):
        text = """
        MEM=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes)
        MEM2=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes)
        """
        result = find_cgroupv1_patterns(text)
        assert result.count("memory.limit_in_bytes") == 1
        assert result.count("/sys/fs/cgroup/memory/") == 1

    def test_mixed_v1_and_v2(self):
        text = """
        # v1 path
        cat /sys/fs/cgroup/memory/memory.limit_in_bytes
        # v2 path
        cat /sys/fs/cgroup/memory.max
        """
        result = find_cgroupv1_patterns(text)
        assert "memory.limit_in_bytes" in result
        assert "memory.max" not in result

    def test_entrypoint_script_realistic(self):
        """Simulate a real entrypoint script with cgroup v1 references."""
        script = """#!/bin/bash
MEM_LIMIT=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || echo "0")
CPU_QUOTA=$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || echo "-1")
CPU_PERIOD=$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us 2>/dev/null || echo "100000")
CPU_SHARES=$(cat /sys/fs/cgroup/cpu/cpu.shares 2>/dev/null || echo "1024")
exec "$@"
"""
        result = find_cgroupv1_patterns(script)
        assert "memory.limit_in_bytes" in result
        assert "cpu.cfs_quota_us" in result
        assert "cpu.cfs_period_us" in result
        assert "cpu.shares" in result
        assert "/sys/fs/cgroup/memory/" in result
        assert "/sys/fs/cgroup/cpu/" in result

    def test_go_binary_strings_realistic(self):
        """Simulate output from strings on a Go binary."""
        strings_output = """
/sys/fs/cgroup/memory/memory.limit_in_bytes
/sys/fs/cgroup/memory/memory.usage_in_bytes
/sys/fs/cgroup/cpu/cpu.cfs_quota_us
/sys/fs/cgroup/cpu/cpu.cfs_period_us
/sys/fs/cgroup/cpuacct/cpuacct.usage
runtime.goexit
"""
        result = find_cgroupv1_patterns(strings_output)
        assert len(result) >= 5

    def test_no_false_positive_on_v2_paths(self):
        """Ensure v2-only files don't trigger matches."""
        v2_content = """
cat /sys/fs/cgroup/memory.max
cat /sys/fs/cgroup/cpu.max
cat /sys/fs/cgroup/io.max
cat /sys/fs/cgroup/cgroup.controllers
"""
        assert find_cgroupv1_patterns(v2_content) == []


class TestRunDeepScan:
    """Tests for run_deep_scan() skeleton."""

    def test_returns_empty_list(self, tmp_path):
        """Skeleton returns empty list (actual logic in steps 3+4)."""
        result = run_deep_scan(
            extract_path=tmp_path,
            image_name="test:latest",
            debug=False,
        )
        assert result == []

    def test_debug_does_not_crash(self, tmp_path):
        """Debug mode should not raise exceptions."""
        result = run_deep_scan(
            extract_path=tmp_path,
            image_name="test:latest",
            debug=True,
        )
        assert result == []
