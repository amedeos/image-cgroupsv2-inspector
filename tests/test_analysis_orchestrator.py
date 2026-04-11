"""Tests for the AnalysisOrchestrator module."""

import csv
from unittest.mock import MagicMock, patch

import pytest

from src.analysis_orchestrator import AnalysisOrchestrator
from src.image_analyzer import BinaryInfo, ImageAnalysisResult
from src.registry_collector import CSV_COLUMNS
from src.scan_state import ScanState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_analyzer():
    """Create a mock ImageAnalyzer."""
    with patch("src.analysis_orchestrator.ImageAnalyzer") as mock_cls:
        analyzer_instance = MagicMock()
        mock_cls.return_value = analyzer_instance
        yield analyzer_instance


@pytest.fixture
def orchestrator():
    """Create an AnalysisOrchestrator."""
    return AnalysisOrchestrator(
        rootfs_path="/tmp/rootfs",
        pull_secret_path=".pull-secret",
    )


@pytest.fixture
def sample_images():
    """Sample image records in unified schema."""
    return [
        {
            "source": "registry",
            "container_name": "",
            "namespace": "",
            "object_type": "",
            "object_name": "",
            "registry_org": "testorg",
            "registry_repo": "java-app",
            "image_name": "quay.example.com/testorg/java-app:17",
            "image_id": "",
        },
        {
            "source": "registry",
            "container_name": "",
            "namespace": "",
            "object_type": "",
            "object_name": "",
            "registry_org": "testorg",
            "registry_repo": "node-app",
            "image_name": "quay.example.com/testorg/node-app:20",
            "image_id": "",
        },
        {
            "source": "registry",
            "container_name": "",
            "namespace": "",
            "object_type": "",
            "object_name": "",
            "registry_org": "testorg",
            "registry_repo": "java-app",
            "image_name": "quay.example.com/testorg/java-app:17",
            "image_id": "",
        },
    ]


def _make_java_result(image_name: str) -> ImageAnalysisResult:
    """Build a result with one compatible Java binary."""
    result = ImageAnalysisResult(image_name=image_name, image_id="")
    result.java_binaries.append(
        BinaryInfo(
            path="/usr/bin/java",
            version="17.0.1",
            version_output="openjdk 17.0.1",
            is_compatible=True,
            runtime_type="OpenJDK",
        )
    )
    return result


def _make_node_result(image_name: str) -> ImageAnalysisResult:
    """Build a result with one compatible Node binary."""
    result = ImageAnalysisResult(image_name=image_name, image_id="")
    result.node_binaries.append(
        BinaryInfo(
            path="/usr/local/bin/node",
            version="20.3.0",
            version_output="v20.3.0",
            is_compatible=True,
            runtime_type="NodeJS",
        )
    )
    return result


# ---------------------------------------------------------------------------
# TestAnalysisOrchestratorAnalyze
# ---------------------------------------------------------------------------


