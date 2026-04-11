"""Tests for --image-timeout feature (issue #42)."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.analysis_orchestrator import AnalysisOrchestrator, _ImageTimeout
from src.image_analyzer import ImageAnalysisResult

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

_REGISTRY_BASE_ARGS = [
    "image-cgroupsv2-inspector",
    "--registry-url",
    "https://quay.example.com",
    "--registry-token",
    "tok123",
    "--registry-org",
    "myorg",
]


def _sample_images(n=3):
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
# CLI argument parsing
# ---------------------------------------------------------------------------


class TestImageTimeoutArgParsing:
    """Test --image-timeout argument parsing."""

    def test_default_timeout_is_600(self):
        with patch("sys.argv", _REGISTRY_BASE_ARGS):
            args = parse_arguments()
        assert args.image_timeout == 600

    def test_custom_timeout_parsed(self):
        with patch("sys.argv", [*_REGISTRY_BASE_ARGS, "--image-timeout", "30"]):
            args = parse_arguments()
        assert args.image_timeout == 30

    def test_zero_timeout_parsed(self):
        with patch("sys.argv", [*_REGISTRY_BASE_ARGS, "--image-timeout", "0"]):
            args = parse_arguments()
        assert args.image_timeout == 0

    def test_timeout_works_with_openshift_args(self):
        with patch(
            "sys.argv",
            [
                "image-cgroupsv2-inspector",
                "--api-url",
                "https://api.cluster.example.com:6443",
                "--token",
                "tok",
                "--image-timeout",
                "120",
            ],
        ):
            args = parse_arguments()
        assert args.image_timeout == 120


# ---------------------------------------------------------------------------
# Orchestrator timeout behaviour
# ---------------------------------------------------------------------------


class TestOrchestratorTimeout:
    """Test AnalysisOrchestrator timeout mechanism."""

    @pytest.fixture
    def mock_analyzer(self):
        with patch("src.analysis_orchestrator.ImageAnalyzer") as mock_cls:
            instance = MagicMock()
            mock_cls.return_value = instance
            yield instance

    def test_timeout_skips_image_and_continues(self, mock_analyzer):
        """A simulated timeout correctly skips the image and continues."""
        good_result = ImageAnalysisResult(image_name="good", image_id="")

        call_count = 0

        def side_effect(image_name, debug=False):
            nonlocal call_count
            call_count += 1
            if "repo0" in image_name:
                raise _ImageTimeout()
            return good_result

        mock_analyzer.analyze_image.side_effect = side_effect

        orchestrator = AnalysisOrchestrator(
            rootfs_path="/tmp/rootfs",
            image_timeout=5,
        )
        # Bypass the real SIGALRM wrapper so we can trigger the exception directly
        orchestrator._analyze_with_timeout = lambda analyzer, name, debug=False: mock_analyzer.analyze_image(
            name, debug=debug
        )

        images = _sample_images(3)
        count, _, skipped = orchestrator.analyze_images(images)

        assert "quay.example.com/myorg/repo0:latest" in skipped
        assert len(skipped) == 1
        assert count == 2

    def test_skipped_image_gets_error_in_record(self, mock_analyzer):
        """Timed-out images have an error message in their records."""
        good_result = ImageAnalysisResult(image_name="good", image_id="")

        def side_effect(image_name, debug=False):
            if "repo0" in image_name:
                raise _ImageTimeout()
            return good_result

        mock_analyzer.analyze_image.side_effect = side_effect

        orchestrator = AnalysisOrchestrator(
            rootfs_path="/tmp/rootfs",
            image_timeout=10,
        )
        orchestrator._analyze_with_timeout = lambda analyzer, name, debug=False: mock_analyzer.analyze_image(
            name, debug=debug
        )

        images = _sample_images(2)
        orchestrator.analyze_images(images)

        repo0_records = [r for r in images if "repo0" in r["image_name"]]
        for rec in repo0_records:
            assert "timed out" in rec.get("analysis_error", "")

    def test_no_timeout_when_disabled(self, mock_analyzer):
        """image_timeout=0 disables the timeout (no SIGALRM)."""
        mock_analyzer.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")

        orchestrator = AnalysisOrchestrator(
            rootfs_path="/tmp/rootfs",
            image_timeout=0,
        )

        images = _sample_images(1)
        count, _, skipped = orchestrator.analyze_images(images)

        assert count == 1
        assert skipped == []

    def test_skipped_summary_printed(self, mock_analyzer, capsys):
        """Summary section is printed when images are skipped."""
        good_result = ImageAnalysisResult(image_name="good", image_id="")

        def side_effect(image_name, debug=False):
            if "repo0" in image_name:
                raise _ImageTimeout()
            return good_result

        mock_analyzer.analyze_image.side_effect = side_effect

        orchestrator = AnalysisOrchestrator(
            rootfs_path="/tmp/rootfs",
            image_timeout=30,
        )
        orchestrator._analyze_with_timeout = lambda analyzer, name, debug=False: mock_analyzer.analyze_image(
            name, debug=debug
        )

        images = _sample_images(2)
        orchestrator.analyze_images(images)

        out = capsys.readouterr().out
        assert "=== Skipped images (timeout) ===" in out
        assert "repo0" in out
        assert "Total skipped: 1" in out

    def test_warning_message_printed(self, mock_analyzer, capsys):
        """WARNING line is printed for each timed-out image."""

        def side_effect(image_name, debug=False):
            raise _ImageTimeout()

        mock_analyzer.analyze_image.side_effect = side_effect

        orchestrator = AnalysisOrchestrator(
            rootfs_path="/tmp/rootfs",
            image_timeout=42,
        )
        orchestrator._analyze_with_timeout = lambda analyzer, name, debug=False: mock_analyzer.analyze_image(
            name, debug=debug
        )

        images = _sample_images(1)
        orchestrator.analyze_images(images)

        out = capsys.readouterr().out
        assert "WARNING: Skipping image" in out
        assert "timed out after 42 seconds" in out

    def test_no_summary_when_no_skips(self, mock_analyzer, capsys):
        """No summary printed when all images succeed."""
        mock_analyzer.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")

        orchestrator = AnalysisOrchestrator(
            rootfs_path="/tmp/rootfs",
            image_timeout=600,
        )

        images = _sample_images(2)
        _, _, skipped = orchestrator.analyze_images(images)

        out = capsys.readouterr().out
        assert "Skipped images" not in out
        assert skipped == []

    def test_cleanup_called_on_timeout(self, mock_analyzer):
        """Cleanup is called for the timed-out image."""

        def side_effect(image_name, debug=False):
            raise _ImageTimeout()

        mock_analyzer.analyze_image.side_effect = side_effect

        orchestrator = AnalysisOrchestrator(
            rootfs_path="/tmp/rootfs",
            image_timeout=10,
        )
        orchestrator._analyze_with_timeout = lambda analyzer, name, debug=False: mock_analyzer.analyze_image(
            name, debug=debug
        )

        images = _sample_images(1)
        orchestrator.analyze_images(images)

        mock_analyzer._cleanup.assert_called_once()


# ---------------------------------------------------------------------------
# Exit code in main()
# ---------------------------------------------------------------------------


class TestImageTimeoutExitCode:
    """Test exit code 2 when images are skipped."""

    def test_exit_code_2_on_skipped_images(self, capsys):
        mock_quay = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = _sample_images(1)

        mock_rootfs = MagicMock()
        mock_rootfs.return_value.get_rootfs_path.return_value = Path("/tmp/rootfs/rootfs")

        mock_orch = MagicMock()
        mock_orch.analyze_images.return_value = (0, "/tmp/out/test.csv", ["quay.example.com/myorg/repo0:latest"])

        with (
            patch("sys.argv", [*_REGISTRY_BASE_ARGS, "--analyze", "--rootfs-path", "/tmp/rootfs"]),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "QuayClient", return_value=mock_quay),
            patch.object(main_script, "RegistryCollector", return_value=mock_collector),
            patch.object(main_script, "RootFSManager", mock_rootfs),
            patch.object(main_script, "AnalysisOrchestrator", return_value=mock_orch),
            patch.object(main_script, "generate_registry_auth_json", return_value="/tmp/auth.json"),
            patch.object(main_script, "setup_rootfs", return_value=True),
            patch.object(Path, "mkdir"),
        ):
            result = main()

        assert result == 2

    def test_exit_code_0_when_no_skips(self, capsys):
        mock_quay = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = _sample_images(1)

        mock_rootfs = MagicMock()
        mock_rootfs.return_value.get_rootfs_path.return_value = Path("/tmp/rootfs/rootfs")

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
            patch.object(main_script, "AnalysisOrchestrator", return_value=mock_orch),
            patch.object(main_script, "generate_registry_auth_json", return_value="/tmp/auth.json"),
            patch.object(main_script, "setup_rootfs", return_value=True),
            patch.object(Path, "mkdir"),
        ):
            result = main()

        assert result == 0

    def test_image_timeout_passed_to_orchestrator(self, capsys):
        mock_quay = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = _sample_images(1)

        mock_rootfs = MagicMock()
        mock_rootfs.return_value.get_rootfs_path.return_value = Path("/tmp/rootfs/rootfs")

        mock_orch = MagicMock()
        mock_orch.analyze_images.return_value = (1, "/tmp/out/test.csv", [])

        with (
            patch(
                "sys.argv",
                [*_REGISTRY_BASE_ARGS, "--analyze", "--rootfs-path", "/tmp/rootfs", "--image-timeout", "45"],
            ),
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
            main()

        orch_kwargs = mock_orch_cls.call_args[1]
        assert orch_kwargs["image_timeout"] == 45
