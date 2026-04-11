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
        state.save(path)

        data = json.loads(path.read_text())
        assert data["version"] == STATE_VERSION
        assert data["target"] == "my-target"
        assert data["completed_images"] == ["a-image", "z-image"]
        assert "started_at" in data
        assert "updated_at" in data


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