class TestAnalysisOrchestratorAnalyze:
    """Test the analyze_images method."""

    def test_deduplication(self, orchestrator, mock_analyzer, sample_images):
        """3 records with 2 unique image_names -> analyze called 2 times."""
        mock_analyzer.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")

        count, _, _skipped = orchestrator.analyze_images(sample_images)

        assert mock_analyzer.analyze_image.call_count == 2
        assert count == 2

    def test_results_applied_to_all_matching_records(self, orchestrator, mock_analyzer, sample_images):
        """Both records sharing java-app:17 should get analysis results."""
        java_result = _make_java_result("quay.example.com/testorg/java-app:17")
        node_result = _make_node_result("quay.example.com/testorg/node-app:20")

        def side_effect(image_name, debug=False):
            if "java-app" in image_name:
                return java_result
            return node_result

        mock_analyzer.analyze_image.side_effect = side_effect

        orchestrator.analyze_images(sample_images)

        java_records = [r for r in sample_images if r["image_name"] == "quay.example.com/testorg/java-app:17"]
        assert len(java_records) == 2
        for rec in java_records:
            assert rec["java_binary"] == "/usr/bin/java"
            assert rec["java_version"] == "17.0.1"
            assert rec["java_cgroup_v2_compatible"] == "Yes"

    def test_result_mapping_keys(self, orchestrator, mock_analyzer, sample_images):
        """Verify all unified schema analysis keys are populated."""
        java_result = _make_java_result("quay.example.com/testorg/java-app:17")
        node_result = _make_node_result("quay.example.com/testorg/node-app:20")

        def side_effect(image_name, debug=False):
            if "java-app" in image_name:
                return java_result
            return node_result

        mock_analyzer.analyze_image.side_effect = side_effect

        orchestrator.analyze_images(sample_images)

        analysis_keys = [
            "java_binary",
            "java_version",
            "java_cgroup_v2_compatible",
            "node_binary",
            "node_version",
            "node_cgroup_v2_compatible",
            "dotnet_binary",
            "dotnet_version",
            "dotnet_cgroup_v2_compatible",
            "analysis_error",
        ]
        for rec in sample_images:
            for key in analysis_keys:
                assert key in rec

    def test_error_handling(self, orchestrator, mock_analyzer, sample_images):
        """Exception for one image is captured; other image still analyzed."""
        node_result = _make_node_result("quay.example.com/testorg/node-app:20")

        def side_effect(image_name, debug=False):
            if "java-app" in image_name:
                raise RuntimeError("pull failed")
            return node_result

        mock_analyzer.analyze_image.side_effect = side_effect

        count, _, _skipped = orchestrator.analyze_images(sample_images)

        assert count == 1

        java_records = [r for r in sample_images if r["image_name"] == "quay.example.com/testorg/java-app:17"]
        for rec in java_records:
            assert rec["analysis_error"] == "pull failed"

        node_records = [r for r in sample_images if r["image_name"] == "quay.example.com/testorg/node-app:20"]
        assert node_records[0]["node_binary"] == "/usr/local/bin/node"

    def test_images_mutated_in_place(self, orchestrator, mock_analyzer, sample_images):
        """Caller's list is mutated; no new list returned."""
        mock_analyzer.analyze_image.return_value = _make_java_result("x")

        original_id = id(sample_images)
        orchestrator.analyze_images(sample_images)

        assert id(sample_images) == original_id
        assert "java_binary" in sample_images[0]

    def test_returns_count_and_filepath(self, orchestrator, mock_analyzer, sample_images, tmp_path):
        """Returns (analyzed_count, csv_filepath, skipped)."""
        mock_analyzer.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")
        csv_path = str(tmp_path / "results.csv")

        count, returned_path, skipped = orchestrator.analyze_images(sample_images, csv_filepath=csv_path)

        assert count == 2
        assert returned_path == csv_path
        assert skipped == []

    def test_returns_none_filepath_when_not_given(self, orchestrator, mock_analyzer, sample_images):
        mock_analyzer.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")

        count, returned_path, skipped = orchestrator.analyze_images(sample_images)

        assert count == 2
        assert returned_path is None
        assert skipped == []


# ---------------------------------------------------------------------------
# TestAnalysisOrchestratorCSV
# ---------------------------------------------------------------------------


