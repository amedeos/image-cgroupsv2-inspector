"""
Quay REST API Client Module
Handles interaction with a Quay registry instance via its REST API.
"""

import logging
import time

import requests
import urllib3

logger = logging.getLogger(__name__)


class QuayClientError(Exception):
    """Base exception for QuayClient errors."""


class QuayConnectionError(QuayClientError):
    """Raised when the Quay instance is unreachable."""


class QuayAuthenticationError(QuayClientError):
    """Raised when authentication fails (401/403)."""


class QuayNotFoundError(QuayClientError):
    """Raised when the requested resource is not found (404)."""


class QuayAPIError(QuayClientError):
    """Raised for unexpected API errors (5xx, unexpected status codes)."""


class QuayClient:
    """Client for the Quay REST API.

    Provides methods to list organizations, repositories, and tags
    from a Quay registry instance (self-hosted or quay.io).

    Args:
        base_url: Quay instance URL (e.g., "https://quay.example.com").
        token: OAuth access token or robot account token.
        verify_ssl: Whether to verify SSL certificates. Defaults to True.
    """

    DEFAULT_TIMEOUT = 30
    MAX_RETRIES = 3
    RETRY_BACKOFF = 1

    def __init__(self, base_url: str, token: str, verify_ssl: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/api/v1"
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

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Send an HTTP request to the Quay API.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: API path relative to the API base (e.g., "/user/").
            **kwargs: Additional keyword arguments passed to requests.Session.request.

        Returns:
            Parsed JSON response as a dict.

        Raises:
            QuayAuthenticationError: On 401 or 403 responses.
            QuayNotFoundError: On 404 responses.
            QuayConnectionError: On connection or timeout errors.
            QuayAPIError: On 5xx or other unexpected status codes.
        """
        url = f"{self.api_base}{path}"
        kwargs.setdefault("timeout", self.DEFAULT_TIMEOUT)

        retries = 0
        while True:
            try:
                response = self.session.request(method, url, **kwargs)
            except requests.ConnectionError as exc:
                logger.error("Connection error reaching %s: %s", url, exc)
                raise QuayConnectionError(f"Failed to connect to Quay at {url}: {exc}")
            except requests.Timeout as exc:
                logger.error("Request to %s timed out: %s", url, exc)
                raise QuayConnectionError(f"Request to {url} timed out: {exc}")

            if response.status_code == 429:
                retries += 1
                if retries > self.MAX_RETRIES:
                    logger.error("Rate limit exceeded after %d retries for %s", self.MAX_RETRIES, url)
                    raise QuayAPIError(f"Rate limit exceeded after {self.MAX_RETRIES} retries for {url}")
                wait = self.RETRY_BACKOFF * (2 ** (retries - 1))
                logger.warning(
                    "Rate limited (429) on %s, retrying in %ss (attempt %d/%d)", url, wait, retries, self.MAX_RETRIES
                )
                time.sleep(wait)
                continue

            break

        if response.status_code == 401:
            logger.error("Authentication failed for %s: invalid or expired token", url)
            raise QuayAuthenticationError(f"Invalid or expired token for {url}")

        if response.status_code == 403:
            logger.error("Insufficient permissions for %s", url)
            raise QuayAuthenticationError(f"Insufficient permissions for {url}")

        if response.status_code == 404:
            logger.error("Resource not found: %s", path)
            raise QuayNotFoundError(f"Resource not found: {path}")

        if response.status_code >= 500:
            body = response.text
            logger.error("Server error %d from %s: %s", response.status_code, url, body)
            raise QuayAPIError(f"Server error {response.status_code} from {url}: {body}")

        if response.status_code >= 400:
            body = response.text
            logger.error("Unexpected error %d from %s: %s", response.status_code, url, body)
            raise QuayAPIError(f"Unexpected error {response.status_code} from {url}: {body}")

        return response.json()

    def test_connection(self) -> bool:
        """Test connectivity and authentication against the Quay API.

        Makes a request to GET /api/v1/user/ to verify the token is valid
        and the Quay instance is reachable.

        Returns:
            True if the connection and authentication are successful.

        Raises:
            QuayAuthenticationError: If the token is invalid or expired.
            QuayConnectionError: If the Quay instance is unreachable.
        """
        logger.info("Testing connection to Quay at %s", self.base_url)
        self._request("GET", "/user/")
        logger.info("Successfully connected to Quay at %s", self.base_url)
        return True

    def get_organization(self, org: str) -> dict:
        """Get organization details.

        Args:
            org: Organization name.

        Returns:
            Organization metadata dict.

        Raises:
            QuayNotFoundError: If the organization does not exist.
            QuayAuthenticationError: If not authorized.
        """
        logger.info("Fetching organization details for '%s'", org)
        return self._request("GET", f"/organization/{org}")

    def list_repositories(self, org: str) -> list[dict]:
        """List all repositories in an organization.

        Handles pagination automatically, returning all results.
        Filters out repositories not in "NORMAL" state.

        Args:
            org: Organization name.

        Returns:
            List of repository dicts with keys: namespace, name,
            description, is_public, kind, state, last_modified.
        """
        logger.info("Listing repositories for organization '%s'", org)
        all_repos: list[dict] = []
        params: dict[str, str] = {"namespace": org}
        page_num = 0

        while True:
            page_num += 1
            logger.debug("Fetching repository page %d for '%s'", page_num, org)
            data = self._request("GET", "/repository", params=params)

            for repo in data.get("repositories", []):
                state = repo.get("state", "NORMAL")
                if state != "NORMAL":
                    logger.warning(
                        "Skipping repository '%s/%s' with non-NORMAL state: %s",
                        repo.get("namespace", org),
                        repo.get("name", "unknown"),
                        state,
                    )
                    continue
                all_repos.append(repo)

            next_page = data.get("next_page")
            if not next_page:
                break
            params["next_page"] = next_page

        logger.info("Found %d repositories in organization '%s'", len(all_repos), org)
        return all_repos

    def list_tags(self, org: str, repo: str, limit: int = 100) -> list[dict]:
        """List all active tags for a repository.

        Handles pagination automatically, returning all results.
        Only returns active tags (not deleted/expired).

        Args:
            org: Organization name.
            repo: Repository name.
            limit: Number of tags per page (max 100).

        Returns:
            List of tag dicts with keys: name, manifest_digest,
            size, last_modified, start_ts.
        """
        logger.info("Listing tags for repository '%s/%s'", org, repo)
        all_tags: list[dict] = []
        page = 1

        while True:
            logger.debug("Fetching tag page %d for '%s/%s'", page, org, repo)
            params = {
                "onlyActiveTags": "true",
                "limit": str(limit),
                "page": str(page),
            }
            data = self._request("GET", f"/repository/{org}/{repo}/tag/", params=params)

            tags = data.get("tags", [])
            all_tags.extend(tags)
            logger.debug("Retrieved %d tags on page %d for '%s/%s'", len(tags), page, org, repo)

            if not data.get("has_additional", False):
                break
            page += 1

        logger.info("Found %d tags for repository '%s/%s'", len(all_tags), org, repo)
        return all_tags
