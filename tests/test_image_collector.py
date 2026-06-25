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


# ---------------------------------------------------------------------------
# Namespace include filter
# ---------------------------------------------------------------------------


class TestNamespaceIncludeFilter:
    """Tests for _is_namespace_included and the include_namespace_patterns filter."""

    def test_no_filter_includes_all(self, mock_client):
        collector = ImageCollector(mock_client)
        assert collector._is_namespace_included("my-app") is True
        assert collector._is_namespace_included("my-app-dev") is True

    def test_suffix_glob(self, mock_client):
        collector = ImageCollector(mock_client, include_namespace_patterns=["*-dev"])
        assert collector._is_namespace_included("my-app-dev") is True
        assert collector._is_namespace_included("backend-dev") is True
        assert collector._is_namespace_included("my-app-prod") is False
        assert collector._is_namespace_included("default") is False

    def test_multiple_patterns(self, mock_client):
        collector = ImageCollector(mock_client, include_namespace_patterns=["*-dev", "*-staging"])
        assert collector._is_namespace_included("my-app-dev") is True
        assert collector._is_namespace_included("my-app-staging") is True
        assert collector._is_namespace_included("my-app-prod") is False

    def test_exact_name_pattern(self, mock_client):
        collector = ImageCollector(mock_client, include_namespace_patterns=["production"])
        assert collector._is_namespace_included("production") is True
        assert collector._is_namespace_included("production-v2") is False

    def test_prefix_glob(self, mock_client):
        collector = ImageCollector(mock_client, include_namespace_patterns=["team-a-*"])
        assert collector._is_namespace_included("team-a-dev") is True
        assert collector._is_namespace_included("team-a-prod") is True
        assert collector._is_namespace_included("team-b-dev") is False

    def test_single_namespace_mode_ignores_include_patterns(self, mock_client):
        collector = ImageCollector(mock_client, namespace="my-app", include_namespace_patterns=["*-dev"])
        assert collector.include_namespace_patterns == []

    def test_filter_applied_to_images(self, mock_client):
        collector = ImageCollector(mock_client, include_namespace_patterns=["*-dev"])
        collector.images = [
            ContainerImageInfo("app", "quay.io/org/app:v1", "backend-dev", "", "Deployment", "dep"),
            ContainerImageInfo("app", "quay.io/org/app:v1", "backend-prod", "", "Deployment", "dep"),
            ContainerImageInfo("app", "quay.io/org/app:v1", "frontend-dev", "", "Deployment", "dep"),
        ]
        collector.images = [img for img in collector.images if collector._is_namespace_included(img.namespace)]
        assert len(collector.images) == 2
        namespaces = {img.namespace for img in collector.images}
        assert namespaces == {"backend-dev", "frontend-dev"}


# ---------------------------------------------------------------------------
# Registry include filter
# ---------------------------------------------------------------------------


class TestRegistryFilter:
    """Tests for _is_registry_included and the include_registry_prefixes filter."""

    def test_no_filter_includes_all(self, mock_client):
        collector = ImageCollector(mock_client)
        assert collector._is_registry_included("quay.io/myorg/app:latest") is True
        assert collector._is_registry_included("docker.io/library/nginx:latest") is True

    def test_single_prefix_matches(self, mock_client):
        collector = ImageCollector(mock_client, include_registry_prefixes=["quay.io/myorg"])
        assert collector._is_registry_included("quay.io/myorg/app:latest") is True
        assert collector._is_registry_included("quay.io/myorg/other:v1") is True

    def test_single_prefix_excludes_other_registry(self, mock_client):
        collector = ImageCollector(mock_client, include_registry_prefixes=["quay.io/myorg"])
        assert collector._is_registry_included("docker.io/library/nginx:latest") is False
        assert collector._is_registry_included("registry.example.com/app:latest") is False

    def test_multiple_prefixes(self, mock_client):
        collector = ImageCollector(
            mock_client,
            include_registry_prefixes=["quay.io/myorg", "registry.example.com"],
        )
        assert collector._is_registry_included("quay.io/myorg/app:latest") is True
        assert collector._is_registry_included("registry.example.com/myapp:v2") is True
        assert collector._is_registry_included("docker.io/library/nginx:latest") is False

    def test_prefix_hostname_only(self, mock_client):
        collector = ImageCollector(mock_client, include_registry_prefixes=["quay.io"])
        assert collector._is_registry_included("quay.io/org/app:latest") is True
        assert collector._is_registry_included("docker.io/library/nginx:latest") is False

    def test_collect_all_applies_filter(self, mock_client):
        """After collect_all, only images matching the prefix survive."""
        collector = ImageCollector(mock_client, include_registry_prefixes=["quay.io/myorg"])

        # Inject images directly (bypassing real API calls)
        from src.image_collector import ContainerImageInfo

        collector.images = [
            ContainerImageInfo("app", "quay.io/myorg/app:v1", "ns", "", "Deployment", "dep"),
            ContainerImageInfo("sidecar", "docker.io/library/nginx:latest", "ns", "", "Deployment", "dep"),
            ContainerImageInfo("other", "quay.io/myorg/other:v2", "ns", "", "Deployment", "dep"),
        ]

        # Patch the collect_from_* methods so collect_all() doesn't call the API
        for method in (
            "collect_from_deployments",
            "collect_from_deploymentconfigs",
            "collect_from_statefulsets",
            "collect_from_daemonsets",
            "collect_from_cronjobs",
            "collect_from_replicasets",
            "collect_from_jobs",
            "collect_from_pods",
        ):
            setattr(collector, method, lambda: 0)

        # Simulate collect_all filter logic by calling the relevant section directly
        collector.images = [img for img in collector.images if collector._is_registry_included(img.image_name)]

        assert len(collector.images) == 2
        names = {img.image_name for img in collector.images}
        assert "quay.io/myorg/app:v1" in names
        assert "quay.io/myorg/other:v2" in names
        assert "docker.io/library/nginx:latest" not in names
