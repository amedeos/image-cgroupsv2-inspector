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

STATE_VERSION = 2

ANALYSIS_KEYS = (
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
)


class ScanState:
    """Persistent scan state backed by a JSON file.

    Images are tracked in three categories:

    - **completed**: successfully analysed — skipped on resume.
    - **error**: failed with an analysis error — retried on resume.
    - **timeout**: exceeded the per-image timeout — retried on resume.

    Analysis results for completed images are cached in ``image_results``
    so they can be restored into the CSV on resume without re-scanning.

    Args:
        target: Identifier for the scan target (cluster name or registry host).
        completed_images: Set of successfully scanned image names.
        error_images: Set of image names that failed with an error.
        timeout_images: Set of image names that timed out.
        image_results: Mapping of image name -> analysis result dict
            (only for completed images).
        started_at: ISO-8601 timestamp when the scan started.
        updated_at: ISO-8601 timestamp of the last state update.
        version: State file schema version.
        csv_filepath: Path to the CSV output file used for this scan.
    """

    def __init__(
        self,
        target: str,
        completed_images: set[str] | None = None,
        error_images: set[str] | None = None,
        timeout_images: set[str] | None = None,
        image_results: dict[str, dict[str, str]] | None = None,
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
        self._error: set[str] = set(error_images) if error_images else set()
        self._timeout: set[str] = set(timeout_images) if timeout_images else set()
        self._results: dict[str, dict[str, str]] = dict(image_results) if image_results else {}
        self.csv_filepath = csv_filepath

    # -- counts / queries --

    @property
    def completed_count(self) -> int:
        return len(self._completed)

    @property
    def error_count(self) -> int:
        return len(self._error)

    @property
    def timeout_count(self) -> int:
        return len(self._timeout)

    @property
    def scanned_count(self) -> int:
        """Total images processed (completed + error + timeout)."""
        return len(self._completed) + len(self._error) + len(self._timeout)

    def is_completed(self, image_name: str) -> bool:
        return image_name in self._completed

    def is_scanned(self, image_name: str) -> bool:
        """True if the image was processed in any category."""
        return image_name in self._completed or image_name in self._error or image_name in self._timeout

    def get_result(self, image_name: str) -> dict[str, str] | None:
        """Return the cached analysis result dict, or None."""
        return self._results.get(image_name)

    # -- mutations --

    def mark_completed(self, image_name: str, result: dict[str, str] | None = None) -> None:
        """Record a successfully scanned image with its analysis results."""
        self._completed.add(image_name)
        self._error.discard(image_name)
        self._timeout.discard(image_name)
        if result is not None:
            self._results[image_name] = {k: result.get(k, "") for k in ANALYSIS_KEYS}
        self.updated_at = datetime.now(UTC).isoformat()

    def mark_error(self, image_name: str, result: dict[str, str] | None = None) -> None:
        """Record an image that failed with an error."""
        self._error.add(image_name)
        self._completed.discard(image_name)
        self._timeout.discard(image_name)
        if result is not None:
            self._results[image_name] = {k: result.get(k, "") for k in ANALYSIS_KEYS}
        self.updated_at = datetime.now(UTC).isoformat()

    def mark_timeout(self, image_name: str, result: dict[str, str] | None = None) -> None:
        """Record an image that exceeded the timeout."""
        self._timeout.add(image_name)
        self._completed.discard(image_name)
        self._error.discard(image_name)
        if result is not None:
            self._results[image_name] = {k: result.get(k, "") for k in ANALYSIS_KEYS}
        self.updated_at = datetime.now(UTC).isoformat()

    # -- persistence --

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
            "error_images": sorted(self._error),
            "timeout_images": sorted(self._timeout),
            "image_results": self._results,
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

        # v1 state files stored everything in completed_images (including
        # errors/timeouts) and had no image_results.  Treat them as
        # completed so existing state files still work on upgrade.
        return cls(
            target=data.get("target", ""),
            completed_images=set(data.get("completed_images", [])),
            error_images=set(data.get("error_images", [])),
            timeout_images=set(data.get("timeout_images", [])),
            image_results=data.get("image_results", {}),
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
