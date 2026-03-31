"""Tests for the RegistryCollector module."""

import csv
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.quay_client import QuayAPIError, QuayNotFoundError
from src.registry_collector import CSV_COLUMNS, RegistryCollector

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TAGS = [
    {
        "name": "17",
        "manifest_digest": "sha256:aaa",
        "size": 100,
        "last_modified": "Mon, 31 Mar 2026 00:00:00 -0000",
        "start_ts": 1743379200,
    },
    {
        "name": "latest",
        "manifest_digest": "sha256:bbb",
        "size": 100,
        "last_modified": "Sun, 30 Mar 2026 00:00:00 -0000",
        "start_ts": 1743292800,
    },
    {
        "name": "dev",
        "manifest_digest": "sha256:ccc",
        "size": 100,
        "last_modified": "Sat, 29 Mar 2026 00:00:00 -0000",
        "start_ts": 1743206400,
    },
]


@pytest.fixture
def mock_quay_client():
    """Create a mock QuayClient."""
    client = MagicMock()
    client.list_repositories.return_value = [
        {"namespace": "testorg", "name": "java-compatible", "state": "NORMAL"},
        {"namespace": "testorg", "name": "node-compatible", "state": "NORMAL"},
    ]
    client.list_tags.return_value = list(SAMPLE_TAGS)
    return client


@pytest.fixture
def collector(mock_quay_client):
    """Create a RegistryCollector with mocked QuayClient."""
    return RegistryCollector(
        quay_client=mock_quay_client,
        registry_host="quay.example.com",
    )


# ---------------------------------------------------------------------------
# TestRegistryCollectorCollectImages
# ---------------------------------------------------------------------------


class TestRegistryCollectorCollectImages:
    """Test the collect_images method."""

    def test_collect_all_repos(self, collector, mock_quay_client):
        images = collector.collect_images("testorg")

        mock_quay_client.list_repositories.assert_called_once_with("testorg")
        assert mock_quay_client.list_tags.call_count == 2
        assert len(images) == 6

    def test_collect_specific_repo(self, collector, mock_quay_client):
        images = collector.collect_images("testorg", repo="java-compatible")

        mock_quay_client.list_repositories.assert_not_called()
        mock_quay_client.list_tags.assert_called_once_with("testorg", "java-compatible")
        assert len(images) == 3

    def test_image_record_has_all_schema_keys(self, collector):
        images = collector.collect_images("testorg", repo="java-compatible")

        expected_keys = {
            "source",
            "container_name",
            "namespace",
            "object_type",
            "object_name",
            "registry_org",
            "registry_repo",
            "image_name",
            "image_id",
        }
        for img in images:
            assert expected_keys.issubset(img.keys())

    def test_source_is_registry(self, collector):
        images = collector.collect_images("testorg", repo="java-compatible")
        assert all(img["source"] == "registry" for img in images)

    def test_openshift_fields_empty(self, collector):
        images = collector.collect_images("testorg", repo="java-compatible")
        for img in images:
            assert img["container_name"] == ""
            assert img["namespace"] == ""
            assert img["object_type"] == ""
            assert img["object_name"] == ""

    def test_registry_org_set(self, collector):
        images = collector.collect_images("testorg", repo="java-compatible")
        assert all(img["registry_org"] == "testorg" for img in images)

    def test_registry_repo_set(self, collector):
        images = collector.collect_images("testorg", repo="java-compatible")
        assert all(img["registry_repo"] == "java-compatible" for img in images)

    def test_image_name_format(self, collector):
        images = collector.collect_images("testorg", repo="java-compatible")
        tag_names = {"17", "latest", "dev"}
        for img in images:
            assert img["image_name"].startswith("quay.example.com/testorg/java-compatible:")
            tag = img["image_name"].split(":")[-1]
            assert tag in tag_names

    def test_image_id_empty(self, collector):
        images = collector.collect_images("testorg", repo="java-compatible")
        assert all(img["image_id"] == "" for img in images)

    def test_deduplication(self, collector, mock_quay_client):
        mock_quay_client.list_repositories.return_value = [
            {"namespace": "testorg", "name": "same-repo", "state": "NORMAL"},
            {"namespace": "testorg", "name": "same-repo", "state": "NORMAL"},
        ]
        mock_quay_client.list_tags.return_value = [
            {"name": "v1.0", "manifest_digest": "sha256:aaa", "size": 100, "start_ts": 1743379200},
        ]

        images = collector.collect_images("testorg")
        assert len(images) == 1


# ---------------------------------------------------------------------------
# TestRegistryCollectorFilterTags
# ---------------------------------------------------------------------------


