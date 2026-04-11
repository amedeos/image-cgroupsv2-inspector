"""Tests for CLI integration — mode routing, argument parsing, registry flow, and #34 bugfix."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Load the main script as a module (it has no .py extension)
# ---------------------------------------------------------------------------

_SCRIPT_PATH = Path(__file__).parent.parent / "image-cgroupsv2-inspector"


def _load_main_module():
    loader = importlib.machinery.SourceFileLoader("main_script", str(_SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("main_script", loader, origin=str(_SCRIPT_PATH))
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(_SCRIPT_PATH)
    spec.loader.exec_module(module)
    return module


main_script = _load_main_module()
parse_arguments = main_script.parse_arguments
main = main_script.main
_print_analysis_summary = main_script._print_analysis_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REGISTRY_BASE_ARGS = [
    "image-cgroupsv2-inspector",
    "--registry-url",
    "https://quay.example.com",
    "--registry-token",
    "tok123",
    "--registry-org",
    "myorg",
]

_OPENSHIFT_BASE_ARGS = [
    "image-cgroupsv2-inspector",
    "--api-url",
    "https://api.cluster.example.com:6443",
    "--token",
    "oc-token",
]


def _sample_images(n=3):
    """Return a list of n sample image dicts with unified schema keys."""
    return [
        {
            "source": "registry",
            "container_name": "",
            "namespace": "",
            "object_type": "",
            "object_name": "",
            "registry_org": "myorg",
            "registry_repo": f"repo{i}",
            "image_name": f"quay.example.com/myorg/repo{i}:latest",
            "image_id": "",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# TestParseArguments
# ---------------------------------------------------------------------------


class TestParseArguments:
    """Test argument parsing for both modes."""

    def test_registry_args_parsed(self):
        with patch("sys.argv", [*_REGISTRY_BASE_ARGS, "--registry-repo", "myapp"]):
            args = parse_arguments()
        assert args.registry_url == "https://quay.example.com"
        assert args.registry_token == "tok123"
        assert args.registry_org == "myorg"
        assert args.registry_repo == "myapp"

    def test_registry_repo_defaults_none(self):
        with patch("sys.argv", _REGISTRY_BASE_ARGS):
            args = parse_arguments()
        assert args.registry_repo is None

    def test_include_exclude_tags_default_none(self):
        with patch("sys.argv", _REGISTRY_BASE_ARGS):
            args = parse_arguments()
        assert args.include_tags is None
        assert args.exclude_tags is None

    def test_latest_only_default_none(self):
        with patch("sys.argv", _REGISTRY_BASE_ARGS):
            args = parse_arguments()
        assert args.latest_only is None

    def test_latest_only_accepts_int(self):
        with patch("sys.argv", [*_REGISTRY_BASE_ARGS, "--latest-only", "5"]):
            args = parse_arguments()
        assert args.latest_only == 5

    def test_version_is_2(self, capsys):
        with patch("sys.argv", ["image-cgroupsv2-inspector", "--version"]), pytest.raises(SystemExit):
            parse_arguments()
        captured = capsys.readouterr()
        assert "2.0.0" in captured.out

    def test_openshift_args_still_work(self):
        with patch(
            "sys.argv",
            [
                *_OPENSHIFT_BASE_ARGS,
                "--namespace",
                "myns",
                "--internal-registry-route",
                "registry.apps.example.com",
            ],
        ):
            args = parse_arguments()
        assert args.api_url == "https://api.cluster.example.com:6443"
        assert args.token == "oc-token"
        assert args.namespace == "myns"
        assert args.internal_registry_route == "registry.apps.example.com"

    def test_shared_args(self):
        with patch(
            "sys.argv",
            [
                *_REGISTRY_BASE_ARGS,
                "--analyze",
                "--rootfs-path",
                "/tmp/rootfs",
                "--pull-secret",
                "/my/secret",
                "--verify-ssl",
                "--verbose",
                "--output-dir",
                "/tmp/out",
                "--skip-disk-check",
            ],
        ):
            args = parse_arguments()
        assert args.analyze is True
        assert args.rootfs_path == "/tmp/rootfs"
        assert args.pull_secret == "/my/secret"
        assert args.verify_ssl is True
        assert args.verbose is True
        assert args.output_dir == "/tmp/out"
        assert args.skip_disk_check is True


# ---------------------------------------------------------------------------
# TestModeRouting
# ---------------------------------------------------------------------------


class TestModeRouting:
    """Test mode detection and mutual exclusion."""

    def test_mutual_exclusion_returns_1(self, capsys):
        test_args = [*_REGISTRY_BASE_ARGS, "--api-url", "https://api.cluster.example.com:6443"]
        with (
            patch("sys.argv", test_args),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
        ):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "mutually exclusive" in captured.out

    def test_registry_url_activates_registry_mode(self, capsys):
        """--registry-url triggers the Quay connection path."""
        mock_quay = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = _sample_images(1)
        mock_collector.save_to_csv.return_value = "/tmp/out/test.csv"

        with (
            patch("sys.argv", _REGISTRY_BASE_ARGS),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "QuayClient", return_value=mock_quay),
            patch.object(main_script, "RegistryCollector", return_value=mock_collector),
        ):
            result = main()
        assert result == 0
        mock_quay.test_connection.assert_called_once()

    def test_no_flags_defaults_to_openshift(self, capsys):
        """Neither --registry-url nor --api-url → OpenShift mode (tries .env)."""
        mock_client = MagicMock()
        mock_client.api_url = ""
        mock_client.token = ""

        with (
            patch("sys.argv", ["image-cgroupsv2-inspector"]),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "OpenShiftClient", return_value=mock_client),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "OpenShift credentials not provided" in captured.out


# ---------------------------------------------------------------------------
# TestRegistryModeValidation
# ---------------------------------------------------------------------------


class TestRegistryModeValidation:
    """Test registry mode input validation."""

    def _run_main_registry(self, extra_args=None, quay_side_effect=None):
        args = list(_REGISTRY_BASE_ARGS)
        if extra_args:
            args.extend(extra_args)

        mock_quay = MagicMock()
        if quay_side_effect:
            mock_quay.test_connection.side_effect = quay_side_effect

        with (
            patch("sys.argv", args),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "QuayClient", return_value=mock_quay),
            patch.object(main_script, "RegistryCollector") as mock_rc,
        ):
            mock_rc.return_value.collect_images.return_value = _sample_images(1)
            mock_rc.return_value.save_to_csv.return_value = "/tmp/out/test.csv"
            return main()

    def test_missing_token_returns_1(self, capsys):
        with (
            patch(
                "sys.argv",
                [
                    "image-cgroupsv2-inspector",
                    "--registry-url",
                    "https://quay.example.com",
                    "--registry-org",
                    "myorg",
                ],
            ),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = main()
        assert result == 1
        assert "registry-token" in capsys.readouterr().out.lower()

    def test_missing_org_returns_1(self, capsys):
        with (
            patch(
                "sys.argv",
                [
                    "image-cgroupsv2-inspector",
                    "--registry-url",
                    "https://quay.example.com",
                    "--registry-token",
                    "tok",
                ],
            ),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = main()
        assert result == 1
        assert "registry-org" in capsys.readouterr().out.lower()

    def test_quay_connection_failure_returns_1(self, capsys):
        from src.quay_client import QuayConnectionError

        result = self._run_main_registry(quay_side_effect=QuayConnectionError("unreachable"))
        assert result == 1
        captured = capsys.readouterr()
        assert "Quay connection error" in captured.out

    def test_org_not_found_returns_1(self, capsys):
        from src.quay_client import QuayNotFoundError

        mock_quay = MagicMock()
        mock_quay.get_organization.side_effect = QuayNotFoundError("not found")

        with (
            patch("sys.argv", _REGISTRY_BASE_ARGS),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "QuayClient", return_value=mock_quay),
        ):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Quay connection error" in captured.out


# ---------------------------------------------------------------------------
# TestRegistryModeEnvVarFallback
# ---------------------------------------------------------------------------


class TestRegistryModeEnvVarFallback:
    """Test environment variable fallback for registry mode."""

    def test_env_url_activates_registry_mode(self, capsys):
        mock_quay = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = _sample_images(1)
        mock_collector.save_to_csv.return_value = "/tmp/out/test.csv"

        env = {
            "QUAY_REGISTRY_URL": "https://quay.example.com",
            "QUAY_REGISTRY_TOKEN": "envtok",
            "QUAY_REGISTRY_ORG": "envorg",
        }
        with (
            patch("sys.argv", ["image-cgroupsv2-inspector"]),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.dict("os.environ", env, clear=True),
            patch.object(main_script, "QuayClient", return_value=mock_quay) as mock_qc_cls,
            patch.object(main_script, "RegistryCollector", return_value=mock_collector),
        ):
            result = main()
        assert result == 0
        mock_qc_cls.assert_called_once()
        call_kwargs = mock_qc_cls.call_args
        assert call_kwargs[1]["token"] == "envtok"

    def test_cli_args_override_env_vars(self, capsys):
        mock_quay = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = _sample_images(1)
        mock_collector.save_to_csv.return_value = "/tmp/out/test.csv"

        env = {
            "QUAY_REGISTRY_URL": "https://old.example.com",
            "QUAY_REGISTRY_TOKEN": "oldtok",
            "QUAY_REGISTRY_ORG": "oldorg",
        }
        with (
            patch("sys.argv", _REGISTRY_BASE_ARGS),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.dict("os.environ", env, clear=True),
            patch.object(main_script, "QuayClient", return_value=mock_quay) as mock_qc_cls,
            patch.object(main_script, "RegistryCollector", return_value=mock_collector),
        ):
            result = main()
        assert result == 0
        call_kwargs = mock_qc_cls.call_args
        assert call_kwargs[1]["base_url"] == "https://quay.example.com"
        assert call_kwargs[1]["token"] == "tok123"


# ---------------------------------------------------------------------------
# TestRegistryModePullSecret  (includes #34 bugfix regression test)
# ---------------------------------------------------------------------------


class TestRegistryModePullSecret:
    """Test pull-secret handling in registry mode, including the #34 bugfix."""

    def _run_analyze(self, extra_args=None, pull_secret_exists=False):
        """Helper: run main() in registry+analyze mode, return mocks."""
        args = [
            *_REGISTRY_BASE_ARGS,
            "--analyze",
            "--rootfs-path",
            "/tmp/rootfs",
        ]
        if extra_args:
            args.extend(extra_args)

        mock_quay = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = _sample_images(2)
        mock_collector.save_to_csv.return_value = "/tmp/out/test.csv"

        mock_rootfs = MagicMock()
        mock_rootfs.return_value.get_rootfs_path.return_value = Path("/tmp/rootfs/rootfs")
        mock_rootfs.return_value.create_rootfs_directory.return_value = (True, "OK")

        mock_orch = MagicMock()
        mock_orch.analyze_images.return_value = (2, "/tmp/out/test.csv", [])

        mock_gen_auth = MagicMock(return_value="/tmp/generated-auth.json")

        def mock_path_exists(self_path):
            if str(self_path) == ".pull-secret" and pull_secret_exists:
                return True
            if str(self_path).startswith("/my/explicit/"):
                return True
            if str(self_path) == ".env":
                return False
            if str(self_path) == "/tmp/rootfs":
                return True
            return _original_path_exists(self_path)

        _original_path_exists = Path.exists

        with (
            patch("sys.argv", args),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "QuayClient", return_value=mock_quay),
            patch.object(main_script, "RegistryCollector", return_value=mock_collector),
            patch.object(main_script, "RootFSManager", mock_rootfs),
            patch.object(main_script, "AnalysisOrchestrator", return_value=mock_orch) as mock_orch_cls,
            patch.object(main_script, "generate_registry_auth_json", mock_gen_auth),
            patch.object(main_script, "setup_rootfs", return_value=True),
            patch.object(Path, "mkdir"),
            patch.object(Path, "exists", mock_path_exists),
        ):
            result = main()

        return result, mock_gen_auth, mock_orch_cls

    def test_default_pull_secret_ignored_even_if_exists(self):
        """#34 bugfix: .pull-secret on disk must NOT be used when
        --pull-secret is not explicitly passed."""
        result, mock_gen_auth, _ = self._run_analyze(pull_secret_exists=True)
        assert result == 0
        mock_gen_auth.assert_called_once_with(
            registry_host="quay.example.com",
            token="tok123",
        )

    def test_generates_auth_when_no_pull_secret_file(self):
        result, mock_gen_auth, _ = self._run_analyze(pull_secret_exists=False)
        assert result == 0
        mock_gen_auth.assert_called_once()

    def test_explicit_pull_secret_used(self):
        """When user explicitly passes --pull-secret, use that file."""
        result, mock_gen_auth, mock_orch_cls = self._run_analyze(
            extra_args=["--pull-secret", "/my/explicit/secret"],
        )
        assert result == 0
        mock_gen_auth.assert_not_called()
        orch_kwargs = mock_orch_cls.call_args[1]
        assert orch_kwargs["pull_secret_path"] == "/my/explicit/secret"


