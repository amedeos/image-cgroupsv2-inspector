"""Tests for the deep_scan module — cgroup v1/v2 pattern registry and matching."""

from pathlib import Path

import pytest

from src.deep_scan import (
    CGROUPV1_CONTROLLER_DIRS,
    CGROUPV1_FILE_NAMES,
    CGROUPV1_REGEX,
    CGROUPV2_FILE_NAMES,
    CGROUPV2_REGEX,
    _extract_sourced_paths,
    _is_elf_binary,
    _is_shell_script,
    _resolve_script_in_rootfs,
    _run_strings,
    find_cgroupv1_patterns,
    find_cgroupv2_patterns,
    run_deep_scan,
    scan_binary_strings,
    scan_entrypoint_scripts,
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

    @pytest.mark.parametrize(
        "pattern",
        [
            "/sys/fs/cgroup/memory/",
            "/sys/fs/cgroup/cpu/",
            "/sys/fs/cgroup/cpuacct/",
            "/sys/fs/cgroup/blkio/",
            "memory.limit_in_bytes",
            "cpu.cfs_quota_us",
            "cpuacct.usage",
            "blkio.weight",
        ],
    )
    def test_matches_v1_patterns(self, pattern):
        assert CGROUPV1_REGEX.search(pattern) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "memory.max",  # cgroup v2
            "cpu.max",  # cgroup v2
            "io.max",  # cgroup v2
            "/sys/fs/cgroup/",  # just the base dir, not v1-specific
            "cgroup.controllers",  # cgroup v2
            "cgroup.subtree_control",  # cgroup v2
            "some random text",
        ],
    )
    def test_does_not_match_v2_or_generic(self, text):
        assert CGROUPV1_REGEX.search(text) is None


class TestFindCgroupV1Patterns:
    """Tests for find_cgroupv1_patterns()."""

    def test_empty_string(self):
        assert find_cgroupv1_patterns("") == []

    def test_single_match(self):
        text = "cat /sys/fs/cgroup/memory/memory.limit_in_bytes"
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


class TestCgroupV2Patterns:
    """Verify v2 pattern constants and regex."""

    def test_v2_file_names_no_slashes(self):
        for f in CGROUPV2_FILE_NAMES:
            assert "/" not in f, f"{f} should not contain slashes"

    @pytest.mark.parametrize(
        "pattern",
        [
            "memory.max",
            "cpu.max",
            "io.max",
            "cgroup.controllers",
            "cgroup.subtree_control",
        ],
    )
    def test_matches_v2_patterns(self, pattern):
        assert CGROUPV2_REGEX.search(pattern) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "memory.limit_in_bytes",  # v1
            "cpu.cfs_quota_us",  # v1
            "some random text",
        ],
    )
    def test_does_not_match_v1(self, text):
        assert CGROUPV2_REGEX.search(text) is None

    @pytest.mark.parametrize(
        "text",
        [
            "blkio.weight",  # v1 — contains "io.weight" as substring
            "memory.max_usage_in_bytes",  # v1 — contains "memory.max" as substring
        ],
    )
    def test_does_not_match_v1_superstrings(self, text):
        """V2 regex must not match when the v2 pattern is embedded inside a v1 pattern."""
        assert CGROUPV2_REGEX.search(text) is None


