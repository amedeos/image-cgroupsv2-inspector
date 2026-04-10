"""Tests for the ImageAnalyzer module — version parsing & cgroup v2 compatibility logic."""

import pytest

from src.image_analyzer import BinaryInfo, ImageAnalysisResult, ImageAnalyzer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def analyzer(tmp_path):
    """Create an ImageAnalyzer instance with a temporary rootfs path."""
    return ImageAnalyzer(rootfs_base_path=str(tmp_path))


# ---------------------------------------------------------------------------
# Java cgroup v2 compatibility checks
# ---------------------------------------------------------------------------


class TestJavaCompatibility:
    """Tests for _check_java_compatibility."""

    # --- OpenJDK / HotSpot ---

    @pytest.mark.parametrize(
        "version",
        [
            "1.8.0_372",
            "1.8.0_400",
            "1.8.0_999",
        ],
    )
    def test_openjdk_8_compatible(self, analyzer, version):
        assert analyzer._check_java_compatibility(version, "OpenJDK") is True

    @pytest.mark.parametrize(
        "version",
        [
            "1.8.0_362",
            "1.8.0_371",
            "1.8.0_100",
            "1.8.0_0",
        ],
    )
    def test_openjdk_8_incompatible(self, analyzer, version):
        assert analyzer._check_java_compatibility(version, "OpenJDK") is False

    @pytest.mark.parametrize(
        "version",
        [
            "11.0.16",
            "11.0.17",
            "11.0.20",
            "11.1.0",
        ],
    )
    def test_openjdk_11_compatible(self, analyzer, version):
        assert analyzer._check_java_compatibility(version, "OpenJDK") is True

    @pytest.mark.parametrize(
        "version",
        [
            "11.0.15",
            "11.0.14",
            "11.0.0",
        ],
    )
    def test_openjdk_11_incompatible(self, analyzer, version):
        assert analyzer._check_java_compatibility(version, "OpenJDK") is False

    @pytest.mark.parametrize(
        "version",
        [
            "15",
            "15.0.1",
            "16",
            "17",
            "17.0.1",
            "21",
            "21.0.3",
        ],
    )
    def test_openjdk_15_plus_always_compatible(self, analyzer, version):
        assert analyzer._check_java_compatibility(version, "OpenJDK") is True

    @pytest.mark.parametrize(
        "version",
        [
            "9",
            "9.0.1",
            "10",
            "10.0.2",
            "12",
            "13",
            "14",
            "14.0.2",
        ],
    )
    def test_openjdk_9_to_14_incompatible(self, analyzer, version):
        assert analyzer._check_java_compatibility(version, "OpenJDK") is False

    # --- IBM Semeru ---

    @pytest.mark.parametrize(
        "version",
        [
            "1.8.0_345-b01",
            "1.8.0_400",
        ],
    )
    def test_ibm_semeru_8_compatible(self, analyzer, version):
        assert analyzer._check_java_compatibility(version, "IBM Semeru") is True

    @pytest.mark.parametrize(
        "version",
        [
            "1.8.0_344",
            "1.8.0_100",
        ],
    )
    def test_ibm_semeru_8_incompatible(self, analyzer, version):
        assert analyzer._check_java_compatibility(version, "IBM Semeru") is False

    def test_ibm_semeru_17_compatible(self, analyzer):
        assert analyzer._check_java_compatibility("17.0.4", "IBM Semeru") is True
        assert analyzer._check_java_compatibility("17.0.5", "IBM Semeru") is True
        assert analyzer._check_java_compatibility("17.1.0", "IBM Semeru") is True

    def test_ibm_semeru_17_incompatible(self, analyzer):
        assert analyzer._check_java_compatibility("17.0.3", "IBM Semeru") is False
        assert analyzer._check_java_compatibility("17.0.0", "IBM Semeru") is False

    def test_ibm_semeru_18_compatible(self, analyzer):
        assert analyzer._check_java_compatibility("18.0.2", "IBM Semeru") is True
        assert analyzer._check_java_compatibility("18.0.3", "IBM Semeru") is True
        assert analyzer._check_java_compatibility("18.1.0", "IBM Semeru") is True

    def test_ibm_semeru_18_incompatible(self, analyzer):
        assert analyzer._check_java_compatibility("18.0.1", "IBM Semeru") is False
        assert analyzer._check_java_compatibility("18.0.0", "IBM Semeru") is False

    # --- IBM Java (IBM SDK) ---

    def test_ibm_java_8_compatible(self, analyzer):
        assert analyzer._check_java_compatibility("1.8.0.7.15", "IBM Java") is True
        assert analyzer._check_java_compatibility("1.8.0.7.20", "IBM Java") is True
        assert analyzer._check_java_compatibility("1.8.0.8.0", "IBM Java") is True
        assert analyzer._check_java_compatibility("1.8.1.0.0", "IBM Java") is True

    def test_ibm_java_8_incompatible(self, analyzer):
        assert analyzer._check_java_compatibility("1.8.0.7.14", "IBM Java") is False
        assert analyzer._check_java_compatibility("1.8.0.7.0", "IBM Java") is False
        assert analyzer._check_java_compatibility("1.8.0.6.0", "IBM Java") is False

    # --- Edge cases ---

    def test_unknown_version(self, analyzer):
        assert analyzer._check_java_compatibility("unknown", "OpenJDK") is None

    def test_empty_version(self, analyzer):
        assert analyzer._check_java_compatibility("", "OpenJDK") is False

    def test_garbage_version(self, analyzer):
        assert analyzer._check_java_compatibility("abc.def.ghi", "OpenJDK") is False


