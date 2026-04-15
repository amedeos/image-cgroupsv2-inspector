"""Tests for the go_scan module — Go binary cgroups v2 compatibility logic."""

from src.go_scan import (
    GO_V2_AWARE_MODULES,
    GO_V2_RUNTIME_VERSION,
    GoBinaryInfo,
    check_go_compatibility,
    parse_go_version,
    semver_gte,
)
from src.image_analyzer import ImageAnalysisResult

# ---------------------------------------------------------------------------
# parse_go_version
# ---------------------------------------------------------------------------


class TestParseGoVersion:
    def test_full_version(self):
        assert parse_go_version("go1.22.5") == (1, 22)

    def test_minor_only(self):
        assert parse_go_version("go1.18") == (1, 18)

    def test_release_candidate(self):
        assert parse_go_version("go1.22rc1") == (1, 22)

    def test_invalid(self):
        assert parse_go_version("not-go") == (None, None)

    def test_empty(self):
        assert parse_go_version("") == (None, None)

    def test_go1_19(self):
        assert parse_go_version("go1.19") == (1, 19)

    def test_go1_21_3(self):
        assert parse_go_version("go1.21.3") == (1, 21)


# ---------------------------------------------------------------------------
# semver_gte
# ---------------------------------------------------------------------------


class TestSemverGte:
    def test_greater(self):
        assert semver_gte("v1.5.1", "v1.5.0") is True

    def test_less(self):
        assert semver_gte("v1.4.0", "v1.5.0") is False

    def test_equal(self):
        assert semver_gte("v1.5.0", "v1.5.0") is True

    def test_major_greater(self):
        assert semver_gte("v2.0.0", "v1.9.9") is True

    def test_major_less(self):
        assert semver_gte("v0.9.0", "v1.0.0") is False

    def test_patch_greater(self):
        assert semver_gte("v1.5.2", "v1.5.1") is True

    def test_no_v_prefix(self):
        assert semver_gte("1.5.0", "1.5.0") is True

    def test_invalid_version_a(self):
        assert semver_gte("invalid", "v1.0.0") is False

    def test_invalid_version_b(self):
        assert semver_gte("v1.0.0", "invalid") is False


# ---------------------------------------------------------------------------
# check_go_compatibility
# ---------------------------------------------------------------------------


class TestCheckGoCompatibility:
    def test_go_1_22_native_support(self):
        is_compat, reason = check_go_compatibility("go1.22.5", {})
        assert is_compat is True
        assert "runtime native v2 support" in reason

    def test_go_1_19_native_support(self):
        is_compat, reason = check_go_compatibility("go1.19", {})
        assert is_compat is True
        assert "runtime native v2 support" in reason

    def test_go_1_22_with_modules(self):
        is_compat, reason = check_go_compatibility("go1.22", {"go.uber.org/automaxprocs": "v1.6.0"})
        assert is_compat is True
        assert "runtime native" in reason

    def test_go_1_18_automaxprocs_v1_6_0(self):
        is_compat, reason = check_go_compatibility("go1.18", {"go.uber.org/automaxprocs": "v1.6.0"})
        assert is_compat is True
        assert "automaxprocs" in reason

    def test_go_1_18_automaxprocs_v1_5_1(self):
        is_compat, reason = check_go_compatibility("go1.18", {"go.uber.org/automaxprocs": "v1.5.1"})
        assert is_compat is True
        assert "automaxprocs" in reason

    def test_go_1_18_automaxprocs_v1_5_0(self):
        is_compat, reason = check_go_compatibility("go1.18", {"go.uber.org/automaxprocs": "v1.5.0"})
        assert is_compat is True
        assert "automaxprocs" in reason

    def test_go_1_18_automaxprocs_v1_4_0_needs_review(self):
        is_compat, reason = check_go_compatibility("go1.18", {"go.uber.org/automaxprocs": "v1.4.0"})
        assert is_compat is None
        assert "needs review" in reason

    def test_go_1_18_automemlimit_v0_7_0(self):
        is_compat, reason = check_go_compatibility("go1.18", {"github.com/KimMachineGun/automemlimit": "v0.7.0"})
        assert is_compat is True
        assert "automemlimit" in reason

    def test_go_1_18_automemlimit_v0_1_0(self):
        is_compat, reason = check_go_compatibility("go1.18", {"github.com/KimMachineGun/automemlimit": "v0.1.0"})
        assert is_compat is True
        assert "automemlimit" in reason

    def test_go_1_18_no_cgroup_modules(self):
        is_compat, reason = check_go_compatibility("go1.18", {})
        assert is_compat is False
        assert "no v2-aware" in reason

    def test_go_1_18_unknown_module_only(self):
        is_compat, reason = check_go_compatibility("go1.18", {"github.com/gorilla/mux": "v1.8.0"})
        assert is_compat is False
        assert "no v2-aware" in reason

    def test_unparseable_version(self):
        is_compat, reason = check_go_compatibility("notgo", {})
        assert is_compat is None
        assert "Cannot parse" in reason

    def test_containerd_cgroups_v1_0_0(self):
        is_compat, reason = check_go_compatibility("go1.17", {"github.com/containerd/cgroups": "v1.0.0"})
        assert is_compat is True
        assert "cgroups" in reason

    def test_runc_libcontainer_v1_1_0(self):
        is_compat, reason = check_go_compatibility(
            "go1.16", {"github.com/opencontainers/runc/libcontainer/cgroups": "v1.1.0"}
        )
        assert is_compat is True
        assert "cgroups" in reason


# ---------------------------------------------------------------------------
# GoBinaryInfo
# ---------------------------------------------------------------------------