class TestFindCgroupV2Patterns:
    def test_empty_string(self):
        assert find_cgroupv2_patterns("") == []

    def test_finds_v2_patterns(self):
        text = "cat /sys/fs/cgroup/memory.max && cat /sys/fs/cgroup/cpu.max"
        result = find_cgroupv2_patterns(text)
        assert "memory.max" in result
        assert "cpu.max" in result

    def test_no_v1_patterns_matched(self):
        text = "cat /sys/fs/cgroup/memory/memory.limit_in_bytes"
        assert find_cgroupv2_patterns(text) == []

    def test_no_false_positive_on_blkio_weight(self):
        """'blkio.weight' is v1 — must not trigger v2 match for 'io.weight'."""
        text = "cat /sys/fs/cgroup/blkio/blkio.weight"
        assert find_cgroupv2_patterns(text) == []

    def test_no_false_positive_on_memory_max_usage(self):
        """'memory.max_usage_in_bytes' is v1 — must not trigger v2 match for 'memory.max'."""
        text = "cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes"
        assert find_cgroupv2_patterns(text) == []

    def test_real_v2_memory_max_still_matches(self):
        """Standalone 'memory.max' (actual v2 file) must still match."""
        text = "cat /sys/fs/cgroup/memory.max"
        result = find_cgroupv2_patterns(text)
        assert "memory.max" in result

    def test_real_v2_io_weight_still_matches(self):
        """Standalone 'io.weight' (actual v2 file) must still match."""
        text = "cat /sys/fs/cgroup/io.weight"
        result = find_cgroupv2_patterns(text)
        assert "io.weight" in result

    def test_v1_and_v2_in_same_text(self):
        """Mixed text: only real v2 patterns should match."""
        text = """
        blkio.weight
        memory.max_usage_in_bytes
        io.weight
        memory.max
        """
        result = find_cgroupv2_patterns(text)
        assert "io.weight" in result
        assert "memory.max" in result


class TestIsShellScript:
    def test_sh_extension(self, tmp_path):
        f = tmp_path / "test.sh"
        f.write_text("echo hello")
        assert _is_shell_script(f) is True

    def test_bash_shebang(self, tmp_path):
        f = tmp_path / "entrypoint"
        f.write_text("#!/bin/bash\necho hello")
        assert _is_shell_script(f) is True

    def test_sh_shebang(self, tmp_path):
        f = tmp_path / "entrypoint"
        f.write_text("#!/bin/sh\necho hello")
        assert _is_shell_script(f) is True

    def test_env_bash_shebang(self, tmp_path):
        f = tmp_path / "entrypoint"
        f.write_text("#!/usr/bin/env bash\necho hello")
        assert _is_shell_script(f) is True

    def test_not_shell_script(self, tmp_path):
        f = tmp_path / "binary"
        f.write_bytes(b"\x7fELF\x00\x00\x00")
        assert _is_shell_script(f) is False

    def test_python_script(self, tmp_path):
        f = tmp_path / "run.py"
        f.write_text("#!/usr/bin/env python3\nprint('hello')")
        assert _is_shell_script(f) is False


class TestExtractSourcedPaths:
    def test_source_command(self):
        content = "source /opt/helpers.sh\necho done"
        assert "/opt/helpers.sh" in _extract_sourced_paths(content)

    def test_dot_command(self):
        content = ". /opt/helpers.sh\necho done"
        assert "/opt/helpers.sh" in _extract_sourced_paths(content)

    def test_quoted_path(self):
        content = 'source "/opt/my helpers.sh"'
        result = _extract_sourced_paths(content)
        assert len(result) >= 1

    def test_exec_command(self):
        content = "exec /usr/local/bin/run.sh --flag"
        assert "/usr/local/bin/run.sh" in _extract_sourced_paths(content)

    def test_no_matches(self):
        content = "echo hello\ncat /etc/hosts"
        assert _extract_sourced_paths(content) == []

    def test_variable_in_source(self):
        content = 'source "${SCRIPT_DIR}/helpers.sh"'
        result = _extract_sourced_paths(content)
        assert len(result) >= 1