# ---------------------------------------------------------------------------
# Node.js cgroup v2 compatibility checks
# ---------------------------------------------------------------------------


class TestNodeCompatibility:
    """Tests for _check_node_compatibility."""

    @pytest.mark.parametrize(
        "version",
        [
            "20.3.0",
            "20.3.1",
            "20.4.0",
            "20.10.0",
            "21.0.0",
            "22.0.0",
        ],
    )
    def test_compatible(self, analyzer, version):
        assert analyzer._check_node_compatibility(version) is True

    @pytest.mark.parametrize(
        "version",
        [
            "20.2.0",
            "20.2.9",
            "20.0.0",
            "18.0.0",
            "18.19.0",
            "16.0.0",
            "14.0.0",
        ],
    )
    def test_incompatible(self, analyzer, version):
        assert analyzer._check_node_compatibility(version) is False

    def test_unknown_version(self, analyzer):
        assert analyzer._check_node_compatibility("unknown") is None

    def test_empty_version(self, analyzer):
        assert analyzer._check_node_compatibility("") is False

    def test_short_version(self, analyzer):
        assert analyzer._check_node_compatibility("20.3") is False


# ---------------------------------------------------------------------------
# .NET cgroup v2 compatibility checks
# ---------------------------------------------------------------------------


class TestDotnetCompatibility:
    """Tests for _check_dotnet_compatibility."""

    @pytest.mark.parametrize(
        "version",
        [
            "5.0.0",
            "5.0.17",
            "6.0.0",
            "6.0.36",
            "7.0.0",
            "8.0.0",
            "8.0.12",
            "9.0.0",
        ],
    )
    def test_compatible(self, analyzer, version):
        assert analyzer._check_dotnet_compatibility(version) is True

    @pytest.mark.parametrize(
        "version",
        [
            "3.0.0",
            "3.0.100",
            "3.1.0",
            "3.1.32",
            "2.0.0",
            "2.1.0",
            "1.0.0",
            "4.0.0",
        ],
    )
    def test_incompatible(self, analyzer, version):
        assert analyzer._check_dotnet_compatibility(version) is False

    def test_unknown_version(self, analyzer):
        assert analyzer._check_dotnet_compatibility("unknown") is None

    def test_empty_version(self, analyzer):
        assert analyzer._check_dotnet_compatibility("") is False


# ---------------------------------------------------------------------------
# Version parsing regex tests
# ---------------------------------------------------------------------------