# ---------------------------------------------------------------------------
# TestRegistryHostExtraction
# ---------------------------------------------------------------------------


class TestRegistryHostExtraction:
    """Test registry host extraction from URL."""

    def _extract_host(self, url):
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname
        if parsed.port:
            host = f"{parsed.hostname}:{parsed.port}"
        return host

    def test_standard_https(self):
        assert self._extract_host("https://quay.example.com") == "quay.example.com"

    def test_with_port(self):
        assert self._extract_host("https://quay.example.com:8443") == "quay.example.com:8443"

    def test_quay_io(self):
        assert self._extract_host("https://quay.io") == "quay.io"


# ---------------------------------------------------------------------------
# TestRegistryModeCollectionOnly
# ---------------------------------------------------------------------------


class TestRegistryModeCollectionOnly:
    """Test registry mode without --analyze."""

    def test_collection_only_returns_0(self, capsys):
        mock_quay = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = _sample_images(2)
        mock_collector.save_to_csv.return_value = "/tmp/out/test.csv"

        with (
            patch("sys.argv", _REGISTRY_BASE_ARGS),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "QuayClient", return_value=mock_quay),
            patch.object(main_script, "RegistryCollector", return_value=mock_collector),
        ):
            result = main()
        assert result == 0
        mock_collector.save_to_csv.assert_called_once()

    def test_collection_only_does_not_call_orchestrator(self, capsys):
        mock_quay = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = _sample_images(1)
        mock_collector.save_to_csv.return_value = "/tmp/out/test.csv"

        with (
            patch("sys.argv", _REGISTRY_BASE_ARGS),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "QuayClient", return_value=mock_quay),
            patch.object(main_script, "RegistryCollector", return_value=mock_collector),
            patch.object(main_script, "AnalysisOrchestrator") as mock_orch,
        ):
            result = main()
        assert result == 0
        mock_orch.assert_not_called()