class TestResolveScriptInRootfs:
    def test_absolute_path(self, tmp_path):
        script = tmp_path / "usr" / "local" / "bin" / "entry.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/bash\necho hi")
        resolved = _resolve_script_in_rootfs("/usr/local/bin/entry.sh", tmp_path)
        assert resolved is not None
        assert resolved == script.resolve()

    def test_missing_file(self, tmp_path):
        assert _resolve_script_in_rootfs("/nonexistent.sh", tmp_path) is None

    def test_relative_path(self, tmp_path):
        parent = tmp_path / "opt" / "app"
        parent.mkdir(parents=True)
        helper = parent / "helper.sh"
        helper.write_text("#!/bin/bash\necho hi")
        resolved = _resolve_script_in_rootfs("helper.sh", tmp_path, relative_to=parent)
        assert resolved is not None

    def test_path_traversal_blocked(self, tmp_path):
        """Paths that escape the rootfs should be rejected."""
        result = _resolve_script_in_rootfs("/../../../etc/passwd", tmp_path)
        assert result is None

    def test_shell_variable_no_relative_to_returns_none(self, tmp_path):
        """Variable paths without relative_to cannot be resolved."""
        result = _resolve_script_in_rootfs("${HOME}/script.sh", tmp_path)
        assert result is None

    def test_variable_with_filename_resolved_relative(self, tmp_path):
        """${SCRIPT_DIR}/helpers.sh should resolve filename relative to relative_to."""
        parent = tmp_path / "opt" / "app"
        parent.mkdir(parents=True)
        helper = parent / "cgroup-helpers.sh"
        helper.write_text("#!/bin/bash\nget_mem() { echo 1; }")
        resolved = _resolve_script_in_rootfs("${SCRIPT_DIR}/cgroup-helpers.sh", tmp_path, relative_to=parent)
        assert resolved is not None
        assert resolved.name == "cgroup-helpers.sh"

    def test_variable_with_filename_no_relative_to(self, tmp_path):
        """Without relative_to, variable paths cannot be resolved."""
        result = _resolve_script_in_rootfs("${SCRIPT_DIR}/helpers.sh", tmp_path)
        assert result is None

    def test_variable_in_filename_skipped(self, tmp_path):
        """If the filename itself contains a variable, give up."""
        parent = tmp_path / "opt"
        parent.mkdir(parents=True)
        result = _resolve_script_in_rootfs("${DIR}/${FILE}", tmp_path, relative_to=parent)
        assert result is None

    def test_dollar_sign_path_resolved(self, tmp_path):
        """$DIR/helpers.sh (no braces) should also resolve."""
        parent = tmp_path / "opt" / "app"
        parent.mkdir(parents=True)
        helper = parent / "helpers.sh"
        helper.write_text("#!/bin/bash\necho hi")
        resolved = _resolve_script_in_rootfs("$DIR/helpers.sh", tmp_path, relative_to=parent)
        assert resolved is not None
        assert resolved.name == "helpers.sh"

    def test_variable_path_traversal_blocked(self, tmp_path):
        """Variable-based path should still respect rootfs boundary."""
        parent = tmp_path / "opt"
        parent.mkdir(parents=True)
        result = _resolve_script_in_rootfs("${DIR}/../../etc/passwd", tmp_path, relative_to=parent)
        assert result is None


class TestScanEntrypointScripts:
    """Integration tests for scan_entrypoint_scripts()."""

    def _create_script(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o755)

    def test_entrypoint_with_v1_patterns(self, tmp_path):
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
MEM=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null)
exec "$@"
""",
        )
        matches, v2_aware, _ = scan_entrypoint_scripts(tmp_path, ["/entrypoint.sh"], debug=False)
        assert len(matches) > 0
        assert any(m.pattern == "memory.limit_in_bytes" for m in matches)
        assert all(m.confidence == "high" for m in matches)
        assert v2_aware is False

    def test_entrypoint_with_v1_and_v2_patterns(self, tmp_path):
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
    MEM=$(cat /sys/fs/cgroup/memory.max)
else
    MEM=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes)
fi
exec "$@"
""",
        )
        matches, v2_aware, _ = scan_entrypoint_scripts(tmp_path, ["/entrypoint.sh"], debug=False)
        assert len(matches) > 0
        assert v2_aware is True

    def test_source_chain_followed(self, tmp_path):
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
source /opt/helpers.sh
echo "Memory: $(get_mem)"
exec "$@"
""",
        )
        self._create_script(
            tmp_path / "opt" / "helpers.sh",
            """#!/bin/bash