class TestJavaVersionParsing:
    """Tests for Java version regex patterns."""

    def test_openjdk_version_pattern(self):
        pattern = ImageAnalyzer.JAVA_VERSION_PATTERN
        output = 'openjdk version "1.8.0_372"'
        match = pattern.search(output)
        assert match is not None
        assert match.group(1) == "1.8.0_372"

    def test_openjdk_version_pattern_11(self):
        pattern = ImageAnalyzer.JAVA_VERSION_PATTERN
        output = 'openjdk version "11.0.16" 2022-07-19'
        match = pattern.search(output)
        assert match is not None
        assert match.group(1) == "11.0.16"

    def test_openjdk_version_pattern_17(self):
        pattern = ImageAnalyzer.JAVA_VERSION_PATTERN
        output = 'openjdk version "17.0.1" 2021-10-19'
        match = pattern.search(output)
        assert match is not None
        assert match.group(1) == "17.0.1"

    def test_ibm_semeru_version_pattern(self):
        pattern = ImageAnalyzer.JAVA_VERSION_PATTERN
        output = 'openjdk version "1.8.0_345-b01"'
        match = pattern.search(output)
        assert match is not None
        assert match.group(1) == "1.8.0_345-b01"

    def test_alt_pattern_simple(self):
        pattern = ImageAnalyzer.JAVA_VERSION_ALT_PATTERN
        output = "openjdk 17.0.4"
        match = pattern.search(output)
        assert match is not None
        assert match.group(1) == "17.0.4"


class TestNodeVersionParsing:
    """Tests for Node.js version regex patterns."""

    def test_version_with_v_prefix(self):
        pattern = ImageAnalyzer.NODE_VERSION_PATTERN
        match = pattern.search("v20.3.0")
        assert match is not None
        assert match.group(1) == "20.3.0"

    def test_version_without_prefix(self):
        pattern = ImageAnalyzer.NODE_VERSION_PATTERN
        match = pattern.search("20.3.0")
        assert match is not None
        assert match.group(1) == "20.3.0"


class TestDotnetVersionParsing:
    """Tests for .NET version regex patterns."""

    def test_netcore_app_pattern(self):
        pattern = ImageAnalyzer.DOTNET_VERSION_PATTERN
        output = "Microsoft.NETCore.App 8.0.12 [/usr/share/dotnet/shared/Microsoft.NETCore.App]"
        match = pattern.search(output)
        assert match is not None
        assert match.group(1) == "8.0.12"

    def test_netcore_app_pattern_old(self):
        pattern = ImageAnalyzer.DOTNET_VERSION_PATTERN
        output = "Microsoft.NETCore.App 3.0.0 [/usr/share/dotnet/shared/Microsoft.NETCore.App]"
        match = pattern.search(output)
        assert match is not None
        assert match.group(1) == "3.0.0"


# ---------------------------------------------------------------------------
# IBM runtime type detection
# ---------------------------------------------------------------------------


class TestRuntimeTypeDetection:
    """Tests for IBM Semeru / IBM SDK pattern detection."""

    def test_ibm_semeru_detected(self):
        assert ImageAnalyzer.IBM_SEMERU_PATTERN.search("IBM Semeru Runtime Open Edition") is not None

    def test_ibm_sdk_detected(self):
        assert ImageAnalyzer.IBM_SDK_PATTERN.search("IBM J9 VM") is not None
        assert ImageAnalyzer.IBM_SDK_PATTERN.search("IBM SDK, Java Technology Edition") is not None

    def test_openjdk_not_ibm(self):
        assert ImageAnalyzer.IBM_SEMERU_PATTERN.search("OpenJDK Runtime Environment") is None
        assert ImageAnalyzer.IBM_SDK_PATTERN.search("OpenJDK Runtime Environment") is None


# ---------------------------------------------------------------------------
# Internal registry URL rewriting
# ---------------------------------------------------------------------------