# ---------------------------------------------------------------------------
# TestRegistryModeWithAnalysis
# ---------------------------------------------------------------------------


class TestRegistryModeWithAnalysis:
    """Test registry mode with --analyze."""

    def test_analyze_without_rootfs_returns_1(self, capsys):
        mock_quay = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = _sample_images(1)

        with (
            patch("sys.argv", [*_REGISTRY_BASE_ARGS, "--analyze"]),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "QuayClient", return_value=mock_quay),
            patch.object(main_script, "RegistryCollector", return_value=mock_collector),
        ):
            result = main()
        assert result == 1
        assert "rootfs-path" in capsys.readouterr().out.lower()

    def test_analyze_calls_orchestrator_without_openshift_params(self, capsys):
        mock_quay = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = _sample_images(1)

        mock_rootfs = MagicMock()
        mock_rootfs.return_value.get_rootfs_path.return_value = Path("/tmp/rootfs/rootfs")
        mock_rootfs.return_value.create_rootfs_directory.return_value = (True, "OK")

        mock_orch = MagicMock()
        mock_orch.analyze_images.return_value = (1, "/tmp/out/test.csv", [])

        with (
            patch("sys.argv", [*_REGISTRY_BASE_ARGS, "--analyze", "--rootfs-path", "/tmp/rootfs"]),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "QuayClient", return_value=mock_quay),
            patch.object(main_script, "RegistryCollector", return_value=mock_collector),
            patch.object(main_script, "RootFSManager", mock_rootfs),
            patch.object(main_script, "AnalysisOrchestrator", return_value=mock_orch) as mock_orch_cls,
            patch.object(main_script, "generate_registry_auth_json", return_value="/tmp/auth.json"),
            patch.object(main_script, "setup_rootfs", return_value=True),
            patch.object(Path, "mkdir"),
        ):
            result = main()
        assert result == 0
        orch_kwargs = mock_orch_cls.call_args[1]
        assert "internal_registry_route" not in orch_kwargs
        assert "openshift_token" not in orch_kwargs


