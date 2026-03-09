"""Tests for the OpenShiftClient module — cluster name extraction."""

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