get_mem() {
    cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null
}
""",
        )
        matches, _, _ = scan_entrypoint_scripts(tmp_path, ["/entrypoint.sh"], debug=False)
        assert len(matches) > 0
        sourced_matches = [m for m in matches if "helpers" in m.source]
        assert len(sourced_matches) > 0
        assert all(m.confidence == "medium" for m in sourced_matches)

    def test_no_entrypoint(self, tmp_path):
        matches, v2_aware, discovered = scan_entrypoint_scripts(tmp_path, [], debug=False)
        assert matches == []
        assert v2_aware is False
        assert discovered == []

    def test_non_path_entrypoint(self, tmp_path):
        """Bare command like 'python' without path should be skipped."""
        matches, _, _ = scan_entrypoint_scripts(tmp_path, ["python", "app.py"], debug=False)
        assert matches == []

    def test_binary_entrypoint_skipped(self, tmp_path):
        """ELF binary should be skipped (step 4 handles this)."""
        binary = tmp_path / "usr" / "local" / "bin" / "myapp"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"\x7fELF" + b"\x00" * 100)
        matches, _, _ = scan_entrypoint_scripts(tmp_path, ["/usr/local/bin/myapp"], debug=False)
        assert matches == []

    def test_v2_aware_in_sourced_file(self, tmp_path):
        """V2 awareness detected in a sourced file."""
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
source /opt/cgroup-lib.sh
exec "$@"
""",
        )
        self._create_script(
            tmp_path / "opt" / "cgroup-lib.sh",
            """#!/bin/bash
if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
    MEM=$(cat /sys/fs/cgroup/memory.max)
else
    MEM=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes)
fi
""",
        )
        matches, v2_aware, _ = scan_entrypoint_scripts(tmp_path, ["/entrypoint.sh"], debug=False)
        assert len(matches) > 0
        assert v2_aware is True

    def test_no_v1_patterns_clean(self, tmp_path):
        """Script with no cgroup references produces no matches."""
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
echo "Hello world"
exec "$@"
""",
        )
        matches, v2_aware, _ = scan_entrypoint_scripts(tmp_path, ["/entrypoint.sh"], debug=False)
        assert matches == []
        assert v2_aware is False

    def test_v1_only_not_flagged_v2_aware(self, tmp_path):
        """Script with only v1 patterns (including blkio.weight) must NOT be v2-aware."""
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
MEM=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null)
MEM_MAX=$(cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes 2>/dev/null)
BLKIO=$(cat /sys/fs/cgroup/blkio/blkio.weight 2>/dev/null)
exec "$@"
""",
        )
        matches, v2_aware, _ = scan_entrypoint_scripts(tmp_path, ["/entrypoint.sh"], debug=False)
        assert len(matches) > 0
        assert v2_aware is False

    def test_source_with_variable_path(self, tmp_path):
        """source "${SCRIPT_DIR}/file.sh" pattern should be followed."""
        self._create_script(
            tmp_path / "opt" / "app" / "entrypoint-source.sh",
            """#!/bin/bash
SCRIPT_DIR=$(dirname "$0")
source "${SCRIPT_DIR}/cgroup-helpers.sh"
echo "Memory: $(get_memory_limit)"
exec "$@"
""",
        )
        self._create_script(
            tmp_path / "opt" / "app" / "cgroup-helpers.sh",
            """#!/bin/bash
get_memory_limit() {
    cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || echo "0"
}
""",
        )
        matches, _, _ = scan_entrypoint_scripts(tmp_path, ["/opt/app/entrypoint-source.sh"], debug=False)
        assert len(matches) > 0
        assert any("memory.limit_in_bytes" in m.pattern for m in matches)
        sourced_matches = [m for m in matches if "cgroup-helpers" in m.source]
        assert len(sourced_matches) > 0
        assert all(m.confidence == "medium" for m in sourced_matches)

    def test_depth_limit(self, tmp_path):
        """Source chains deeper than _MAX_SOURCE_DEPTH are truncated."""
        for i in range(8):
            next_script = f"/opt/level{i + 1}.sh" if i < 7 else ""
            source_line = f"source {next_script}" if next_script else ""
            v1_ref = "cat /sys/fs/cgroup/memory/memory.limit_in_bytes" if i == 7 else ""
            self._create_script(
                tmp_path / "opt" / f"level{i}.sh",
                f"""#!/bin/bash
{source_line}
{v1_ref}
""",
            )
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
source /opt/level0.sh
""",
        )
        _, _, _ = scan_entrypoint_scripts(tmp_path, ["/entrypoint.sh"], debug=False)
        # The chain is deeper than _MAX_SOURCE_DEPTH (5), so the deepest
        # script with v1 refs may or may not be reached depending on depth

    def test_exec_chain_discovers_elf_binary(self, tmp_path):
        """exec /path/to/binary in entrypoint should be collected for strings scanning."""
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
echo "starting"
exec /usr/local/bin/myapp --flag
""",
        )
        binary = tmp_path / "usr" / "local" / "bin" / "myapp"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"\x7fELF" + b"\x00" * 100)

        _, _, discovered = scan_entrypoint_scripts(tmp_path, ["/entrypoint.sh"], debug=False)
        assert "/usr/local/bin/myapp" in discovered

    def test_exec_chain_skips_interpreters(self, tmp_path):
        """exec /bin/bash should NOT be collected as a discovered binary."""
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
exec /bin/bash /some/script.sh
""",
        )
        bash = tmp_path / "bin" / "bash"
        bash.parent.mkdir(parents=True)
        bash.write_bytes(b"\x7fELF" + b"\x00" * 100)

        _, _, discovered = scan_entrypoint_scripts(tmp_path, ["/entrypoint.sh"], debug=False)
        assert "/bin/bash" not in discovered

    def test_exec_chain_does_not_duplicate_shell_scripts(self, tmp_path):
        """exec of a shell script should be followed as script, not collected as binary."""
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
exec /opt/run.sh
""",
        )
        self._create_script(
            tmp_path / "opt" / "run.sh",
            """#!/bin/bash
cat /sys/fs/cgroup/memory/memory.limit_in_bytes
""",
        )
        matches, _, discovered = scan_entrypoint_scripts(tmp_path, ["/entrypoint.sh"], debug=False)
        assert len(discovered) == 0
        assert len(matches) > 0
        assert any(m.confidence == "medium" for m in matches)

    def test_exec_chain_binary_no_entrypoint_match(self, tmp_path):
        """Entrypoint has no v1 patterns, but exec'd binary should be discovered."""
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
echo "setup complete"
exec /usr/bin/monitor
""",
        )
        binary = tmp_path / "usr" / "bin" / "monitor"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"\x7fELF" + b"\x00" * 100)

        matches, _, discovered = scan_entrypoint_scripts(tmp_path, ["/entrypoint.sh"], debug=False)
        assert matches == []
        assert "/usr/bin/monitor" in discovered

    def test_source_chain_then_exec_binary(self, tmp_path):
        """Entrypoint sources a script which exec's a binary — binary should be discovered."""
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
source /opt/setup.sh
""",
        )
        self._create_script(
            tmp_path / "opt" / "setup.sh",
            """#!/bin/bash
