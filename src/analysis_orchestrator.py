"""
Analysis Orchestrator Module

Orchestrates image analysis with incremental CSV saving.
Works with image records from both OpenShift and registry collectors.
"""

import csv
import logging
import signal
import traceback

from .image_analyzer import ImageAnalysisResult, ImageAnalyzer
from .registry_collector import CSV_COLUMNS

logger = logging.getLogger(__name__)


class _ImageTimeout(Exception):
    """Raised when per-image analysis exceeds the configured timeout."""


class AnalysisOrchestrator:
    """Orchestrates image analysis with incremental CSV saving.

    Source-agnostic: works with image records (plain dicts) from both
    OpenShift and registry collectors.

    Args:
        rootfs_path: Path where rootfs directory exists.
        pull_secret_path: Path to pull-secret for authentication.
        internal_registry_route: External hostname for OpenShift internal
            registry (only for OpenShift mode, None for registry mode).
        openshift_token: Bearer token for internal registry auth
            (only for OpenShift mode, None for registry mode).
        image_timeout: Maximum seconds for pulling and scanning each
            individual image.  0 disables the timeout.
    """

    def __init__(
        self,
        rootfs_path: str,
        pull_secret_path: str | None = None,
        internal_registry_route: str | None = None,
        openshift_token: str | None = None,
        image_timeout: int = 600,
    ) -> None:
        self.rootfs_path = rootfs_path
        self.pull_secret_path = pull_secret_path
        self.internal_registry_route = internal_registry_route
        self.openshift_token = openshift_token
        self.image_timeout = image_timeout

    def _save_csv(self, images: list[dict], filepath: str) -> None:
        """Write image records to CSV using the unified schema."""
        with open(filepath, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for image in images:
                row = {col: image.get(col, "") for col in CSV_COLUMNS}
                writer.writerow(row)

    def analyze_images(
        self,
        images: list[dict],
        csv_filepath: str | None = None,
        debug: bool = False,
        logger: logging.Logger | None = None,
    ) -> tuple[int, str | None, list[str]]:
        """Analyze images and save CSV incrementally.

        For each unique image_name:
        1. Call ImageAnalyzer.analyze_image()
        2. Update ALL records in ``images`` that share this image_name
           with the analysis results
        3. Write the FULL CSV with current progress (crash resilience)
        4. Continue to next image

        After all images are analyzed, do a final CSV save with all rows.

        Args:
            images: List of image record dicts (unified schema).
                These dicts are MUTATED IN PLACE with analysis results.
            csv_filepath: Path for incremental CSV saving.
                If None, no CSV is written (results only in dicts).
            debug: Enable debug output.
            logger: Optional logger for file logging.

        Returns:
            Tuple of (images_analyzed_count, csv_filepath or None,
            skipped_images list).
        """
        analyzer = ImageAnalyzer(
            self.rootfs_path,
            self.pull_secret_path,
            self.internal_registry_route,
            self.openshift_token,
        )

        unique_image_names: list[str] = []
        seen: set[str] = set()
        for record in images:
            name = record.get("image_name", "")
            if name and name not in seen:
                seen.add(name)
                unique_image_names.append(name)

        total = len(unique_image_names)
        analyzed_count = 0
        skipped_images: list[str] = []
        results_cache: dict[str, ImageAnalysisResult] = {}

        for idx, image_name in enumerate(unique_image_names, 1):
            print(f"[{idx}/{total}] Analyzing: {image_name}")
            if logger:
                logger.info("[%d/%d] Analyzing image: %s", idx, total, image_name)

            try:
                result = self._analyze_with_timeout(analyzer, image_name, debug=debug)
                results_cache[image_name] = result
                analyzed_count += 1
            except _ImageTimeout:
                print(f"WARNING: Skipping image {image_name} — timed out after {self.image_timeout} seconds")
                if logger:
                    logger.warning(
                        "Skipping image %s — timed out after %d seconds",
                        image_name,
                        self.image_timeout,
                    )
                skipped_images.append(image_name)
                analyzer._cleanup(
                    analyzer._rewrite_internal_registry(image_name),
                    debug=debug,
                )
                results_cache[image_name] = ImageAnalysisResult(
                    image_name=image_name,
                    image_id="",
                    error=f"timed out after {self.image_timeout} seconds",
                )
            except Exception as exc:
                print(f"  Error analyzing image: {exc}")
                if logger:
                    logger.error("Error analyzing image %s: %s", image_name, exc)
                if debug:
                    traceback.print_exc()
                results_cache[image_name] = ImageAnalysisResult(image_name=image_name, image_id="", error=str(exc))

            self._apply_results(images, results_cache)

            if csv_filepath:
                self._save_csv(images, csv_filepath)
                row_count = len(images)
                print(f"\U0001f4be Progress saved: {row_count} rows")

        self._apply_results(images, results_cache)

        if csv_filepath:
            self._save_csv(images, csv_filepath)

        if skipped_images:
            print("\n=== Skipped images (timeout) ===")
            for name in skipped_images:
                print(name)
            print(f"Total skipped: {len(skipped_images)}")

        return analyzed_count, csv_filepath, skipped_images

    def _analyze_with_timeout(
        self,
        analyzer: ImageAnalyzer,
        image_name: str,
        debug: bool = False,
    ) -> ImageAnalysisResult:
        """Run ``analyzer.analyze_image`` with an optional SIGALRM timeout."""
        if not self.image_timeout:
            return analyzer.analyze_image(image_name, debug=debug)

        old_handler = signal.getsignal(signal.SIGALRM)

        def _alarm_handler(signum, frame):
            raise _ImageTimeout()

        try:
            signal.signal(signal.SIGALRM, _alarm_handler)
            signal.alarm(self.image_timeout)
            result = analyzer.analyze_image(image_name, debug=debug)
            signal.alarm(0)
            return result
        except _ImageTimeout:
            signal.alarm(0)
            raise
        finally:
            signal.signal(signal.SIGALRM, old_handler)

    @staticmethod
    def _apply_results(
        images: list[dict],
        results_cache: dict[str, ImageAnalysisResult],
    ) -> None:
        """Apply cached analysis results to all matching image records."""
        for record in images:
            result = results_cache.get(record.get("image_name", ""))
            if result:
                record["java_binary"] = result.java_found
                record["java_version"] = result.java_versions
                record["java_cgroup_v2_compatible"] = result.java_compatible
                record["node_binary"] = result.node_found
                record["node_version"] = result.node_versions
                record["node_cgroup_v2_compatible"] = result.node_compatible
                record["dotnet_binary"] = result.dotnet_found
                record["dotnet_version"] = result.dotnet_versions
                record["dotnet_cgroup_v2_compatible"] = result.dotnet_compatible
                record["analysis_error"] = result.error or ""
