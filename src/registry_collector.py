"""
Registry Image Collector Module
Collects container image references from a Quay registry organization,
producing image records compatible with the unified CSV schema.
"""

import csv
import fnmatch
import logging
from datetime import datetime
from pathlib import Path

from .quay_client import QuayClient, QuayClientError

logger = logging.getLogger(__name__)

CSV_COLUMNS = [
    "source",
    "container_name",
    "namespace",
    "object_type",
    "object_name",
    "registry_org",
    "registry_repo",
    "image_name",
    "image_id",
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


class RegistryCollector:
    """Collects container image references from a Quay registry.

    Uses QuayClient to enumerate repositories and tags in a Quay
    organization, producing image records compatible with the unified
    CSV schema (source="registry").

    Args:
        quay_client: An initialized QuayClient instance.
        registry_host: Registry hostname for building image references
            (e.g., "quay.example.com" or "quay.io").
    """

    def __init__(self, quay_client: QuayClient, registry_host: str) -> None:
        self.quay_client = quay_client
        self.registry_host = registry_host

    def _build_image_record(self, org: str, repo: str, tag: str) -> dict:
        """Build a single image record dict with the unified schema.

        Args:
            org: Quay organization name.
            repo: Repository name.
            tag: Tag name.

        Returns:
            Image record dict with all unified schema keys.
        """
        return {
            "source": "registry",
            "container_name": "",
            "namespace": "",
            "object_type": "",
            "object_name": "",
            "registry_org": org,
            "registry_repo": repo,
            "image_name": f"{self.registry_host}/{org}/{repo}:{tag}",
            "image_id": "",
        }

    def _filter_tags(
        self,
        tags: list[dict],
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        latest_only: int | None = None,
    ) -> list[dict]:
        """Filter tags by include/exclude glob patterns and recency.

        Processing order:
        1. Apply include patterns (keep only matching tags). Default: ["*"]
        2. Apply exclude patterns (remove matching tags)
        3. Sort by start_ts descending (most recent first)
        4. If latest_only is set, take only the first N tags

        Uses fnmatch.fnmatch for glob matching on tag names.

        Args:
            tags: List of tag dicts from QuayClient.list_tags().
            include_tags: Glob patterns to include (e.g., ["v*", "release-*"]).
            exclude_tags: Glob patterns to exclude (e.g., ["*-dev", "*-snapshot"]).
            latest_only: Keep only the N most recent tags.

        Returns:
            Filtered list of tag dicts.
        """
        include_patterns = include_tags if include_tags is not None else ["*"]
        exclude_patterns = exclude_tags or []

        filtered = []
        for tag in tags:
            name = tag.get("name", "")
            if any(fnmatch.fnmatch(name, p) for p in include_patterns):
                filtered.append(tag)

        result = []
        for tag in filtered:
            name = tag.get("name", "")
            excluded = False
            for pattern in exclude_patterns:
                if fnmatch.fnmatch(name, pattern):
                    logger.debug("Tag '%s' excluded by pattern '%s'", name, pattern)
                    excluded = True
                    break
            if not excluded:
                result.append(tag)

        result.sort(key=lambda t: t.get("start_ts", 0), reverse=True)

        if latest_only is not None:
            total = len(result)
            result = result[:latest_only]
            logger.debug(
                "Applying latest_only=%d, keeping %d of %d tags",
                latest_only,
                len(result),
                total,
            )

        return result

    def collect_images(
        self,
        org: str,
        repo: str | None = None,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        latest_only: int | None = None,
    ) -> list[dict]:
        """Collect image references from a Quay organization.

        Args:
            org: Quay organization name.
            repo: Specific repository to scan. If None, scans all repos
                in the organization.
            include_tags: Glob patterns for tags to include (default: ["*"]).
            exclude_tags: Glob patterns for tags to exclude
                (e.g., ["*-dev", "*-snapshot"]).
            latest_only: If set, only include the N most recent tags per
                repo, sorted by start_ts descending.

        Returns:
            List of image record dicts with the unified schema.
        """
        logger.info("Collecting images from organization '%s'", org)

        if repo is not None:
            repos = [{"name": repo}]
        else:
            repos = self.quay_client.list_repositories(org)

        all_images: list[dict] = []
        seen_image_names: set[str] = set()
        repos_scanned = 0

        for repo_info in repos:
            repo_name = repo_info["name"]

            try:
                tags = self.quay_client.list_tags(org, repo_name)
            except QuayClientError as exc:
                if repo is not None:
                    raise
                logger.warning(
                    "Failed to list tags for '%s/%s': %s — skipping",
                    org,
                    repo_name,
                    exc,
                )
                continue

            logger.info(
                "Scanning repository '%s/%s' (%d active tags)",
                org,
                repo_name,
                len(tags),
            )

            filtered = self._filter_tags(tags, include_tags, exclude_tags, latest_only)

            if not filtered:
                logger.warning(
                    "Repository '%s/%s' has no active tags after filtering",
                    org,
                    repo_name,
                )
                continue

            for tag in filtered:
                record = self._build_image_record(org, repo_name, tag["name"])
                image_name = record["image_name"]
                if image_name not in seen_image_names:
                    seen_image_names.add(image_name)
                    all_images.append(record)

            repos_scanned += 1

        logger.info(
            "Collected %d images from %d repositories",
            len(all_images),
            repos_scanned,
        )
        return all_images

    def save_to_csv(
        self,
        images: list[dict],
        output_dir: str = "output",
    ) -> str:
        """Save collected images to a CSV file.

        The CSV uses the unified schema columns. Only the collection-phase
        columns are populated; analysis columns are left empty (they will
        be filled by image_analyzer.py later).

        The filename format for registry mode is:
            {registry_host}-{org}-{YYYYMMDD}-{HHMMSS}.csv

        Args:
            images: List of image record dicts.
            output_dir: Output directory (default: "output").

        Returns:
            Path to the saved CSV file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        org = images[0]["registry_org"] if images else "unknown"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{self.registry_host}-{org}-{timestamp}.csv"
        filepath = output_path / filename

        with open(filepath, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for image in images:
                row = {col: image.get(col, "") for col in CSV_COLUMNS}
                writer.writerow(row)

        logger.info("Saved %d image records to %s", len(images), filepath)
        return str(filepath)