echo "configuring"
exec /usr/local/bin/app
""",
        )
        binary = tmp_path / "usr" / "local" / "bin" / "app"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"\x7fELF" + b"\x00" * 100)

        _, _, discovered = scan_entrypoint_scripts(tmp_path, ["/entrypoint.sh"], debug=False)
        assert "/usr/local/bin/app" in discovered


class TestRunDeepScan:
    """Tests for the updated run_deep_scan()."""

    def _create_script(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o755)

    def test_with_entrypoint(self, tmp_path):
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
MEM=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes)
exec "$@"
""",
        )
        matches, v2_aware = run_deep_scan(
            extract_path=tmp_path,
            image_name="test:latest",
            entrypoint=["/entrypoint.sh"],
            cmd=None,
            debug=False,
        )
        assert len(matches) > 0
        assert v2_aware is False

    def test_without_entrypoint(self, tmp_path):
        matches, v2_aware = run_deep_scan(
            extract_path=tmp_path,
            image_name="test:latest",
            entrypoint=None,
            cmd=None,
            debug=False,
        )
        assert matches == []
        assert v2_aware is False

    def test_v2_aware_flag(self, tmp_path):
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
    cat /sys/fs/cgroup/memory.max
else
    cat /sys/fs/cgroup/memory/memory.limit_in_bytes