class TestAnalysisOrchestratorCSV:
    """Test incremental CSV writing."""

    def test_csv_written_after_each_image(self, orchestrator, mock_analyzer, sample_images, tmp_path):
        """CSV file exists after analysis completes."""
        mock_analyzer.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")
        csv_path = str(tmp_path / "results.csv")

        orchestrator.analyze_images(sample_images, csv_filepath=csv_path)

        assert (tmp_path / "results.csv").exists()

    def test_csv_header_matches_unified_schema(self, orchestrator, mock_analyzer, sample_images, tmp_path):
        mock_analyzer.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")
        csv_path = str(tmp_path / "results.csv")

        orchestrator.analyze_images(sample_images, csv_filepath=csv_path)

        with open(csv_path) as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == CSV_COLUMNS

    def test_csv_row_count_includes_all_records(self, orchestrator, mock_analyzer, sample_images, tmp_path):
        """CSV has ALL records, not just unique ones."""
        mock_analyzer.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")
        csv_path = str(tmp_path / "results.csv")

        orchestrator.analyze_images(sample_images, csv_filepath=csv_path)

        with open(csv_path) as f:
            reader = csv.reader(f)
            next(reader)
            rows = list(reader)
        assert len(rows) == 3

    def test_csv_has_analysis_results(self, orchestrator, mock_analyzer, sample_images, tmp_path):
        java_result = _make_java_result("quay.example.com/testorg/java-app:17")
        node_result = _make_node_result("quay.example.com/testorg/node-app:20")

        def side_effect(image_name, debug=False):
            if "java-app" in image_name:
                return java_result
            return node_result

        mock_analyzer.analyze_image.side_effect = side_effect
        csv_path = str(tmp_path / "results.csv")

        orchestrator.analyze_images(sample_images, csv_filepath=csv_path)

        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        java_rows = [r for r in rows if "java-app" in r["image_name"]]
        assert len(java_rows) == 2
        for r in java_rows:
            assert r["java_binary"] == "/usr/bin/java"

    def test_csv_not_written_when_filepath_is_none(self, orchestrator, mock_analyzer, sample_images, tmp_path):
        mock_analyzer.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")

        _count, filepath, _skipped = orchestrator.analyze_images(sample_images)

        assert filepath is None

    def test_csv_uses_csv_columns(self, orchestrator, mock_analyzer, sample_images, tmp_path):
        """Verify the CSV columns come from registry_collector.CSV_COLUMNS."""
        mock_analyzer.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")
        csv_path = str(tmp_path / "results.csv")

        orchestrator.analyze_images(sample_images, csv_filepath=csv_path)

        with open(csv_path) as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
        assert list(fieldnames) == CSV_COLUMNS


# ---------------------------------------------------------------------------
# TestAnalysisOrchestratorOpenShift
# ---------------------------------------------------------------------------


class TestAnalysisOrchestratorOpenShift:
    """Test with OpenShift-mode image records."""

    def test_works_with_openshift_source(self, mock_analyzer):
        orchestrator = AnalysisOrchestrator(
            rootfs_path="/tmp/rootfs",
            pull_secret_path=".pull-secret",
            internal_registry_route="registry.apps.example.com",
            openshift_token="sha256~token123",
        )
        images = [
            {
                "source": "openshift",
                "container_name": "app",
                "namespace": "my-ns",
                "object_type": "Deployment",
                "object_name": "my-deploy",
                "registry_org": "",
                "registry_repo": "",
                "image_name": "quay.io/my-org/my-image:latest",
                "image_id": "sha256:abc123",
            },
        ]
        mock_analyzer.analyze_image.return_value = _make_java_result("quay.io/my-org/my-image:latest")

        count, _, _skipped = orchestrator.analyze_images(images)

        assert count == 1
        assert images[0]["java_binary"] == "/usr/bin/java"

    def test_internal_registry_route_passed_to_analyzer(self):
        with patch("src.analysis_orchestrator.ImageAnalyzer") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")
            mock_cls.return_value = mock_instance

            orchestrator = AnalysisOrchestrator(
                rootfs_path="/tmp/rootfs",
                internal_registry_route="registry.apps.example.com",
                openshift_token="sha256~token123",
            )
            orchestrator.analyze_images([{"image_name": "quay.io/test:latest"}])

            mock_cls.assert_called_once_with(
                "/tmp/rootfs",
                None,
                "registry.apps.example.com",
                "sha256~token123",
            )

    def test_openshift_token_passed_to_analyzer(self):
        with patch("src.analysis_orchestrator.ImageAnalyzer") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")
            mock_cls.return_value = mock_instance

            orchestrator = AnalysisOrchestrator(
                rootfs_path="/tmp/rootfs",
                pull_secret_path=".pull-secret",
                openshift_token="sha256~mytoken",
            )
            orchestrator.analyze_images([{"image_name": "quay.io/test:latest"}])

            args = mock_cls.call_args[0]
            assert args[3] == "sha256~mytoken"


# ---------------------------------------------------------------------------
# TestAnalysisOrchestratorResume
# ---------------------------------------------------------------------------


