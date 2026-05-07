"""Tests for the JfrogCollector module."""

import csv as csv_mod
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.jfrog_client import JfrogClient, JfrogClientError
from src.jfrog_collector import JfrogCollector
from src.registry_collector import CSV_COLUMNS

SAMPLE_TAGS_JAVA = [
    {"name": "17", "last_modified": "2026-05-07T10:00:00+00:00", "start_ts": 1778162400},
    {"name": "17-20260507", "last_modified": "2026-05-07T10:01:00+00:00", "start_ts": 1778162460},
    {"name": "latest", "last_modified": "2026-05-07T10:02:00+00:00", "start_ts": 1778162520},
    {"name": "dev", "last_modified": "2026-05-07T10:03:00+00:00", "start_ts": 1778162580},
]

SAMPLE_TAGS_NODE = [
    {"name": "20", "last_modified": "2026-05-07T11:00:00+00:00", "start_ts": 1778166000},
    {"name": "latest", "last_modified": "2026-05-07T11:01:00+00:00", "start_ts": 1778166060},
]


@pytest.fixture
def jfrog_client():
    """Mock JfrogClient with spec-bound attributes."""
    return MagicMock(spec=JfrogClient)


@pytest.fixture
def collector(jfrog_client):
    return JfrogCollector(
        jfrog_client=jfrog_client,
        registry_host="acme.jfrog.io",
    )


class TestBuildImageRecord:
    def test_record_uses_jfrog_source(self, collector):
        rec = collector._build_image_record("docker-local", "java-compatible", "17")
        assert rec["source"] == "jfrog"
        assert rec["registry_org"] == "docker-local"
        assert rec["registry_repo"] == "java-compatible"
        assert rec["image_name"] == "acme.jfrog.io/docker-local/java-compatible:17"

    def test_record_has_all_collection_phase_keys(self, collector):
        rec = collector._build_image_record("r", "i", "t")
        for key in [
            "source",
            "container_name",
            "namespace",
            "object_type",
            "object_name",
            "registry_org",
            "registry_repo",
            "image_name",
            "image_id",
        ]:
            assert key in rec


class TestCollectImagesSingleImage:
    def test_returns_one_record_per_tag(self, collector, jfrog_client):
        jfrog_client.list_tags.return_value = SAMPLE_TAGS_JAVA
        result = collector.collect_images(
            repo="docker-local",
            image="java-compatible",
        )
        assert len(result) == 4
        assert all(r["source"] == "jfrog" for r in result)
        assert all(r["registry_repo"] == "java-compatible" for r in result)
        # list_images NOT called when an image is explicitly specified.
        jfrog_client.list_images.assert_not_called()

    def test_failure_on_specific_image_propagates(self, collector, jfrog_client):
        jfrog_client.list_tags.side_effect = JfrogClientError("boom")
        with pytest.raises(JfrogClientError):
            collector.collect_images(repo="docker-local", image="missing")

    def test_latest_only_propagated(self, collector, jfrog_client):
        jfrog_client.list_tags.return_value = SAMPLE_TAGS_JAVA
        result = collector.collect_images(
            repo="docker-local",
            image="java-compatible",
            latest_only=2,
        )
        # Sorted descending by start_ts; top two are 'dev' and 'latest'.
        names = {r["image_name"].split(":")[-1] for r in result}
        assert names == {"dev", "latest"}

    def test_include_exclude_filters_applied(self, collector, jfrog_client):
        jfrog_client.list_tags.return_value = SAMPLE_TAGS_JAVA
        result = collector.collect_images(
            repo="docker-local",
            image="java-compatible",
            include_tags=["17*"],
            exclude_tags=["17-*"],
        )
        # Only "17" survives.
        names = [r["image_name"].split(":")[-1] for r in result]
        assert names == ["17"]


class TestCollectImagesWholeRepo:
    def test_iterates_every_image(self, collector, jfrog_client):
        jfrog_client.list_images.return_value = ["java-compatible", "node-compatible"]
        jfrog_client.list_tags.side_effect = [SAMPLE_TAGS_JAVA, SAMPLE_TAGS_NODE]
        result = collector.collect_images(repo="docker-local")
        # 4 java tags + 2 node tags = 6 unique image_names.
        assert len(result) == 6
        repos_seen = {r["registry_repo"] for r in result}
        assert repos_seen == {"java-compatible", "node-compatible"}

    def test_skips_images_whose_list_tags_fails(self, collector, jfrog_client):
        jfrog_client.list_images.return_value = ["java-compatible", "broken"]
        jfrog_client.list_tags.side_effect = [
            SAMPLE_TAGS_JAVA,
            JfrogClientError("vanished"),
        ]
        result = collector.collect_images(repo="docker-local")
        assert len(result) == 4  # only java-compatible records
        assert all(r["registry_repo"] == "java-compatible" for r in result)

    def test_dedupes_image_name_collisions(self, collector, jfrog_client):
        # Two images that somehow yield the same image_name (impossible in
        # practice but exercises the dedup branch).
        jfrog_client.list_images.return_value = ["x"]
        jfrog_client.list_tags.return_value = [
            {"name": "v1", "start_ts": 1},
            {"name": "v1", "start_ts": 2},
        ]
        result = collector.collect_images(repo="docker-local")
        assert len(result) == 1


class TestSaveToCsv:
    def test_csv_has_unified_schema_and_jfrog_source(self, collector, tmp_path: Path):
        records = [
            collector._build_image_record("docker-local", "java-compatible", "17"),
            collector._build_image_record("docker-local", "node-compatible", "20"),
        ]
        csv_path = collector.save_to_csv(records, output_dir=str(tmp_path))
        assert Path(csv_path).exists()

        with open(csv_path) as f:
            reader = csv_mod.DictReader(f)
            assert reader.fieldnames == CSV_COLUMNS
            rows = list(reader)
        assert len(rows) == 2
        assert all(row["source"] == "jfrog" for row in rows)
        assert all(row["registry_org"] == "docker-local" for row in rows)

    def test_filename_includes_host_and_repo(self, collector, tmp_path: Path):
        records = [collector._build_image_record("docker-local", "x", "v1")]
        csv_path = collector.save_to_csv(records, output_dir=str(tmp_path))
        name = Path(csv_path).name
        assert name.startswith("acme.jfrog.io-docker-local-")
        assert name.endswith(".csv")

    def test_empty_records_produces_header_only_csv(self, collector, tmp_path: Path):
        csv_path = collector.save_to_csv([], output_dir=str(tmp_path))
        with open(csv_path) as f:
            reader = csv_mod.DictReader(f)
            assert reader.fieldnames == CSV_COLUMNS
            rows = list(reader)
        assert rows == []
