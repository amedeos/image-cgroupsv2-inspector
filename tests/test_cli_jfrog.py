"""Tests for the CLI's JFrog scan mode."""

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


_JFROG_BASE_ARGS = [
    "image-cgroupsv2-inspector",
    "--jfrog-url",
    "https://acme.jfrog.io",
    "--jfrog-token",
    "tok123",
    "--jfrog-repo",
    "docker-local",
]

_OPENSHIFT_API_FLAG = ["--api-url", "https://api.cluster.example.com:6443"]
_REGISTRY_FLAGS = [
    "--registry-url",
    "https://quay.example.com",
    "--registry-token",
    "qtok",
    "--registry-org",
    "myorg",
]


def _sample_jfrog_images(n: int = 2) -> list[dict]:
    return [
        {
            "source": "jfrog",
            "container_name": "",
            "namespace": "",
            "object_type": "",
            "object_name": "",
            "registry_org": "docker-local",
            "registry_repo": f"img-{i}",
            "image_name": f"acme.jfrog.io/docker-local/img-{i}:latest",
            "image_id": "",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


class TestParseArguments:
    def test_jfrog_args_parsed(self):
        argv = [*_JFROG_BASE_ARGS, "--jfrog-image", "java-compatible", "--jfrog-username", "u@x"]
        with patch("sys.argv", argv):
            args = parse_arguments()
        assert args.jfrog_url == "https://acme.jfrog.io"
        assert args.jfrog_token == "tok123"
        assert args.jfrog_repo == "docker-local"
        assert args.jfrog_image == "java-compatible"
        assert args.jfrog_username == "u@x"

    def test_jfrog_image_defaults_to_none(self):
        with patch("sys.argv", _JFROG_BASE_ARGS):
            args = parse_arguments()
        assert args.jfrog_image is None

    def test_shared_tag_filters_apply(self):
        argv = [*_JFROG_BASE_ARGS, "--include-tags", "v*", "--exclude-tags", "*-dev", "--latest-only", "3"]
        with patch("sys.argv", argv):
            args = parse_arguments()
        assert args.include_tags == "v*"
        assert args.exclude_tags == "*-dev"
        assert args.latest_only == 3


# ---------------------------------------------------------------------------
# Mutual exclusion
# ---------------------------------------------------------------------------


class TestMutualExclusion:
    @pytest.fixture
    def harness(self):
        with (
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.dict(
                "os.environ",
                {k: "" for k in ("JFROG_URL", "JFROG_TOKEN", "JFROG_REPO", "JFROG_USERNAME")},
                clear=False,
            ),
        ):
            yield

    def test_jfrog_and_api_mutually_exclusive(self, harness, capsys):
        argv = [*_JFROG_BASE_ARGS, *_OPENSHIFT_API_FLAG, "--token", "oc"]
        with patch("sys.argv", argv):
            assert main() == 1
        out = capsys.readouterr().out
        assert "mutually exclusive" in out
        assert "--api-url" in out and "--jfrog-url" in out

    def test_jfrog_and_registry_mutually_exclusive(self, harness, capsys):
        argv = [*_JFROG_BASE_ARGS, *_REGISTRY_FLAGS]
        with patch("sys.argv", argv):
            assert main() == 1
        out = capsys.readouterr().out
        assert "mutually exclusive" in out
        assert "--registry-url" in out and "--jfrog-url" in out

    def test_all_three_modes_mutually_exclusive(self, harness, capsys):
        argv = [
            *_JFROG_BASE_ARGS,
            *_OPENSHIFT_API_FLAG,
            "--token",
            "oc",
            *_REGISTRY_FLAGS,
        ]
        with patch("sys.argv", argv):
            assert main() == 1
        out = capsys.readouterr().out
        assert "--api-url" in out
        assert "--registry-url" in out
        assert "--jfrog-url" in out


# ---------------------------------------------------------------------------
# Env-var fallback
# ---------------------------------------------------------------------------


class TestEnvFallback:
    def test_jfrog_env_vars_populate_args_when_flags_omitted(self, capsys):
        """JFROG_URL/JFROG_TOKEN/JFROG_REPO act as fallbacks when CLI flags are empty."""
        mock_client = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = _sample_jfrog_images(2)
        mock_collector.save_to_csv.return_value = "/tmp/test.csv"

        with (
            patch("sys.argv", ["image-cgroupsv2-inspector"]),
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "JfrogClient", return_value=mock_client),
            patch.object(main_script, "JfrogCollector", return_value=mock_collector),
            patch.dict(
                "os.environ",
                {
                    "JFROG_URL": "https://env.jfrog.io",
                    "JFROG_TOKEN": "envtok",
                    "JFROG_REPO": "envrepo",
                },
                clear=True,
            ),
        ):
            result = main()
        assert result == 0
        # Confirm we hit the JFrog branch (test_connection invoked).
        mock_client.test_connection.assert_called_once()


# ---------------------------------------------------------------------------
# JFrog mode — happy path & guards
# ---------------------------------------------------------------------------


class TestJfrogModeFlow:
    @pytest.fixture
    def jfrog_harness(self):
        mock_client = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_images.return_value = _sample_jfrog_images(2)
        mock_collector.save_to_csv.return_value = "/tmp/test.csv"

        with (
            patch.object(main_script, "run_system_checks", return_value=True),
            patch.object(main_script, "print_banner"),
            patch("dotenv.load_dotenv"),
            patch.object(main_script, "JfrogClient", return_value=mock_client),
            patch.object(main_script, "JfrogCollector", return_value=mock_collector),
            patch.dict("os.environ", {}, clear=True),
        ):
            yield mock_client, mock_collector

    def test_jfrog_url_activates_jfrog_mode(self, jfrog_harness, capsys):
        mock_client, _ = jfrog_harness
        with patch("sys.argv", _JFROG_BASE_ARGS):
            assert main() == 0
        mock_client.test_connection.assert_called_once()
        mock_client.check_repository.assert_called_once_with("docker-local")
        out = capsys.readouterr().out
        assert "JFrog registry" in out

    def test_missing_token_returns_1(self, jfrog_harness, capsys):
        # Argparse parses --jfrog-token as required by main(), not parser
        argv = [
            "image-cgroupsv2-inspector",
            "--jfrog-url",
            "https://acme.jfrog.io",
            "--jfrog-repo",
            "docker-local",
        ]
        with patch("sys.argv", argv):
            assert main() == 1
        out = capsys.readouterr().out
        assert "--jfrog-token is required" in out

    def test_missing_repo_returns_1(self, jfrog_harness, capsys):
        argv = [
            "image-cgroupsv2-inspector",
            "--jfrog-url",
            "https://acme.jfrog.io",
            "--jfrog-token",
            "tok",
        ]
        with patch("sys.argv", argv):
            assert main() == 1
        out = capsys.readouterr().out
        assert "--jfrog-repo is required" in out

    def test_analyze_without_username_returns_1(self, jfrog_harness, capsys, tmp_path):
        argv = [*_JFROG_BASE_ARGS, "--analyze", "--rootfs-path", str(tmp_path)]
        with patch("sys.argv", argv), patch.object(main_script, "setup_rootfs", return_value=True):
            assert main() == 1
        out = capsys.readouterr().out
        assert "--jfrog-username is required" in out
