"""Tests for the system_checks module."""

from unittest.mock import MagicMock, patch

from src.system_checks import (
    check_strings_installed,
    run_system_checks,
)


class TestCheckStringsInstalled:
    """Tests for check_strings_installed()."""

    def test_strings_found(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "GNU strings version 2.40\n"
        mock_result.stderr = ""

        with patch("src.system_checks.shutil.which", return_value="/usr/bin/strings"), \
             patch("src.system_checks.subprocess.run", return_value=mock_result):
            ok, msg = check_strings_installed()
            assert ok is True
            assert "strings is installed" in msg

    def test_strings_not_in_path(self):
        with patch("src.system_checks.shutil.which", return_value=None):
            ok, msg = check_strings_installed()
            assert ok is False
            assert "not found in PATH" in msg

    def test_strings_version_fails(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "some error"

        with patch("src.system_checks.shutil.which", return_value="/usr/bin/strings"), \
             patch("src.system_checks.subprocess.run", return_value=mock_result):
            ok, msg = check_strings_installed()
            assert ok is False
            assert "failed to get version" in msg

    def test_strings_exception(self):
        with patch("src.system_checks.shutil.which", side_effect=OSError("boom")):
            ok, msg = check_strings_installed()
            assert ok is False
            assert "Error checking strings" in msg


class TestRunSystemChecks:
    """Tests for run_system_checks() with the deep_scan parameter."""

    def test_deep_scan_false_does_not_check_strings(self):
        with patch("src.system_checks.check_podman_installed", return_value=(True, "podman ok")), \
             patch("src.system_checks.check_strings_installed") as mock_strings:
            result = run_system_checks(deep_scan=False)
            assert result is True
            mock_strings.assert_not_called()

    def test_deep_scan_true_checks_strings(self):
        with patch("src.system_checks.check_podman_installed", return_value=(True, "podman ok")), \
             patch("src.system_checks.check_strings_installed", return_value=(True, "strings ok")):
            result = run_system_checks(deep_scan=True)
            assert result is True

    def test_deep_scan_true_strings_missing_fails(self):
        with patch("src.system_checks.check_podman_installed", return_value=(True, "podman ok")), \
             patch("src.system_checks.check_strings_installed", return_value=(False, "not found")):
            result = run_system_checks(deep_scan=True)
            assert result is False

    def test_podman_missing_still_fails_with_deep_scan(self):
        with patch("src.system_checks.check_podman_installed", return_value=(False, "not found")), \
             patch("src.system_checks.check_strings_installed", return_value=(True, "strings ok")):
            result = run_system_checks(deep_scan=True)
            assert result is False
