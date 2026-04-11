"""
Scan State Module

Manages persistent scan state for resume support.
Tracks which images have already been scanned so that interrupted scans
can be resumed without re-processing completed images.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

STATE_VERSION = 1


class ScanState:
    """Persistent scan state backed by a JSON file.

    Args:
        target: Identifier for the scan target (cluster name or registry host).
        completed_images: Set of image names already processed.
        started_at: ISO-8601 timestamp when the scan started.
        updated_at: ISO-8601 timestamp of the last state update.
        version: State file schema version.
        csv_filepath: Path to the CSV output file used for this scan.
    """

    def __init__(
        self,
        target: str,
        completed_images: set[str] | None = None,
        started_at: str | None = None,
        updated_at: str | None = None,
        version: int = STATE_VERSION,
        csv_filepath: str | None = None,
    ) -> None:
        self.version = version
        self.target = target
        now = datetime.now(UTC).isoformat()
        self.started_at = started_at or now
        self.updated_at = updated_at or now
        self._completed: set[str] = set(completed_images) if completed_images else set()
        self.csv_filepath = csv_filepath

    @property
    def completed_count(self) -> int:
        return len(self._completed)

    def is_completed(self, image_name: str) -> bool:
        return image_name in self._completed

    def mark_completed(self, image_name: str) -> None:
        """Add an image to the completed set and update the timestamp."""
        self._completed.add(image_name)
        self.updated_at = datetime.now(UTC).isoformat()

    def save(self, path: str | Path) -> None:
        """Atomically write the state to *path* (write tmp + os.replace)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": self.version,
            "target": self.target,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "csv_filepath": self.csv_filepath,
            "completed_images": sorted(self._completed),
        }
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            os.replace(tmp, str(path))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    @classmethod
    def load(cls, path: str | Path) -> ScanState:
        """Load state from *path*.  Returns an empty state if the file
        does not exist or cannot be parsed."""
        path = Path(path)
        if not path.exists():
            return cls(target="")
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return cls(target="")
        return cls(
            target=data.get("target", ""),
            completed_images=set(data.get("completed_images", [])),
            started_at=data.get("started_at"),
            updated_at=data.get("updated_at"),
            version=data.get("version", STATE_VERSION),
            csv_filepath=data.get("csv_filepath"),
        )

    @staticmethod
    def build_state_filename(target: str) -> str:
        """Build the state file name for a given target (cluster or registry host)."""
        safe = target.replace("/", "_").replace(":", "_")
        return f".state_{safe}.json"
