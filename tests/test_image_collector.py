"""Tests for the ImageCollector module — namespace exclusion and helper methods."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.image_collector import DEFAULT_EXCLUDE_NAMESPACE_PATTERNS, ContainerImageInfo, ImageCollector

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    """Create a mock OpenShiftClient."""
    client = MagicMock()
    client.get_core_v1_api.return_value = MagicMock()
    client.get_apps_v1_api.return_value = MagicMock()
    client.get_batch_v1_api.return_value = MagicMock()
    client.get_custom_objects_api.return_value = MagicMock()
    return client


# ---------------------------------------------------------------------------
# Namespace exclusion
# ---------------------------------------------------------------------------


class TestNamespaceExclusion:
    """Tests for _is_namespace_excluded."""

    def test_default_patterns_exclude_openshift(self, mock_client):
        collector = ImageCollector(mock_client)
        assert collector._is_namespace_excluded("openshift-etcd") is True
        assert collector._is_namespace_excluded("openshift-monitoring") is True
        assert collector._is_namespace_excluded("openshift-apiserver") is True

    def test_default_patterns_exclude_kube(self, mock_client):
        collector = ImageCollector(mock_client)
        assert collector._is_namespace_excluded("kube-system") is True
        assert collector._is_namespace_excluded("kube-public") is True

    def test_default_patterns_allow_user_namespaces(self, mock_client):
        collector = ImageCollector(mock_client)
        assert collector._is_namespace_excluded("my-app") is False
        assert collector._is_namespace_excluded("production") is False
        assert collector._is_namespace_excluded("default") is False
        assert collector._is_namespace_excluded("test-java") is False

    def test_custom_patterns(self, mock_client):
        collector = ImageCollector(mock_client, exclude_namespace_patterns=["test-*", "dev-*"])
        assert collector._is_namespace_excluded("test-java") is True
        assert collector._is_namespace_excluded("dev-backend") is True
        assert collector._is_namespace_excluded("production") is False
        assert collector._is_namespace_excluded("openshift-etcd") is False

    def test_empty_patterns_allows_all(self, mock_client):
        collector = ImageCollector(mock_client, exclude_namespace_patterns=[])
        assert collector._is_namespace_excluded("openshift-etcd") is False
        assert collector._is_namespace_excluded("kube-system") is False
        assert collector._is_namespace_excluded("my-app") is False

    def test_single_namespace_mode_no_exclusion(self, mock_client):
        collector = ImageCollector(mock_client, namespace="my-app")
        assert collector.exclude_patterns == []
        assert collector._is_namespace_excluded("openshift-etcd") is False

    def test_exclusion_cache(self, mock_client):
        collector = ImageCollector(mock_client)
        assert collector._is_namespace_excluded("openshift-etcd") is True
        assert "openshift-etcd" in collector._excluded_namespaces_cache
        assert collector._is_namespace_excluded("openshift-etcd") is True


# ---------------------------------------------------------------------------
# Label selector building
# ---------------------------------------------------------------------------


class TestBuildLabelSelector:
    """Tests for _build_label_selector."""

    def test_single_label(self, mock_client):
        collector = ImageCollector(mock_client)
        assert collector._build_label_selector({"app": "myapp"}) == "app=myapp"

    def test_multiple_labels(self, mock_client):
        collector = ImageCollector(mock_client)
        result = collector._build_label_selector({"app": "myapp", "version": "v1"})
        assert "app=myapp" in result
        assert "version=v1" in result

    def test_empty_labels(self, mock_client):
        collector = ImageCollector(mock_client)
        assert collector._build_label_selector({}) == ""

    def test_none_labels(self, mock_client):
        collector = ImageCollector(mock_client)
        assert collector._build_label_selector(None) == ""


# ---------------------------------------------------------------------------
# Owner references
# ---------------------------------------------------------------------------


class TestOwnerReferences:
    """Tests for _is_owned_by."""

    def test_owned_by_deployment(self, mock_client):
        collector = ImageCollector(mock_client)
        metadata = MagicMock()
        metadata.owner_references = [MagicMock(kind="ReplicaSet", name="my-rs")]
        assert collector._is_owned_by(metadata, ["ReplicaSet"]) is True

    def test_not_owned(self, mock_client):
        collector = ImageCollector(mock_client)
        metadata = MagicMock()
        metadata.owner_references = None
        assert collector._is_owned_by(metadata, ["Deployment"]) is False

    def test_owned_by_different_kind(self, mock_client):
        collector = ImageCollector(mock_client)
        metadata = MagicMock()
        metadata.owner_references = [MagicMock(kind="StatefulSet", name="my-sts")]
        assert collector._is_owned_by(metadata, ["Deployment"]) is False
        assert collector._is_owned_by(metadata, ["StatefulSet"]) is True


# ---------------------------------------------------------------------------
# ContainerImageInfo
# ---------------------------------------------------------------------------


class TestContainerImageInfo:
    """Tests for ContainerImageInfo."""

    def test_to_dict(self):
        info = ContainerImageInfo(
            container_name="app",
            image_name="quay.io/my-org/my-image:latest",
            namespace="my-app",
            image_id="sha256:abc123",
            object_type="Deployment",
            object_name="my-deployment",
        )
        d = info.to_dict()
        assert d["source"] == "openshift"
        assert d["container_name"] == "app"
        assert d["image_name"] == "quay.io/my-org/my-image:latest"
        assert d["namespace"] == "my-app"
        assert d["image_id"] == "sha256:abc123"
        assert d["object_type"] == "Deployment"
        assert d["object_name"] == "my-deployment"
        assert d["registry_org"] == ""
        assert d["registry_repo"] == ""
        assert d["java_binary"] == ""
        assert d["java_version"] == ""
        assert d["java_cgroup_v2_compatible"] == ""
        assert d["analysis_error"] == ""

    def test_to_dict_with_analysis(self):
        info = ContainerImageInfo(
            container_name="app",
            image_name="quay.io/my-org/my-image:latest",
            namespace="my-app",
            image_id="",
            object_type="Pod",
            object_name="my-pod",
        )
        info.java_binary = "/usr/bin/java"
        info.java_version = "17.0.1"
        info.java_compatible = "Yes"
        d = info.to_dict()
        assert d["source"] == "openshift"
        assert d["registry_org"] == ""
        assert d["registry_repo"] == ""
        assert d["java_binary"] == "/usr/bin/java"
        assert d["java_version"] == "17.0.1"
        assert d["java_cgroup_v2_compatible"] == "Yes"


# ---------------------------------------------------------------------------
# _add_container_info
# ---------------------------------------------------------------------------


class TestAddContainerInfo:
    """Tests for _add_container_info with resolved image maps."""

    def test_uses_resolved_image(self, mock_client):
        collector = ImageCollector(mock_client)
        containers = [SimpleNamespace(name="app", image="eclipse-temurin:17")]
        resolved = {"app": "docker.io/library/eclipse-temurin:17"}
        count = collector._add_container_info(
            containers, "test-ns", "Deployment", "my-deploy", resolved_image_map=resolved
        )
        assert count == 1
        assert collector.images[0].image_name == "docker.io/library/eclipse-temurin:17"

    def test_uses_spec_image_when_no_resolution(self, mock_client):
        collector = ImageCollector(mock_client)
        containers = [SimpleNamespace(name="app", image="quay.io/my-org/my-image:latest")]
        count = collector._add_container_info(containers, "test-ns", "Deployment", "my-deploy")
        assert count == 1
        assert collector.images[0].image_name == "quay.io/my-org/my-image:latest"

    def test_uses_spec_image_when_resolved_same(self, mock_client):
        collector = ImageCollector(mock_client)
        containers = [SimpleNamespace(name="app", image="quay.io/my-org/my-image:latest")]
        resolved = {"app": "quay.io/my-org/my-image:latest"}
        count = collector._add_container_info(
            containers, "test-ns", "Deployment", "my-deploy", resolved_image_map=resolved
        )
        assert count == 1
        assert collector.images[0].image_name == "quay.io/my-org/my-image:latest"


# ---------------------------------------------------------------------------
# Default exclude patterns constant
# ---------------------------------------------------------------------------


class TestDefaults:
    """Tests for module-level defaults."""

    def test_default_exclude_patterns(self):
        assert "openshift-*" in DEFAULT_EXCLUDE_NAMESPACE_PATTERNS
        assert "kube-*" in DEFAULT_EXCLUDE_NAMESPACE_PATTERNS