class TestAnalysisOrchestratorResume:
    """Test resume / state-file integration."""

    def test_resume_skips_completed_images(self, mock_analyzer, sample_images, tmp_path):
        """With resume=True and a pre-populated state, already-scanned images are skipped."""
        state_path = str(tmp_path / ".state_test.json")
        pre_state = ScanState(target="test")
        pre_state.mark_completed("quay.example.com/testorg/java-app:17")
        pre_state.save(state_path)

        mock_analyzer.analyze_image.return_value = _make_node_result("quay.example.com/testorg/node-app:20")

        orchestrator = AnalysisOrchestrator(
            rootfs_path="/tmp/rootfs",
            pull_secret_path=".pull-secret",
            state_file_path=state_path,
            resume=True,
        )
        count, _, _skipped = orchestrator.analyze_images(sample_images)

        assert count == 1
        assert mock_analyzer.analyze_image.call_count == 1
        mock_analyzer.analyze_image.assert_called_once_with("quay.example.com/testorg/node-app:20", debug=False)

    def test_state_file_written_without_resume(self, mock_analyzer, sample_images, tmp_path):
        """Without --resume, the state file is still written progressively."""
        state_path = str(tmp_path / ".state_test.json")
        mock_analyzer.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")

        orchestrator = AnalysisOrchestrator(
            rootfs_path="/tmp/rootfs",
            pull_secret_path=".pull-secret",
            state_file_path=state_path,
            resume=False,
        )
        orchestrator.analyze_images(sample_images)

        assert (tmp_path / ".state_test.json").exists()
        loaded = ScanState.load(state_path)
        assert loaded.completed_count == 2

    def test_state_file_not_written_when_path_is_none(self, mock_analyzer, sample_images, tmp_path):
        """When state_file_path is None, no state file should be created."""
        mock_analyzer.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")

        orchestrator = AnalysisOrchestrator(
            rootfs_path="/tmp/rootfs",
            pull_secret_path=".pull-secret",
            state_file_path=None,
            resume=False,
        )
        orchestrator.analyze_images(sample_images)

        assert len(list(tmp_path.glob("*.json"))) == 0

    def test_resume_with_missing_state_file(self, mock_analyzer, sample_images, tmp_path):
        """--resume with no prior state file: warn and do full scan."""
        state_path = str(tmp_path / ".state_missing.json")
        mock_analyzer.analyze_image.return_value = ImageAnalysisResult(image_name="test", image_id="")

        orchestrator = AnalysisOrchestrator(
            rootfs_path="/tmp/rootfs",
            pull_secret_path=".pull-secret",
            state_file_path=state_path,
            resume=True,
        )
        count, _, _skipped = orchestrator.analyze_images(sample_images)

        assert count == 2
        assert mock_analyzer.analyze_image.call_count == 2

    def test_timed_out_image_marked_completed(self, mock_analyzer, sample_images, tmp_path):
        """Timed-out images should be marked as completed in the state file."""
        state_path = str(tmp_path / ".state_test.json")

        def side_effect(image_name, debug=False):
            if "java-app" in image_name:
                raise RuntimeError("pull failed")
            return _make_node_result(image_name)

        mock_analyzer.analyze_image.side_effect = side_effect

        orchestrator = AnalysisOrchestrator(
            rootfs_path="/tmp/rootfs",
            pull_secret_path=".pull-secret",
            state_file_path=state_path,
            resume=False,
        )
        orchestrator.analyze_images(sample_images)

        loaded = ScanState.load(state_path)
        assert loaded.is_completed("quay.example.com/testorg/java-app:17")
        assert loaded.is_completed("quay.example.com/testorg/node-app:20")

    def test_clean_state_deletes_file(self, tmp_path):
        """Simulate --clean-state: the state file is removed."""
        state_path = tmp_path / ".state_test.json"
        ScanState(target="t").save(state_path)
        assert state_path.exists()

        import os

        os.remove(str(state_path))
        assert not state_path.exists()

    def test_clean_state_no_file(self, tmp_path):
        """--clean-state with no existing file: no error."""
        state_path = tmp_path / ".state_missing.json"
        assert not state_path.exists()