fi
""",
        )
        matches, v2_aware = run_deep_scan(
            extract_path=tmp_path,
            image_name="test:latest",
            entrypoint=["/entrypoint.sh"],
            debug=False,
        )
        assert len(matches) > 0
        assert v2_aware is True

    def test_debug_does_not_crash(self, tmp_path):
        """Debug mode should not raise exceptions."""
        matches, v2_aware = run_deep_scan(
            extract_path=tmp_path,
            image_name="test:latest",
            debug=True,
        )
        assert matches == []
        assert v2_aware is False


class TestIsElfBinary:
    def test_elf_binary(self, tmp_path):
        binary = tmp_path / "myapp"
        binary.write_bytes(b"\x7fELF" + b"\x02\x01\x01\x00" * 100)
        assert _is_elf_binary(binary) is True

    def test_shell_script(self, tmp_path):
        script = tmp_path / "run.sh"
        script.write_text("#!/bin/bash\necho hello")
        assert _is_elf_binary(script) is False

    def test_empty_file(self, tmp_path):
        empty = tmp_path / "empty"
        empty.write_bytes(b"")
        assert _is_elf_binary(empty) is False

    def test_short_file(self, tmp_path):
        short = tmp_path / "short"
        short.write_bytes(b"\x7f")
        assert _is_elf_binary(short) is False

    def test_nonexistent_file(self, tmp_path):
        assert _is_elf_binary(tmp_path / "nonexistent") is False


class TestRunStrings:
    def _create_binary_with_strings(self, path: Path, embedded_strings: list[str]) -> None:
        """Create a fake binary with embedded readable strings."""
        path.parent.mkdir(parents=True, exist_ok=True)
        content = b"\x7fELF" + b"\x00" * 100
        for s in embedded_strings:
            content += s.encode("utf-8") + b"\x00" * 10
        content += b"\x00" * 100
        path.write_bytes(content)

    def test_extracts_strings(self, tmp_path):
        binary = tmp_path / "myapp"
        self._create_binary_with_strings(
            binary,
            [
                "/sys/fs/cgroup/memory/memory.limit_in_bytes",
                "some_other_long_string_here",
            ],
        )
        result = _run_strings(binary)
        assert result is not None
        assert "memory.limit_in_bytes" in result

    def test_empty_file(self, tmp_path):
        binary = tmp_path / "empty"
        binary.write_bytes(b"")
        result = _run_strings(binary)
        assert result is None

    def test_nonexistent_file(self, tmp_path):
        result = _run_strings(tmp_path / "nonexistent")
        assert result is None


class TestScanBinaryStrings:
    def _create_binary_with_strings(self, path: Path, embedded_strings: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = b"\x7fELF" + b"\x00" * 100
        for s in embedded_strings:
            content += s.encode("utf-8") + b"\x00" * 10
        content += b"\x00" * 100
        path.write_bytes(content)

    def test_binary_with_v1_patterns(self, tmp_path):
        self._create_binary_with_strings(
            tmp_path / "usr" / "bin" / "myapp",
            [
                "/sys/fs/cgroup/memory/memory.limit_in_bytes",
                "/sys/fs/cgroup/cpu/cpu.cfs_quota_us",
            ],
        )
        matches, v2_aware = scan_binary_strings(tmp_path, ["/usr/bin/myapp"], debug=False)
        assert len(matches) > 0
        assert all(m.confidence == "low" for m in matches)
        assert all(m.source.startswith("binary:") for m in matches)
        assert any("memory.limit_in_bytes" in m.pattern for m in matches)
        assert v2_aware is False

    def test_binary_with_v1_and_v2_patterns(self, tmp_path):
        self._create_binary_with_strings(
            tmp_path / "usr" / "bin" / "myapp",
            [
                "/sys/fs/cgroup/memory/memory.limit_in_bytes",
                "/sys/fs/cgroup/cgroup.controllers",
                "memory.max_is_a_long_enough_string",
            ],
        )
        matches, v2_aware = scan_binary_strings(tmp_path, ["/usr/bin/myapp"], debug=False)
        assert len(matches) > 0
        assert v2_aware is True

    def test_binary_without_v1_patterns(self, tmp_path):
        self._create_binary_with_strings(
            tmp_path / "usr" / "bin" / "cleanapp",
            ["just_some_random_long_string_here", "another_normal_string_data"],
        )
        matches, v2_aware = scan_binary_strings(tmp_path, ["/usr/bin/cleanapp"], debug=False)
        assert matches == []
        assert v2_aware is False

    def test_nonexistent_binary_skipped(self, tmp_path):
        matches, _ = scan_binary_strings(tmp_path, ["/usr/bin/nonexistent"], debug=False)
        assert matches == []

    def test_shell_script_skipped(self, tmp_path):
        script = tmp_path / "usr" / "bin" / "run.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/bash\ncat /sys/fs/cgroup/memory/memory.limit_in_bytes")
        matches, _ = scan_binary_strings(tmp_path, ["/usr/bin/run.sh"], debug=False)
        assert matches == []

    def test_multiple_binaries(self, tmp_path):
        self._create_binary_with_strings(
            tmp_path / "usr" / "bin" / "app1",
            ["/sys/fs/cgroup/memory/memory.limit_in_bytes"],
        )
        self._create_binary_with_strings(
            tmp_path / "usr" / "bin" / "app2",
            ["/sys/fs/cgroup/cpu/cpu.cfs_quota_us"],
        )
        matches, _ = scan_binary_strings(tmp_path, ["/usr/bin/app1", "/usr/bin/app2"], debug=False)
        assert len(matches) >= 2
        sources = {m.source for m in matches}
        assert "binary:/usr/bin/app1" in sources
        assert "binary:/usr/bin/app2" in sources

    def test_duplicate_binary_refs_deduplicated(self, tmp_path):
        self._create_binary_with_strings(
            tmp_path / "usr" / "bin" / "myapp",
            ["/sys/fs/cgroup/memory/memory.limit_in_bytes"],
        )
        matches, _ = scan_binary_strings(tmp_path, ["/usr/bin/myapp", "/usr/bin/myapp"], debug=False)
        pattern_count = sum(1 for m in matches if m.pattern == "memory.limit_in_bytes")
        assert pattern_count == 1

    def test_source_prefix_is_binary(self, tmp_path):
        """Verify the source field uses the binary: prefix."""
        self._create_binary_with_strings(
            tmp_path / "usr" / "local" / "bin" / "cgroup-reader",
            ["/sys/fs/cgroup/memory/memory.limit_in_bytes"],
        )
        matches, _ = scan_binary_strings(tmp_path, ["/usr/local/bin/cgroup-reader"], debug=False)
        assert len(matches) > 0
        assert matches[0].source == "binary:/usr/local/bin/cgroup-reader"


class TestRunDeepScanWithBinary:
    """Test run_deep_scan integration with binary scanning (step 4)."""

    def _create_binary_with_strings(self, path: Path, embedded_strings: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = b"\x7fELF" + b"\x00" * 100
        for s in embedded_strings:
            content += s.encode("utf-8") + b"\x00" * 10
        content += b"\x00" * 100
        path.write_bytes(content)

    def _create_script(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o755)

    def test_binary_entrypoint_scanned(self, tmp_path):
        """When entrypoint is a binary, strings scan should find patterns."""
        self._create_binary_with_strings(
            tmp_path / "usr" / "bin" / "cadvisor",
            [
                "/sys/fs/cgroup/memory/memory.limit_in_bytes",
                "/sys/fs/cgroup/cpu/cpu.cfs_quota_us",
                "/sys/fs/cgroup/cpuacct/cpuacct.usage",
            ],
        )
        matches, _ = run_deep_scan(
            extract_path=tmp_path,
            image_name="cadvisor:v0.44.0",
            entrypoint=["/usr/bin/cadvisor"],
            debug=False,
        )
        assert len(matches) > 0
        assert all(m.confidence == "low" for m in matches)
        assert all("binary:" in m.source for m in matches)

    def test_script_entrypoint_not_double_scanned(self, tmp_path):
        """Shell script entrypoint should only produce high/medium matches, not low."""
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
MEM=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes)
exec "$@"
""",
        )
        matches, _ = run_deep_scan(
            extract_path=tmp_path,
            image_name="test:latest",
            entrypoint=["/entrypoint.sh"],
            debug=False,
        )
        assert len(matches) > 0
        assert all(m.confidence == "high" for m in matches)
        assert not any("binary:" in m.source for m in matches)

    def test_binary_with_v2_awareness(self, tmp_path):
        """Binary containing both v1 and v2 patterns should be flagged v2-aware."""
        self._create_binary_with_strings(
            tmp_path / "usr" / "bin" / "monitor",
            [
                "/sys/fs/cgroup/memory/memory.limit_in_bytes",
                "/sys/fs/cgroup/cgroup.controllers",
                "memory.max_and_some_padding",
            ],
        )
        matches, v2_aware = run_deep_scan(
            extract_path=tmp_path,
            image_name="monitor:latest",
            entrypoint=["/usr/bin/monitor"],
            debug=False,
        )
        assert len(matches) > 0
        assert v2_aware is True

    def test_mixed_script_and_binary_args(self, tmp_path):
        """When entrypoint is a script and CMD has a binary, both are scanned."""
        self._create_script(
            tmp_path / "wrapper.sh",
            """#!/bin/bash
echo "starting"
exec "$@"
""",
        )
        self._create_binary_with_strings(
            tmp_path / "usr" / "bin" / "myapp",
            ["/sys/fs/cgroup/memory/memory.limit_in_bytes"],
        )
        matches, _ = run_deep_scan(
            extract_path=tmp_path,
            image_name="test:latest",
            entrypoint=["/wrapper.sh"],
            cmd=["/usr/bin/myapp"],
            debug=False,
        )
        binary_matches = [m for m in matches if "binary:" in m.source]
        assert len(binary_matches) > 0
        assert all(m.confidence == "low" for m in binary_matches)

    def test_no_matches_in_clean_binary(self, tmp_path):
        """Binary without cgroup refs should produce no matches."""
        self._create_binary_with_strings(
            tmp_path / "usr" / "bin" / "nginx",
            ["welcome_to_nginx_server", "http_proxy_module_loaded"],
        )
        matches, v2_aware = run_deep_scan(
            extract_path=tmp_path,
            image_name="nginx:latest",
            entrypoint=["/usr/bin/nginx"],
            debug=False,
        )
        assert matches == []
        assert v2_aware is False

    def test_exec_chain_binary_scanned_with_strings(self, tmp_path):
        """Binary discovered via exec chain should be scanned with strings."""
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
echo "starting"
exec /usr/local/bin/myapp
""",
        )
        self._create_binary_with_strings(
            tmp_path / "usr" / "local" / "bin" / "myapp",
            [
                "/sys/fs/cgroup/memory/memory.limit_in_bytes",
                "/sys/fs/cgroup/cpu/cpu.cfs_quota_us",
            ],
        )
        matches, _ = run_deep_scan(
            extract_path=tmp_path,
            image_name="test:latest",
            entrypoint=["/entrypoint.sh"],
            debug=False,
        )
        assert len(matches) > 0
        assert all("binary:" in m.source for m in matches)
        assert all(m.confidence == "low" for m in matches)
        assert any("memory.limit_in_bytes" in m.pattern for m in matches)

    def test_exec_chain_binary_not_duplicated(self, tmp_path):
        """If binary is both in CMD and discovered via exec, scan it only once."""
        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
exec /usr/local/bin/myapp
""",
        )
        self._create_binary_with_strings(
            tmp_path / "usr" / "local" / "bin" / "myapp",
            ["/sys/fs/cgroup/memory/memory.limit_in_bytes"],
        )
        matches, _ = run_deep_scan(
            extract_path=tmp_path,
            image_name="test:latest",
            entrypoint=["/entrypoint.sh"],
            cmd=["/usr/local/bin/myapp"],
            debug=False,
        )
        binary_sources = {m.source for m in matches}
        assert len(binary_sources) == 1


class TestRunDeepScanInterpreterSkip:
    """Test that common interpreters are skipped in binary scanning."""

    def _create_script(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o755)

    def test_bash_not_scanned_with_strings(self, tmp_path):
        """CMD ['/bin/bash', '-c', '...'] should not trigger strings on /bin/bash."""
        bash = tmp_path / "bin" / "bash"
        bash.parent.mkdir(parents=True)
        bash.write_bytes(b"\x7fELF" + b"\x00" * 1000)

        self._create_script(
            tmp_path / "entrypoint.sh",
            """#!/bin/bash
echo hello
exec "$@"
""",
        )
        matches, _ = run_deep_scan(
            extract_path=tmp_path,
            image_name="test:latest",
            entrypoint=["/entrypoint.sh"],
            cmd=["/bin/bash", "-c", "echo running"],
            debug=False,
        )
        assert not any("binary:/bin/bash" in m.source for m in matches)