class TestRegistryCollectorFilterTags:
    """Test tag filtering logic."""

    def test_no_filters_returns_all(self, collector):
        result = collector._filter_tags(SAMPLE_TAGS)
        assert len(result) == 3

    def test_include_pattern(self, collector):
        result = collector._filter_tags(SAMPLE_TAGS, include_tags=["1*"])
        assert len(result) == 1
        assert result[0]["name"] == "17"

    def test_exclude_dev(self, collector):
        result = collector._filter_tags(SAMPLE_TAGS, exclude_tags=["dev"])
        assert len(result) == 2
        names = [t["name"] for t in result]
        assert "dev" not in names

    def test_exclude_glob(self, collector):
        result = collector._filter_tags(SAMPLE_TAGS, exclude_tags=["*dev*"])
        assert len(result) == 2
        names = [t["name"] for t in result]
        assert "dev" not in names

    def test_include_and_exclude_combined(self, collector):
        result = collector._filter_tags(
            SAMPLE_TAGS,
            include_tags=["*"],
            exclude_tags=["dev"],
        )
        assert len(result) == 2
        names = [t["name"] for t in result]
        assert "17" in names
        assert "latest" in names

    def test_latest_only_1(self, collector):
        result = collector._filter_tags(SAMPLE_TAGS, latest_only=1)
        assert len(result) == 1
        assert result[0]["name"] == "17"

    def test_latest_only_2(self, collector):
        result = collector._filter_tags(SAMPLE_TAGS, latest_only=2)
        assert len(result) == 2
        assert result[0]["name"] == "17"
        assert result[1]["name"] == "latest"

    def test_latest_only_exceeds_count(self, collector):
        result = collector._filter_tags(SAMPLE_TAGS, latest_only=10)
        assert len(result) == 3

    def test_exclude_latest(self, collector):
        result = collector._filter_tags(SAMPLE_TAGS, exclude_tags=["latest"])
        names = [t["name"] for t in result]
        assert "latest" not in names
        assert len(result) == 2

    def test_all_tags_filtered_out(self, collector):
        result = collector._filter_tags(SAMPLE_TAGS, include_tags=["nonexistent-*"])
        assert result == []

    def test_processing_order(self, collector):
        result = collector._filter_tags(
            SAMPLE_TAGS,
            include_tags=["*"],
            exclude_tags=["dev"],
            latest_only=1,
        )
        assert len(result) == 1
        assert result[0]["name"] == "17"


# ---------------------------------------------------------------------------
# TestRegistryCollectorSaveToCSV
# ---------------------------------------------------------------------------


class TestRegistryCollectorSaveToCSV:
    """Test CSV output."""

    def test_csv_file_created(self, collector, tmp_path):
        images = collector.collect_images("testorg", repo="java-compatible")
        filepath = collector.save_to_csv(images, output_dir=str(tmp_path))
        assert Path(filepath).exists()

    def test_csv_filename_format(self, collector, tmp_path):
        images = collector.collect_images("testorg", repo="java-compatible")
        filepath = collector.save_to_csv(images, output_dir=str(tmp_path))
        filename = Path(filepath).name
        assert filename.startswith("quay.example.com-testorg-")
        assert filename.endswith(".csv")

    def test_csv_header_columns(self, collector, tmp_path):
        images = collector.collect_images("testorg", repo="java-compatible")
        filepath = collector.save_to_csv(images, output_dir=str(tmp_path))

        with open(filepath) as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == CSV_COLUMNS

    def test_csv_row_count(self, collector, tmp_path):
        images = collector.collect_images("testorg", repo="java-compatible")
        filepath = collector.save_to_csv(images, output_dir=str(tmp_path))

        with open(filepath) as f:
            reader = csv.reader(f)
            next(reader)
            rows = list(reader)
        assert len(rows) == 3

    def test_csv_data_matches_records(self, collector, tmp_path):
        images = collector.collect_images("testorg", repo="java-compatible")
        filepath = collector.save_to_csv(images, output_dir=str(tmp_path))

        with open(filepath) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        for row in rows:
            assert row["source"] == "registry"
            assert row["registry_org"] == "testorg"
            assert row["registry_repo"] == "java-compatible"
            assert row["image_name"].startswith("quay.example.com/testorg/java-compatible:")

    def test_output_dir_created(self, collector, tmp_path):
        new_dir = tmp_path / "nested" / "output"
        images = collector.collect_images("testorg", repo="java-compatible")
        filepath = collector.save_to_csv(images, output_dir=str(new_dir))
        assert Path(filepath).exists()
        assert new_dir.exists()

    def test_analysis_columns_empty(self, collector, tmp_path):
        images = collector.collect_images("testorg", repo="java-compatible")
        filepath = collector.save_to_csv(images, output_dir=str(tmp_path))

        analysis_cols = [
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

        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                for col in analysis_cols:
                    assert row[col] == "", f"Expected '{col}' to be empty, got '{row[col]}'"


# ---------------------------------------------------------------------------
# TestRegistryCollectorErrorHandling
# ---------------------------------------------------------------------------


class TestRegistryCollectorErrorHandling:
    """Test error handling."""

    def test_list_tags_failure_skips_repo(self, collector, mock_quay_client):
        def list_tags_side_effect(org, repo_name):
            if repo_name == "java-compatible":
                raise QuayNotFoundError(f"Not found: {repo_name}")
            return list(SAMPLE_TAGS)

        mock_quay_client.list_tags.side_effect = list_tags_side_effect

        images = collector.collect_images("testorg")
        assert len(images) == 3
        image_names = [img["image_name"] for img in images]
        assert all("node-compatible" in name for name in image_names)

    def test_list_tags_api_error_continues(self, collector, mock_quay_client):
        def list_tags_side_effect(org, repo_name):
            if repo_name == "java-compatible":
                raise QuayAPIError("Server error")
            return list(SAMPLE_TAGS)

        mock_quay_client.list_tags.side_effect = list_tags_side_effect

        images = collector.collect_images("testorg")
        assert len(images) == 3

    def test_specific_repo_not_found_propagates(self, collector, mock_quay_client):
        mock_quay_client.list_tags.side_effect = QuayNotFoundError("Not found")

        with pytest.raises(QuayNotFoundError):
            collector.collect_images("testorg", repo="nonexistent")

    def test_empty_org(self, collector, mock_quay_client):
        mock_quay_client.list_repositories.return_value = []
        images = collector.collect_images("emptyorg")
        assert images == []

    def test_repo_with_zero_tags_after_filtering(self, collector, mock_quay_client):
        mock_quay_client.list_tags.return_value = [
            {"name": "dev-only", "manifest_digest": "sha256:aaa", "size": 100, "start_ts": 1743379200},
        ]
        images = collector.collect_images("testorg", exclude_tags=["dev-*"])
        assert images == []
