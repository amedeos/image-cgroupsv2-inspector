"""
System Checks Module
Verifies system requirements for the image inspector tool.
"""

import shutil
import subprocess


def check_podman_installed() -> tuple[bool, str]:
    """
    Check if podman is installed and accessible.

    Returns:
        Tuple of (success, message with version or error)
    """
    try:
        # Check if podman is in PATH
        podman_path = shutil.which("podman")
        if not podman_path:
            return False, "podman not found in PATH. Please install podman."

        # Get podman version
        result = subprocess.run(["podman", "--version"], capture_output=True, text=True)

        if result.returncode != 0:
            return False, f"podman found but failed to get version: {result.stderr}"

        version = result.stdout.strip()
        return True, f"podman is installed: {version}"

    except Exception as e:
        return False, f"Error checking podman: {e}"


def check_podman_running() -> tuple[bool, str]:
    """
    Check if podman can run containers (basic functionality test).

    Returns:
        Tuple of (success, message)
    """
    try:
        result = subprocess.run(["podman", "info", "--format", "json"], capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return False, f"podman info failed: {result.stderr.strip()}"

        import json

        try:
            info = json.loads(result.stdout)
            host_os = info.get("host", {}).get("os", "unknown")
            return True, f"podman is functional (OS: {host_os})"
        except json.JSONDecodeError:
            return True, "podman is functional"

    except subprocess.TimeoutExpired:
        return False, "podman info timed out"
    except Exception as e:
        return False, f"Error testing podman: {e}"


def check_strings_installed() -> tuple[bool, str]:
    """
    Check if the ``strings`` utility (from binutils) is installed and accessible.

    Returns:
        Tuple of (success, message with version or error)
    """
    try:
        strings_path = shutil.which("strings")
        if not strings_path:
            return False, "strings not found in PATH. Please install binutils."

        result = subprocess.run(
            ["strings", "--version"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return False, f"strings found but failed to get version: {result.stderr}"

        first_line = (result.stdout or result.stderr).strip().splitlines()[0]
        return True, f"strings is installed: {first_line}"

    except Exception as e:
        return False, f"Error checking strings: {e}"


def run_system_checks(verbose: bool = False, deep_scan: bool = False) -> bool:
    """
    Run all system checks required for the tool to function.

    Args:
        verbose: If True, print detailed output.
        deep_scan: If True, also verify the ``strings`` utility is available.

    Returns:
        True if all checks pass, False otherwise.
    """
    print("\n🔍 Running system checks...")
    all_passed = True

    # Check podman
    podman_installed, msg = check_podman_installed()
    if podman_installed:
        print(f"✓ {msg}")

        if verbose:
            podman_running, run_msg = check_podman_running()
            if podman_running:
                print(f"✓ {run_msg}")
            else:
                print(f"⚠ {run_msg}")
    else:
        print(f"✗ {msg}")
        all_passed = False

    # Check strings (only needed for --deep-scan)
    if deep_scan:
        strings_installed, msg = check_strings_installed()
        if strings_installed:
            print(f"✓ {msg}")
        else:
            print(f"✗ {msg}")
            all_passed = False

    return all_passed