# ---------------------------------------------------------------------------
# TestRegistryModeNoImages
# ---------------------------------------------------------------------------


class TestRegistryModeNoImages:
    """Test registry mode when no images found."""

    def test_empty_collection_returns_0(self, capsys):
        mock_quay = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = []

        with (
            patch("sys.argv", _REGISTRY_BASE_ARGS),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "QuayClient", return_value=mock_quay),
            patch.object(main_script, "RegistryCollector", return_value=mock_collector),
        ):
            result = main()
        assert result == 0
        captured = capsys.readouterr()
        assert "No images found" in captured.out


# ---------------------------------------------------------------------------
# TestPrintAnalysisSummary
# ---------------------------------------------------------------------------


class TestPrintAnalysisSummary:
    """Test the shared _print_analysis_summary function."""

    def test_counts_java_found(self, capsys):
        images = [
            {"java_binary": "/usr/bin/java", "java_cgroup_v2_compatible": "Yes"},
            {"java_binary": "None"},
        ]
        _print_analysis_summary(images)
        out = capsys.readouterr().out
        assert "Java found in: 1 containers" in out

    def test_counts_compatible_incompatible(self, capsys):
        images = [
            {"java_binary": "/usr/bin/java", "java_cgroup_v2_compatible": "Yes"},
            {"java_binary": "/usr/bin/java", "java_cgroup_v2_compatible": "No"},
            {"node_binary": "/usr/bin/node", "node_cgroup_v2_compatible": "Yes"},
            {"dotnet_binary": "/usr/lib/dotnet", "dotnet_cgroup_v2_compatible": "No"},
        ]
        _print_analysis_summary(images)
        out = capsys.readouterr().out
        assert "Java found in: 2 containers" in out
        assert "Node.js found in: 1 containers" in out
        assert ".NET found in: 1 containers" in out

    def test_empty_images(self, capsys):
        _print_analysis_summary([])
        out = capsys.readouterr().out
        assert "Java found in: 0 containers" in out
        assert "Node.js found in: 0 containers" in out
        assert ".NET found in: 0 containers" in out

    def test_all_none_runtimes(self, capsys):
        images = [
            {"java_binary": "None", "node_binary": "None", "dotnet_binary": "None"},
        ]
        _print_analysis_summary(images)
        out = capsys.readouterr().out
        assert "Java found in: 0 containers" in out
        assert "compatible" not in out.split("Java")[1].split("Node")[0]

    def test_works_with_registry_source(self, capsys):
        images = [
            {
                "source": "registry",
                "java_binary": "/usr/bin/java",
                "java_cgroup_v2_compatible": "Yes",
            },
        ]
        _print_analysis_summary(images)
        out = capsys.readouterr().out
        assert "Java found in: 1 containers" in out

    def test_works_with_openshift_source(self, capsys):
        images = [
            {
                "source": "openshift",
                "node_binary": "/usr/bin/node",
                "node_cgroup_v2_compatible": "No",
            },
        ]
        _print_analysis_summary(images)
        out = capsys.readouterr().out
        assert "Node.js found in: 1 containers" in out
        assert "incompatible: 1" in out

    def test_counts_unknown(self, capsys):
        images = [
            {"java_binary": "/usr/bin/java", "java_cgroup_v2_compatible": "Yes"},
            {"java_binary": "/usr/bin/java", "java_cgroup_v2_compatible": "Unknown"},
            {"node_binary": "/usr/bin/node", "node_cgroup_v2_compatible": "Unknown"},
        ]
        _print_analysis_summary(images)
        out = capsys.readouterr().out
        assert "Java found in: 2 containers" in out
        assert "compatible: 1" in out
        assert "? cgroup v2 unknown: 1" in out
        assert "Node.js found in: 1 containers" in out

    def test_unknown_not_shown_when_zero(self, capsys):
        images = [
            {"java_binary": "/usr/bin/java", "java_cgroup_v2_compatible": "Yes"},
        ]
        _print_analysis_summary(images)
        out = capsys.readouterr().out
        assert "unknown" not in out