class TestInternalRegistryRewrite:
    """Tests for _rewrite_internal_registry."""

    def test_no_route_configured(self, tmp_path):
        analyzer = ImageAnalyzer(rootfs_base_path=str(tmp_path), internal_registry_route=None)
        image = "image-registry.openshift-image-registry.svc:5000/ns/img:tag"
        assert analyzer._rewrite_internal_registry(image) == image

    def test_rewrite_with_port(self, tmp_path):
        analyzer = ImageAnalyzer(
            rootfs_base_path=str(tmp_path),
            internal_registry_route="default-route-openshift-image-registry.apps.example.com",
        )
        image = "image-registry.openshift-image-registry.svc:5000/myns/myimage:v1"
        expected = "default-route-openshift-image-registry.apps.example.com/myns/myimage:v1"
        assert analyzer._rewrite_internal_registry(image) == expected

    def test_non_internal_image_unchanged(self, tmp_path):
        analyzer = ImageAnalyzer(
            rootfs_base_path=str(tmp_path),
            internal_registry_route="default-route-openshift-image-registry.apps.example.com",
        )
        image = "quay.io/my-org/my-image:latest"
        assert analyzer._rewrite_internal_registry(image) == image

    def test_docker_hub_image_unchanged(self, tmp_path):
        analyzer = ImageAnalyzer(
            rootfs_base_path=str(tmp_path),
            internal_registry_route="default-route-openshift-image-registry.apps.example.com",
        )
        image = "docker.io/library/openjdk:17"
        assert analyzer._rewrite_internal_registry(image) == image


# ---------------------------------------------------------------------------
# Path exclusion
# ---------------------------------------------------------------------------


class TestPathExclusion:
    """Tests for _is_excluded_path."""

    @pytest.mark.parametrize(
        "path",
        [
            "/var/lib/alternatives/java",
            "/var/lib/dpkg/alternatives/node",
            "/etc/alternatives/dotnet",
            "/usr/share/bash-completion/completions/java",
            "/etc/bash_completion.d/node",
        ],
    )
    def test_excluded_paths(self, analyzer, path):
        assert analyzer._is_excluded_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/usr/bin/java",
            "/usr/local/bin/node",
            "/usr/share/dotnet/dotnet",
            "/opt/java/bin/java",
        ],
    )
    def test_non_excluded_paths(self, analyzer, path):
        assert analyzer._is_excluded_path(path) is False

    def test_dotnet_optimization_data_excluded(self, analyzer):
        path = "/home/user/.dotnet/optimizationdata/some-file"
        assert analyzer._is_excluded_path(path) is True


# ---------------------------------------------------------------------------
# ImageAnalysisResult properties
# ---------------------------------------------------------------------------


