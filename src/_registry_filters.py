"""
Shared tag-filtering helpers for registry collectors.

Both Quay (RegistryCollector) and JFrog (JfrogCollector) need to apply
the same include/exclude/latest-only logic to a list of tag dicts. The
function is collector-agnostic: it works on any list of dicts that
expose a ``name`` key and (optionally) a ``start_ts`` epoch for
recency-based slicing.
"""

import fnmatch
import logging

logger = logging.getLogger(__name__)


def filter_tags(
    tags: list[dict],
    include_tags: list[str] | None = None,
    exclude_tags: list[str] | None = None,
    latest_only: int | None = None,
) -> list[dict]:
    """Filter tags by include/exclude glob patterns and recency.

    Processing order:
    1. Apply include patterns (keep only matching tags). Default: ["*"]
    2. Apply exclude patterns (remove matching tags)
    3. Sort by ``start_ts`` descending (most recent first; tags without
       a ``start_ts`` sort last)
    4. If ``latest_only`` is set, take only the first N tags

    Uses ``fnmatch.fnmatch`` for glob matching on tag names.

    Args:
        tags: List of tag dicts. Each dict must expose ``name``;
            ``start_ts`` (epoch seconds) is used for sorting when
            ``latest_only`` is set.
        include_tags: Glob patterns to include (e.g. ``["v*", "release-*"]``).
        exclude_tags: Glob patterns to exclude (e.g. ``["*-dev"]``).
        latest_only: Keep only the N most recent tags by ``start_ts``.

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