# ---------------------------------------------------------------------------
# TestOpenShiftModeNotBroken
# ---------------------------------------------------------------------------


class TestOpenShiftModeNotBroken:
    """Verify OpenShift mode still works after refactoring."""

    def _make_mock_image(self, name="quay.io/org/img:latest"):
        img = MagicMock()
        img.to_dict.return_value = {
            "source": "openshift",
            "container_name": "app",
            "namespace": "myns",
            "object_type": "Deployment",
            "object_name": "myapp",
            "registry_org": "",
            "registry_repo": "",
            "image_name": name,
            "image_id": "",
            "java_binary": "",
            "java_version": "",
            "java_cgroup_v2_compatible": "",
            "node_binary": "",
            "node_version": "",
            "node_cgroup_v2_compatible": "",
            "dotnet_binary": "",
            "dotnet_version": "",
            "dotnet_cgroup_v2_compatible": "",
            "analysis_error": "",
        }
        return img

    def _setup_openshift_mocks(self, analyze=False, extra_args=None):
        args = list(_OPENSHIFT_BASE_ARGS)
        if analyze:
            args.extend(["--analyze", "--rootfs-path", "/tmp/rootfs"])
        if extra_args:
            args.extend(extra_args)

        mock_client = MagicMock()
        mock_client.api_url = "https://api.cluster.example.com:6443"
        mock_client.token = "oc-token"
        mock_client.cluster_name = "mycluster"
        mock_client.get_internal_registry_route.return_value = "registry.apps.example.com"

        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = 2
        mock_collector.images = [self._make_mock_image(), self._make_mock_image("quay.io/org/img2:v1")]
        mock_collector.save_to_csv.return_value = "/tmp/out/test.csv"

        mock_rootfs = MagicMock()
        mock_rootfs.return_value.get_rootfs_path.return_value = Path("/tmp/rootfs/rootfs")
        mock_rootfs.return_value.create_rootfs_directory.return_value = (True, "OK")

        mock_orch = MagicMock()
        mock_orch.analyze_images.return_value = (2, "/tmp/out/analyzed.csv", [])

        return args, mock_client, mock_collector, mock_rootfs, mock_orch

    def test_collection_only_uses_save_to_csv(self, capsys):
        args, mock_client, mock_collector, _, _ = self._setup_openshift_mocks()

        with (
            patch("sys.argv", args),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "OpenShiftClient", return_value=mock_client),
            patch.object(main_script, "ImageCollector", return_value=mock_collector),
        ):
            result = main()
        assert result == 0
        mock_collector.save_to_csv.assert_called_once()

    def test_analyze_uses_orchestrator(self, capsys):
        args, mock_client, mock_collector, mock_rootfs, mock_orch = self._setup_openshift_mocks(analyze=True)

        with (
            patch("sys.argv", args),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "OpenShiftClient", return_value=mock_client),
            patch.object(main_script, "ImageCollector", return_value=mock_collector),
            patch.object(main_script, "RootFSManager", mock_rootfs),
            patch.object(main_script, "AnalysisOrchestrator", return_value=mock_orch) as mock_orch_cls,
            patch.object(main_script, "setup_rootfs", return_value=True),
            patch.object(Path, "mkdir"),
        ):
            result = main()
        assert result == 0
        mock_orch_cls.assert_called_once()
        orch_kwargs = mock_orch_cls.call_args[1]
        assert orch_kwargs["internal_registry_route"] == "registry.apps.example.com"
        assert orch_kwargs["openshift_token"] == "oc-token"

    def test_analyze_converts_images_to_dicts(self, capsys):
        args, mock_client, mock_collector, mock_rootfs, mock_orch = self._setup_openshift_mocks(analyze=True)

        with (
            patch("sys.argv", args),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "OpenShiftClient", return_value=mock_client),
            patch.object(main_script, "ImageCollector", return_value=mock_collector),
            patch.object(main_script, "RootFSManager", mock_rootfs),
            patch.object(main_script, "AnalysisOrchestrator", return_value=mock_orch),
            patch.object(main_script, "setup_rootfs", return_value=True),
            patch.object(Path, "mkdir"),
        ):
            result = main()
        assert result == 0
        for img in mock_collector.images:
            img.to_dict.assert_called()