class TestGoBinaryInfo:
    def test_basic_creation(self):
        info = GoBinaryInfo(
            path="/usr/local/bin/app",
            go_version="go1.22.5",
            modules={"go.uber.org/automaxprocs": "v1.6.0"},
            is_compatible=True,
            compliance_reason="Go 1.22 >= 1.19: runtime native v2 support",
        )
        assert info.path == "/usr/local/bin/app"
        assert info.go_version == "go1.22.5"
        assert info.is_compatible is True

    def test_default_values(self):
        info = GoBinaryInfo(path="/bin/app", go_version="go1.18")
        assert info.modules == {}
        assert info.is_compatible is None
        assert info.compliance_reason == ""


# ---------------------------------------------------------------------------
# ImageAnalysisResult Go properties
# ---------------------------------------------------------------------------


class TestImageAnalysisResultGoProperties:
    def test_no_go_binaries(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc")
        assert result.go_found == "None"
        assert result.go_versions == "None"
        assert result.go_compatible == "N/A"
        assert result.go_modules_str == "None"

    def test_single_compatible_binary(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc")
        result.go_binaries.append(
            GoBinaryInfo(
                path="/usr/local/bin/app",
                go_version="go1.22.5",
                modules={"go.uber.org/automaxprocs": "v1.6.0"},
                is_compatible=True,
                compliance_reason="native v2",
            )
        )
        assert result.go_found == "/usr/local/bin/app"
        assert result.go_versions == "go1.22.5"
        assert result.go_compatible == "Yes"
        assert result.go_modules_str == "go.uber.org/automaxprocs v1.6.0"

    def test_single_incompatible_binary(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc")
        result.go_binaries.append(
            GoBinaryInfo(
                path="/usr/bin/old",
                go_version="go1.16",
                modules={},
                is_compatible=False,
                compliance_reason="no v2 support",
            )
        )
        assert result.go_compatible == "No"

    def test_needs_review_compatibility(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc")
        result.go_binaries.append(
            GoBinaryInfo(
                path="/usr/bin/mystery",
                go_version="go1.18",
                modules={"go.uber.org/automaxprocs": "v1.4.0"},
                is_compatible=None,
                compliance_reason="needs review",
            )
        )
        assert result.go_compatible == "Needs Review"

    def test_unknown_compatibility(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc")
        result.go_binaries.append(
            GoBinaryInfo(
                path="/usr/bin/weird",
                go_version="goXYZ",
                is_compatible=None,
                compliance_reason="Cannot parse Go version: goXYZ",
            )
        )
        assert result.go_compatible == "Unknown"

    def test_mixed_compatible_and_incompatible(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc")
        result.go_binaries.append(
            GoBinaryInfo(
                path="/usr/bin/new",
                go_version="go1.22",
                is_compatible=True,
                compliance_reason="native",
            )
        )
        result.go_binaries.append(
            GoBinaryInfo(
                path="/usr/bin/old",
                go_version="go1.16",
                is_compatible=False,
                compliance_reason="no v2",
            )
        )
        assert result.go_compatible == "No"

    def test_mixed_compatible_and_needs_review(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc")
        result.go_binaries.append(
            GoBinaryInfo(
                path="/usr/bin/new",
                go_version="go1.22",
                is_compatible=True,
                compliance_reason="native",
            )
        )
        result.go_binaries.append(
            GoBinaryInfo(
                path="/usr/bin/old",
                go_version="go1.18",
                modules={"go.uber.org/automaxprocs": "v1.4.0"},
                is_compatible=None,
                compliance_reason="automaxprocs v1.4.0 < v1.5.0: needs review",
            )
        )
        assert result.go_compatible == "Needs Review"

    def test_multiple_binaries_paths(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc")
        result.go_binaries.append(GoBinaryInfo(path="/bin/a", go_version="go1.22", is_compatible=True))
        result.go_binaries.append(GoBinaryInfo(path="/bin/b", go_version="go1.21", is_compatible=True))
        assert result.go_found == "/bin/a; /bin/b"
        assert result.go_versions == "go1.22; go1.21"
        assert result.go_compatible == "Yes"

    def test_modules_str_no_modules(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc")
        result.go_binaries.append(GoBinaryInfo(path="/bin/a", go_version="go1.22", modules={}, is_compatible=True))
        assert result.go_modules_str == "None"

    def test_modules_str_multiple_modules(self):
        result = ImageAnalysisResult(image_name="test:latest", image_id="abc")
        result.go_binaries.append(
            GoBinaryInfo(
                path="/bin/a",
                go_version="go1.22",
                modules={
                    "go.uber.org/automaxprocs": "v1.6.0",
                    "github.com/KimMachineGun/automemlimit": "v0.7.0",
                },
                is_compatible=True,
            )
        )
        mods = result.go_modules_str
        assert "go.uber.org/automaxprocs v1.6.0" in mods
        assert "github.com/KimMachineGun/automemlimit v0.7.0" in mods
        assert "|" in mods


# ---------------------------------------------------------------------------
# GO_V2_AWARE_MODULES constants
# ---------------------------------------------------------------------------


class TestGoConstants:
    def test_runtime_version_tuple(self):
        assert GO_V2_RUNTIME_VERSION == (1, 19)

    def test_aware_modules_has_automaxprocs(self):
        assert "go.uber.org/automaxprocs" in GO_V2_AWARE_MODULES

    def test_aware_modules_has_automemlimit(self):
        assert "github.com/KimMachineGun/automemlimit" in GO_V2_AWARE_MODULES

    def test_aware_modules_has_containerd_cgroups(self):
        assert "github.com/containerd/cgroups" in GO_V2_AWARE_MODULES

    def test_aware_modules_has_runc_cgroups(self):
        assert "github.com/opencontainers/runc/libcontainer/cgroups" in GO_V2_AWARE_MODULES
