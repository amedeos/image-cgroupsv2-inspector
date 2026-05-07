"""
JFrog Image Collector Module
Collects container image references from a JFrog Container Registry,
producing image records compatible with the unified CSV schema.
"""

import csv
import logging
from datetime import datetime
from pathlib import Path

from ._registry_filters import filter_tags
from .jfrog_client import JfrogClient, JfrogClientError
from .registry_collector import CSV_COLUMNS

logger = logging.getLogger(__name__)


class JfrogCollector:
    """Collects container image references from a JFrog repository.

    Uses :class:`JfrogClient` to enumerate Docker images and tags
    inside a JFrog Artifactory Docker repository, producing image
    records compatible with the unified CSV schema (``source="jfrog"``).

    Mapping to the unified schema:

    * ``registry_org`` ← JFrog repository key (e.g. ``docker-local``)
    * ``registry_repo`` ← Docker image name (e.g. ``java-compatible``)
    * ``image_name`` ← ``{registry_host}/{repo}/{image}:{tag}``

    Args:
        jfrog_client: An initialised :class:`JfrogClient`.
        registry_host: Host (and optional port) used when building
            ``image_name``, e.g. ``acme.jfrog.io`` or
            ``artifactory.lab.example.com:8082``.
    """

    def __init__(self, jfrog_client: JfrogClient, registry_host: str) -> None:
        self.jfrog_client = jfrog_client
        self.registry_host = registry_host

    def _build_image_record(self, repo: str, image: str, tag: str) -> dict:
        """Build a single image record dict with the unified schema."""
        return {
            "source": "jfrog",
            "container_name": "",
            "namespace": "",
            "object_type": "",
            "object_name": "",
            "registry_org": repo,
            "registry_repo": image,
            "image_name": f"{self.registry_host}/{repo}/{image}:{tag}",
            "image_id": "",
        }

    def collect_images(
        self,
        repo: str,
        image: str | None = None,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        latest_only: int | None = None,
    ) -> list[dict]:
        """Collect image references from a JFrog Docker repository.

        Args:
            repo: JFrog repository key (e.g. ``docker-local``).
            image: Specific Docker image to scan. If None, scans every
                image returned by the Docker v2 catalog of ``repo``.
            include_tags: Glob patterns for tags to include
                (default: ``["*"]``).
            exclude_tags: Glob patterns for tags to exclude.
            latest_only: If set, keep only the N most recent tags per
                image (sorted by ``start_ts`` from the storage API).

        Returns:
            List of image record dicts with the unified schema.
        """
        logger.info("Collecting images from JFrog repository '%s'", repo)

        if image is not None:
            images = [image]
        else:
            images = self.jfrog_client.list_images(repo)

        all_records: list[dict] = []
        seen_image_names: set[str] = set()
        images_scanned = 0

        for image_name in images:
            try:
                tags = self.jfrog_client.list_tags(repo, image_name)
            except JfrogClientError as exc:
                if image is not None:
                    raise
                logger.warning(
                    "Failed to list tags for '%s/%s': %s — skipping",
                    repo,
                    image_name,
                    exc,
                )
                continue

            logger.info(
                "Scanning image '%s/%s' (%d tags)",
                repo,
                image_name,
                len(tags),
            )

            filtered = filter_tags(tags, include_tags, exclude_tags, latest_only)

            if not filtered:
                logger.warning(
                    "Image '%s/%s' has no tags after filtering",
                    repo,
                    image_name,
                )
                continue

            for tag in filtered:
                record = self._build_image_record(repo, image_name, tag["name"])
                if record["image_name"] not in seen_image_names:
                    seen_image_names.add(record["image_name"])
                    all_records.append(record)

            images_scanned += 1

        logger.info(
            "Collected %d images from %d Docker images in '%s'",
            len(all_records),
            images_scanned,
            repo,
        )
        return all_records

    def save_to_csv(
        self,
        images: list[dict],
        output_dir: str = "output",
    ) -> str:
        """Save collected image records to a CSV file.

        Filename format: ``{registry_host}-{repo}-{YYYYMMDD}-{HHMMSS}.csv``.
        Only the collection-phase columns are populated; analysis
        columns are filled later by ``image_analyzer``.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        repo = images[0]["registry_org"] if images else "unknown"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{self.registry_host}-{repo}-{timestamp}.csv"
        filepath = output_path / filename

        with open(filepath, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for image in images:
                row = {col: image.get(col, "") for col in CSV_COLUMNS}
                writer.writerow(row)

        logger.info("Saved %d image records to %s", len(images), filepath)
        return str(filepath)