class TestImageAnalysisResult:
    """Tests for ImageAnalysisResult data class properties."""

    def test_empty_result(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc123")
        assert result.java_found == "None"
        assert result.java_versions == "None"
        assert result.java_compatible == "N/A"
        assert result.node_found == "None"
        assert result.node_versions == "None"
        assert result.node_compatible == "N/A"
        assert result.dotnet_found == "None"
        assert result.dotnet_versions == "None"
        assert result.dotnet_compatible == "N/A"
        assert result.error is None

    def test_java_compatible(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc123")
        result.java_binaries.append(
            BinaryInfo(
                path="/usr/bin/java",
                version="17.0.1",
                version_output="openjdk 17.0.1",
                is_compatible=True,
                runtime_type="OpenJDK",
            )
        )
        assert result.java_found == "/usr/bin/java"
        assert result.java_versions == "17.0.1"
        assert result.java_compatible == "Yes"

    def test_java_incompatible(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc123")
        result.java_binaries.append(
            BinaryInfo(
                path="/usr/bin/java",
                version="1.8.0_362",
                version_output="openjdk 1.8.0_362",
                is_compatible=False,
                runtime_type="OpenJDK",
            )
        )
        assert result.java_compatible == "No"

    def test_multiple_binaries_all_compatible(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc123")
        result.java_binaries.append(
            BinaryInfo(
                path="/usr/bin/java",
                version="17.0.1",
                version_output="",
                is_compatible=True,
                runtime_type="OpenJDK",
            )
        )
        result.java_binaries.append(
            BinaryInfo(
                path="/opt/java/bin/java",
                version="21.0.1",
                version_output="",
                is_compatible=True,
                runtime_type="OpenJDK",
            )
        )
        assert result.java_compatible == "Yes"
        assert "/usr/bin/java" in result.java_found
        assert "/opt/java/bin/java" in result.java_found

    def test_multiple_binaries_one_incompatible(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc123")
        result.java_binaries.append(
            BinaryInfo(
                path="/usr/bin/java",
                version="17.0.1",
                version_output="",
                is_compatible=True,
                runtime_type="OpenJDK",
            )
        )
        result.java_binaries.append(
            BinaryInfo(
                path="/opt/java/bin/java",
                version="1.8.0_100",
                version_output="",
                is_compatible=False,
                runtime_type="OpenJDK",
            )
        )
        assert result.java_compatible == "No"

    def test_java_unknown_version(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc123")
        result.java_binaries.append(
            BinaryInfo(
                path="/usr/bin/java",
                version="unknown",
                version_output="",
                is_compatible=None,
                runtime_type="Unknown",
            )
        )
        assert result.java_compatible == "Unknown"

    def test_java_mixed_known_and_unknown(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc123")
        result.java_binaries.append(
            BinaryInfo(
                path="/usr/bin/java",
                version="17.0.1",
                version_output="",
                is_compatible=True,
                runtime_type="OpenJDK",
            )
        )
        result.java_binaries.append(
            BinaryInfo(
                path="/opt/java/bin/java",
                version="unknown",
                version_output="",
                is_compatible=None,
                runtime_type="Unknown",
            )
        )
        assert result.java_compatible == "Unknown"

    def test_node_unknown_version(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="")
        result.node_binaries.append(
            BinaryInfo(
                path="/usr/local/bin/node",
                version="unknown",
                version_output="",
                is_compatible=None,
                runtime_type="NodeJS",
            )
        )
        assert result.node_compatible == "Unknown"

    def test_dotnet_unknown_version(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="")
        result.dotnet_binaries.append(
            BinaryInfo(
                path="/usr/share/dotnet/dotnet",
                version="unknown",
                version_output="",
                is_compatible=None,
                runtime_type=".NET",
            )
        )
        assert result.dotnet_compatible == "Unknown"

    def test_node_result(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="")
        result.node_binaries.append(
            BinaryInfo(
                path="/usr/local/bin/node",
                version="20.3.0",
                version_output="v20.3.0",
                is_compatible=True,
                runtime_type="NodeJS",
            )
        )
        assert result.node_found == "/usr/local/bin/node"
        assert result.node_versions == "20.3.0"
        assert result.node_compatible == "Yes"

    def test_dotnet_result(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="")
        result.dotnet_binaries.append(
            BinaryInfo(
                path="/usr/share/dotnet/dotnet",
                version="8.0.12",
                version_output="Microsoft.NETCore.App 8.0.12",
                is_compatible=True,
                runtime_type=".NET",
            )
        )
        assert result.dotnet_found == "/usr/share/dotnet/dotnet"
        assert result.dotnet_versions == "8.0.12"
        assert result.dotnet_compatible == "Yes"

    def test_error_result(self):
        result = ImageAnalysisResult(
            image_name="test:latest",
            image_id="",
            error="Failed to pull image",
        )
        assert result.error == "Failed to pull image"
        assert result.java_found == "None"


# ---------------------------------------------------------------------------
# Binary pattern matching
# ---------------------------------------------------------------------------


class TestBinaryPatterns:
    """Tests for binary matching regex patterns."""

    def test_java_binary_pattern(self):
        pattern = ImageAnalyzer.JAVA_BINARY_PATTERN
        assert pattern.match("/usr/bin/java") is not None
        assert pattern.match("/usr/lib/jvm/java-17/bin/java") is not None
        assert pattern.match("/opt/java/bin/java") is not None
        assert pattern.match("/usr/bin/javac") is None
        assert pattern.match("/usr/bin/javascript") is None

    def test_node_binary_pattern(self):
        pattern = ImageAnalyzer.NODE_BINARY_PATTERN
        assert pattern.match("/usr/bin/node") is not None
        assert pattern.match("/usr/local/bin/node") is not None
        assert pattern.match("/usr/bin/nodejs") is None
        assert pattern.match("/usr/bin/node_modules") is None

    def test_dotnet_binary_pattern(self):
        pattern = ImageAnalyzer.DOTNET_BINARY_PATTERN
        assert pattern.match("/usr/bin/dotnet") is not None
        assert pattern.match("/usr/share/dotnet/dotnet") is not None
        assert pattern.match("/usr/bin/dotnet-sdk") is None
