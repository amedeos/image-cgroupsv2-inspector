"""Tests for CLI path resolution before os.chdir(script_dir)."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

_SCRIPT_PATH = Path(__file__).parent.parent / "image-cgroupsv2-inspector"


def _load_main_module():
    loader = importlib.machinery.SourceFileLoader("main_script", str(_SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("main_script", loader, origin=str(_SCRIPT_PATH))
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(_SCRIPT_PATH)
    spec.loader.exec_module(module)
    return module


main_script = _load_main_module()
_resolve_user_path = main_script._resolve_user_path
_resolve_cli_paths = main_script._resolve_cli_paths
parse_arguments = main_script.parse_arguments


class TestResolveUserPath:
    def test_relative_path_uses_invocation_cwd(self, tmp_path):
        secret = tmp_path / "CUSTOMER-ps"
        secret.write_text('{"auths":{}}')
        resolved = _resolve_user_path("CUSTOMER-ps", tmp_path)
        assert resolved == str(secret.resolve())

    def test_absolute_path_unchanged(self, tmp_path):
        secret = tmp_path / "abs-secret.json"
        secret.write_text("{}")
        resolved = _resolve_user_path(str(secret), tmp_path / "other")
        assert resolved == str(secret.resolve())


class TestResolveCliPaths:
    def test_pull_secret_resolved_before_chdir(self, tmp_path, monkeypatch):
        launch_dir = tmp_path / "launch"
        launch_dir.mkdir()
        secret = launch_dir / "CUSTOMER-ps"
        secret.write_text('{"auths":{"registry.example.com":{"auth":"x"}}}')

        work_dir = tmp_path / "bundle"
        work_dir.mkdir()
        monkeypatch.chdir(work_dir)

        argv = [
            "image-cgroupsv2-inspector",
            "--api-url",
            "https://api.cluster.example.com:6443",
            "--token",
            "tok",
            "--pull-secret",
            str(launch_dir / "CUSTOMER-ps"),
        ]
        monkeypatch.setattr("sys.argv", argv)
        args = parse_arguments()
        _resolve_cli_paths(args, launch_dir)

        assert args.pull_secret == str(secret.resolve())
        assert Path(args.pull_secret).exists()


class TestOpenShiftPullSecretNotOverwritten:
    """Regression: resolved pull-secret path must be found after chdir."""

    def test_download_skipped_when_resolved_path_exists(self, tmp_path):
        launch_dir = tmp_path / "cgroupv2"
        launch_dir.mkdir()
        secret = launch_dir / "CUSTOMER-ps"
        secret.write_text('{"auths":{"quay.example.com":{"auth":"dXNlcjpwYXNz"}}}')

        from src.openshift_client import OpenShiftClient

        client = OpenShiftClient(
            api_url="https://api.cluster.example.com:6443",
            token="tok",
            env_file=str(launch_dir / ".env"),
            pull_secret_file=_resolve_user_path("CUSTOMER-ps", launch_dir),
        )

        with patch.object(OpenShiftClient, "get_core_v1_api") as mock_core:
            mock_core.return_value.read_namespaced_secret.side_effect = AssertionError(
                "must not download when user file exists"
            )
            assert client._download_pull_secret() is True

        assert secret.read_text() == '{"auths":{"quay.example.com":{"auth":"dXNlcjpwYXNz"}}}'
