"""
JFrog Artifactory REST API Client Module
Handles interaction with a JFrog Container Registry instance.
"""

import logging
import time
from datetime import datetime

import requests
import urllib3

logger = logging.getLogger(__name__)


class JfrogClientError(Exception):
    """Base exception for JfrogClient errors."""


class JfrogConnectionError(JfrogClientError):
    """Raised when the JFrog instance is unreachable."""


class JfrogAuthenticationError(JfrogClientError):
    """Raised when authentication fails (401/403)."""


class JfrogNotFoundError(JfrogClientError):
    """Raised when the requested resource is not found (404)."""


class JfrogAPIError(JfrogClientError):
    """Raised for unexpected API errors (5xx, unexpected status codes)."""


class JfrogClient:
    """Client for the JFrog Artifactory REST API.

    Wraps the subset of endpoints needed to enumerate Docker images in
    a JFrog Container Registry repository: connectivity check,
    repository listing, Docker Registry v2 catalog/tags, and storage
    metadata.

    Authentication is via Bearer access token
    (``Authorization: Bearer <token>``). The Pro-only per-repo
    configuration endpoint ``/api/repositories/{repoKey}`` is
    deliberately avoided because it returns HTTP 400 on Artifactory
    Community Edition.

    Args:
        base_url: JFrog base URL (e.g. ``https://acme.jfrog.io`` or
            ``http://artifactory.lab.example.com:8082``).
        token: JFrog Bearer access token.
        verify_ssl: Whether to verify TLS certificates. Defaults to True.
    """

    DEFAULT_TIMEOUT = 30
    MAX_RETRIES = 3
    RETRY_BACKOFF = 1

    def __init__(self, base_url: str, token: str, verify_ssl: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/artifactory"
        self.verify_ssl = verify_ssl

        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
        )
        self.session.verify = verify_ssl

    def _request(self, method: str, path: str, *, parse_json: bool = True, **kwargs):
        """Send an HTTP request to the JFrog API.

        Retries on 429 with exponential backoff. Maps standard HTTP
        statuses to JfrogClient* exceptions.

        Args:
            method: HTTP method.
            path: API path relative to ``/artifactory``
                (e.g. ``/api/system/ping``).
            parse_json: When True (default), return ``response.json()``;
                when False, return ``response.text`` (e.g. for
                ``/api/system/ping`` which replies with plain text).
            **kwargs: Forwarded to ``requests.Session.request``.

        Returns:
            Parsed JSON value, or response text when ``parse_json=False``.
        """
        url = f"{self.api_base}{path}"
        kwargs.setdefault("timeout", self.DEFAULT_TIMEOUT)

        retries = 0
        while True:
            try:
                response = self.session.request(method, url, **kwargs)
            except requests.ConnectionError as exc:
                logger.error("Connection error reaching %s: %s", url, exc)
                raise JfrogConnectionError(f"Failed to connect to JFrog at {url}: {exc}")
            except requests.Timeout as exc:
                logger.error("Request to %s timed out: %s", url, exc)
                raise JfrogConnectionError(f"Request to {url} timed out: {exc}")

            if response.status_code == 429:
                retries += 1
                if retries > self.MAX_RETRIES:
                    raise JfrogAPIError(f"Rate limit exceeded after {self.MAX_RETRIES} retries for {url}")
                wait = self.RETRY_BACKOFF * (2 ** (retries - 1))
                logger.warning(
                    "Rate limited (429) on %s, retrying in %ss (attempt %d/%d)",
                    url,
                    wait,
                    retries,
                    self.MAX_RETRIES,
                )
                time.sleep(wait)
                continue

            break

        if response.status_code in (401, 403):
            raise JfrogAuthenticationError(f"Authentication failed for {url} (HTTP {response.status_code})")

        if response.status_code == 404:
            raise JfrogNotFoundError(f"Resource not found: {path}")

        if response.status_code >= 400:
            body = response.text
            logger.error("Unexpected error %d from %s: %s", response.status_code, url, body)
            raise JfrogAPIError(f"Unexpected error {response.status_code} from {url}: {body}")

        if parse_json:
            return response.json()
        return response.text

    def test_connection(self) -> bool:
        """Verify reachability and authentication via system/ping.

        ``GET /artifactory/api/system/ping`` returns the literal string
        ``OK`` on success and is available in Artifactory Community
        Edition. The endpoint replies with ``text/plain``, so we
        override the session's default ``Accept: application/json``
        header to avoid an HTTP 406 from JFrog.
        """
        logger.info("Testing connection to JFrog at %s", self.base_url)
        body = self._request(
            "GET",
            "/api/system/ping",
            parse_json=False,
            headers={"Accept": "text/plain"},
        )
        if "OK" not in body:
            raise JfrogAPIError(f"Unexpected ping response: {body!r}")
        logger.info("Successfully connected to JFrog at %s", self.base_url)
        return True

    def list_repositories(self, repo_type: str = "local") -> list[dict]:
        """List configured repositories of a given type.

        Uses ``GET /artifactory/api/repositories?type={type}`` which is
        available on Artifactory Community Edition.

        Args:
            repo_type: Filter (``local``, ``remote``, ``virtual``,
                ``federated``). Defaults to ``local``.

        Returns:
            List of dicts with keys: ``key``, ``type``, ``url``,
            ``packageType``.
        """
        logger.info("Listing %s repositories", repo_type)
        return self._request("GET", "/api/repositories", params={"type": repo_type})

    def check_repository(self, repo: str, repo_type: str = "local") -> dict:
        """Verify a repository exists, returning its metadata dict.

        Equivalent in spirit to ``QuayClient.get_organization`` but
        implemented on top of the CE-friendly list endpoint.

        Args:
            repo: JFrog repository key (e.g. ``docker-local``).
            repo_type: Type filter passed to list_repositories.

        Raises:
            JfrogNotFoundError: If no repository with the given key
                exists in the listed set.
        """
        repos = self.list_repositories(repo_type=repo_type)
        for entry in repos:
            if entry.get("key") == repo:
                return entry
        raise JfrogNotFoundError(f"Repository '{repo}' not found among {repo_type} repositories")

    def list_images(self, repo: str) -> list[str]:
        """List Docker images (repositories) inside a JFrog repo.

        Uses the Docker Registry v2 catalog endpoint:
        ``GET /artifactory/api/docker/{repo}/v2/_catalog``.

        Args:
            repo: JFrog repository key.

        Returns:
            Sorted, de-duplicated list of image name strings.
        """
        logger.info("Listing Docker images in '%s'", repo)
        all_images: list[str] = []
        page_size = 100
        params: dict[str, str] = {"n": str(page_size)}
        page = 0

        while True:
            page += 1
            data = self._request(
                "GET",
                f"/api/docker/{repo}/v2/_catalog",
                params=params,
            )
            batch = data.get("repositories") or []
            all_images.extend(batch)
            logger.debug(
                "Catalog page %d for '%s': %d images",
                page,
                repo,
                len(batch),
            )
            if not batch or len(batch) < page_size:
                break
            params["last"] = batch[-1]

        deduped = sorted(set(all_images))
        logger.info("Found %d Docker images in '%s'", len(deduped), repo)
        return deduped

    def list_tags(
        self,
        repo: str,
        image: str,
        *,
        fetch_timestamps: bool = True,
    ) -> list[dict]:
        """List tags for a Docker image inside a JFrog repo.

        Uses ``GET /artifactory/api/docker/{repo}/v2/{image}/tags/list``
        for tag names. When ``fetch_timestamps`` is True the result is
        enriched with one ``GET /artifactory/api/storage/{repo}/{image}/{tag}``
        per tag, recording ``lastModified`` (ISO 8601) and a derived
        epoch-seconds ``start_ts`` so the dicts match the shape that
        ``_registry_filters.filter_tags`` consumes for sorting.

        Args:
            repo: JFrog repository key.
            image: Docker image name (e.g. ``java-compatible``).
            fetch_timestamps: When True (default), enrich each entry
                with ``last_modified`` + ``start_ts``. False skips the
                per-tag storage call; ``latest_only`` will then be
                unstable since all tags share ``start_ts == 0``.

        Returns:
            List of dicts: ``{"name": str, "last_modified": str|None,
            "start_ts": int}``.
        """
        logger.info("Listing tags for '%s/%s'", repo, image)
        data = self._request("GET", f"/api/docker/{repo}/v2/{image}/tags/list")
        tag_names: list[str] = data.get("tags") or []

        result: list[dict] = []
        for name in tag_names:
            entry: dict = {"name": name, "last_modified": None, "start_ts": 0}
            if fetch_timestamps:
                try:
                    info = self._request(
                        "GET",
                        f"/api/storage/{repo}/{image}/{name}",
                    )
                    last_modified = info.get("lastModified")
                    if last_modified:
                        entry["last_modified"] = last_modified
                        entry["start_ts"] = _iso8601_to_epoch(last_modified)
                except JfrogClientError as exc:
                    logger.warning(
                        "Failed to fetch storage info for '%s/%s:%s' (%s); tag will lack a timestamp",
                        repo,
                        image,
                        name,
                        exc,
                    )
            result.append(entry)

        logger.info("Found %d tags for '%s/%s'", len(result), repo, image)
        return result


def _iso8601_to_epoch(iso: str) -> int:
    """Convert a JFrog-style ISO 8601 timestamp to epoch seconds.

    JFrog returns values such as ``2026-05-07T19:29:19.323+02:00``.
    Returns 0 if the value cannot be parsed.
    """
    try:
        return int(datetime.fromisoformat(iso).timestamp())
    except (ValueError, TypeError):
        logger.debug("Could not parse JFrog timestamp %r", iso)
        return 0
