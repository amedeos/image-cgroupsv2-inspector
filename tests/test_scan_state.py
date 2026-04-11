"""Tests for the ScanState module."""

import json
import os
import threading

import pytest

from src.scan_state import STATE_VERSION, ScanState


class TestScanStateBasic:
    """Creation, properties, and simple mutations."""

    def test_empty_state(self):
        state = ScanState(target="my-cluster")
        assert state.target == "my-cluster"
        assert state.completed_count == 0
        assert state.version == STATE_VERSION

    def test_mark_completed(self):
        state = ScanState(target="c")
        state.mark_completed("img1")
        state.mark_completed("img2")
        assert state.completed_count == 2
        assert state.is_completed("img1")
        assert state.is_completed("img2")
        assert not state.is_completed("img3")

    def test_mark_completed_updates_timestamp(self):
        state = ScanState(target="c")
        ts_before = state.updated_at
        state.mark_completed("img1")
        assert state.updated_at >= ts_before

    def test_mark_completed_idempotent(self):
        state = ScanState(target="c")
        state.mark_completed("img1")
        state.mark_completed("img1")
        assert state.completed_count == 1

    def test_is_completed_empty(self):
        state = ScanState(target="c")
        assert not state.is_completed("anything")


class TestScanStateSaveLoad:
    """Round-trip serialisation."""

    def test_save_load_roundtrip(self, tmp_path):
        path = tmp_path / "state.json"
        state = ScanState(target="my-cluster")
        state.mark_completed("img-a")
        state.mark_completed("img-b")
        state.save(path)

        loaded = ScanState.load(path)
        assert loaded.target == "my-cluster"
        assert loaded.completed_count == 2
        assert loaded.is_completed("img-a")
        assert loaded.is_completed("img-b")
        assert loaded.version == STATE_VERSION

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "state.json"
        state = ScanState(target="t")
        state.save(path)
        assert path.exists()

    def test_save_overwrites_existing(self, tmp_path):
        path = tmp_path / "state.json"
        s1 = ScanState(target="t")
        s1.mark_completed("a")
        s1.save(path)

        s2 = ScanState(target="t")
        s2.mark_completed("b")
        s2.save(path)

        loaded = ScanState.load(path)
        assert loaded.is_completed("b")
        assert not loaded.is_completed("a")

    def test_load_missing_file_returns_empty(self, tmp_path):
        state = ScanState.load(tmp_path / "nonexistent.json")
        assert state.target == ""
        assert state.completed_count == 0

    def test_load_corrupt_file_returns_empty(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("NOT JSON {{{")
        state = ScanState.load(path)
        assert state.target == ""
        assert state.completed_count == 0

    def test_timestamps_preserved(self, tmp_path):
        path = tmp_path / "state.json"
        state = ScanState(target="t", started_at="2026-01-01T00:00:00Z")
        state.save(path)
        loaded = ScanState.load(path)
        assert loaded.started_at == "2026-01-01T00:00:00Z"

    def test_saved_json_format(self, tmp_path):
        path = tmp_path / "state.json"
        state = ScanState(target="my-target")
        state.mark_completed("z-image")
        state.mark_completed("a-image")
        state.mark_error("e-image")
        state.mark_timeout("t-image")
        state.save(path)

        data = json.loads(path.read_text())
        assert data["version"] == STATE_VERSION
        assert data["target"] == "my-target"
        assert data["completed_images"] == ["a-image", "z-image"]
        assert data["error_images"] == ["e-image"]
        assert data["timeout_images"] == ["t-image"]
        assert "started_at" in data
        assert "updated_at" in data

    def test_csv_filepath_roundtrip(self, tmp_path):
        path = tmp_path / "state.json"
        state = ScanState(target="t", csv_filepath="/tmp/out/scan.csv")
        state.save(path)

        loaded = ScanState.load(path)
        assert loaded.csv_filepath == "/tmp/out/scan.csv"

    def test_csv_filepath_none_by_default(self):
        state = ScanState(target="t")
        assert state.csv_filepath is None

    def test_csv_filepath_none_from_old_state_file(self, tmp_path):
        """State files created before csv_filepath was added should load fine."""
        path = tmp_path / "state.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "target": "t",
                    "started_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "completed_images": ["img1"],
                }
            )
        )
        loaded = ScanState.load(path)
        assert loaded.csv_filepath is None
        assert loaded.is_completed("img1")


