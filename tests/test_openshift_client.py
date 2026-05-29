"""Tests for the OpenShiftClient module."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.rest import ApiException

from src.openshift_client import OpenShiftClient


class TestClusterNameExtraction:
    """Tests for _extract_cluster_name."""

    def _make_client(self, api_url):
        """Create an OpenShiftClient without connecting, using a fake .env path."""
        client = OpenShiftClient(api_url=api_url, token="fake", env_file="/dev/null")
        return client

    def test_standard_api_url(self):
        client = self._make_client("https://api.mycluster.example.com:6443")
        assert client._extract_cluster_name() == "mycluster.example.com"

    def test_api_url_without_port(self):
        client = self._make_client("https://api.mycluster.example.com")
        assert client._extract_cluster_name() == "mycluster.example.com"

    def test_api_url_non_standard_host(self):
        client = self._make_client("https://openshift.internal.corp:6443")
        assert client._extract_cluster_name() == "openshift.internal.corp"

    def test_api_url_no_api_prefix(self):
        client = self._make_client("https://cluster.example.com:6443")
        assert client._extract_cluster_name() == "cluster.example.com"

    def test_api_url_none(self):
        client = self._make_client(None)
        assert client._extract_cluster_name() == "unknown"

    def test_api_url_empty(self):
        client = self._make_client("")
        assert client._extract_cluster_name() == "unknown"

    def test_api_url_just_api(self):
        client = self._make_client("https://api.example.com")
        assert client._extract_cluster_name() == "example.com"

    def test_api_url_with_path(self):
        client = self._make_client("https://api.mycluster.example.com:6443/some/path")
        assert client._extract_cluster_name() == "mycluster.example.com"

    def test_api_url_complex_domain(self):
        client = self._make_client("https://api.shrocp4upi417ovn.lab.upshift.rdu2.redhat.com:6443")
        assert client._extract_cluster_name() == "shrocp4upi417ovn.lab.upshift.rdu2.redhat.com"


class TestConnect:
    """Tests for OpenShift client connection/authentication setup."""

    def _make_client(self, tmp_path, token="fake-token"):
        return OpenShiftClient(
            api_url="https://api.mycluster.example.com:6443",
            token=token,
            env_file=str(tmp_path / ".env"),
            pull_secret_file=str(tmp_path / ".pull-secret"),
        )

    def test_connect_configures_bearer_token_auth(self, tmp_path):
        client = self._make_client(tmp_path)
        captured = {}
        api_client = MagicMock()

        def build_api_client(configuration):
            captured["configuration"] = configuration
            return api_client

        with (
            patch("src.openshift_client.ApiClient", side_effect=build_api_client),
            patch("src.openshift_client.client.VersionApi") as mock_version_api,
            patch("src.openshift_client.client.CustomObjectsApi") as mock_custom_objects_api,
            patch.object(OpenShiftClient, "_save_to_env"),
            patch.object(OpenShiftClient, "_download_pull_secret"),
        ):
            mock_version_api.return_value.get_code.return_value = SimpleNamespace(git_version="v1.28.2")
            mock_custom_objects_api.return_value.get_cluster_custom_object.return_value = {
                "metadata": {"name": "alice"}
            }

            assert client.connect() is True

        configuration = captured["configuration"]
        assert configuration.api_key == {"BearerToken": "fake-token"}
        assert configuration.api_key_prefix == {"BearerToken": "Bearer"}
        assert client.api_client is api_client

    def test_connect_fails_when_authenticated_probe_is_forbidden(self, tmp_path):
        client = self._make_client(tmp_path)

        with (
            patch("src.openshift_client.ApiClient", return_value=MagicMock()),
            patch("src.openshift_client.client.VersionApi") as mock_version_api,
            patch("src.openshift_client.client.CustomObjectsApi") as mock_custom_objects_api,
            patch.object(OpenShiftClient, "_save_to_env") as mock_save_to_env,
            patch.object(OpenShiftClient, "_download_pull_secret") as mock_download_pull_secret,
        ):
            mock_version_api.return_value.get_code.return_value = SimpleNamespace(git_version="v1.28.2")
            mock_custom_objects_api.return_value.get_cluster_custom_object.side_effect = ApiException(
                status=403, reason="Forbidden"
            )

            with pytest.raises(Exception, match="token was not accepted for authenticated OpenShift API access"):
                client.connect()

        mock_save_to_env.assert_not_called()
        mock_download_pull_secret.assert_not_called()
        assert client._api_client is None