class TestScanStateCategories:
    """Test error/timeout/completed categories."""

    def test_mark_error(self):
        state = ScanState(target="c")
        state.mark_error("img1")
        assert state.error_count == 1
        assert not state.is_completed("img1")
        assert state.is_scanned("img1")

    def test_mark_timeout(self):
        state = ScanState(target="c")
        state.mark_timeout("img1")
        assert state.timeout_count == 1
        assert not state.is_completed("img1")
        assert state.is_scanned("img1")

    def test_mark_error_moves_from_completed(self):
        state = ScanState(target="c")
        state.mark_completed("img1")
        state.mark_error("img1")
        assert state.completed_count == 0
        assert state.error_count == 1

    def test_mark_completed_moves_from_error(self):
        state = ScanState(target="c")
        state.mark_error("img1")
        state.mark_completed("img1")
        assert state.completed_count == 1
        assert state.error_count == 0

    def test_scanned_count(self):
        state = ScanState(target="c")
        state.mark_completed("a")
        state.mark_error("b")
        state.mark_timeout("c")
        assert state.scanned_count == 3

    def test_categories_roundtrip(self, tmp_path):
        path = tmp_path / "state.json"
        state = ScanState(target="t")
        state.mark_completed("ok")
        state.mark_error("fail")
        state.mark_timeout("slow")
        state.save(path)

        loaded = ScanState.load(path)
        assert loaded.is_completed("ok")
        assert not loaded.is_completed("fail")
        assert not loaded.is_completed("slow")
        assert loaded.is_scanned("fail")
        assert loaded.is_scanned("slow")
        assert loaded.error_count == 1
        assert loaded.timeout_count == 1

    def test_image_results_saved_with_completed(self, tmp_path):
        path = tmp_path / "state.json"
        result = {"java_binary": "/usr/bin/java", "java_version": "17.0.1"}
        state = ScanState(target="t")
        state.mark_completed("img1", result)
        state.save(path)

        loaded = ScanState.load(path)
        cached = loaded.get_result("img1")
        assert cached is not None
        assert cached["java_binary"] == "/usr/bin/java"

    def test_get_result_returns_none_for_unknown(self):
        state = ScanState(target="t")
        assert state.get_result("nonexistent") is None

    def test_v1_state_file_loads_as_completed(self, tmp_path):
        """v1 state files (no error/timeout) should load without errors."""
        path = tmp_path / "state.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "target": "t",
                    "started_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "completed_images": ["img1", "img2"],
                }
            )
        )
        loaded = ScanState.load(path)
        assert loaded.is_completed("img1")
        assert loaded.error_count == 0
        assert loaded.timeout_count == 0


class TestScanStateAtomicWrite:
    """Atomic write safety."""

    def test_no_partial_writes(self, tmp_path):
        """Concurrent saves should not corrupt the file."""
        path = tmp_path / "state.json"
        errors: list[Exception] = []

        def writer(n: int):
            try:
                state = ScanState(target="t")
                for i in range(20):
                    state.mark_completed(f"thread-{n}-img-{i}")
                    state.save(path)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        loaded = ScanState.load(path)
        assert loaded.target == "t"
        assert loaded.completed_count > 0

    def test_temp_file_cleaned_on_error(self, tmp_path, monkeypatch):
        """If os.replace fails, the temp file should be removed."""
        path = tmp_path / "state.json"
        state = ScanState(target="t")

        def failing_replace(src, dst):
            raise OSError("simulated failure")

        monkeypatch.setattr(os, "replace", failing_replace)

        with pytest.raises(OSError, match="simulated failure"):
            state.save(path)

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


class TestBuildStateFilename:
    """State file name generation."""

    def test_cluster_name(self):
        assert ScanState.build_state_filename("ocp-prod") == ".state_ocp-prod.json"

    def test_registry_host(self):
        assert ScanState.build_state_filename("quay.example.com") == ".state_quay.example.com.json"

    def test_registry_host_with_port(self):
        assert ScanState.build_state_filename("quay.example.com:8443") == ".state_quay.example.com_8443.json"

    def test_slashes_replaced(self):
        assert ScanState.build_state_filename("a/b/c") == ".state_a_b_c.json"
