"""
OpenShift Client Module
Handles connection to OpenShift cluster via API URL and token.
"""

import base64
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

import urllib3
from dotenv import load_dotenv, set_key
from kubernetes import client
from kubernetes.client import ApiClient, Configuration
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class OpenShiftClient:
    """
    Client for connecting to OpenShift clusters.
    Handles authentication via token and API URL.
    """

    def __init__(
        self,
        api_url: str | None = None,
        token: str | None = None,
        env_file: str = ".env",
        pull_secret_file: str = ".pull-secret",
        verify_ssl: bool = False,
    ):
        """
        Initialize the OpenShift client.

        Args:
            api_url: OpenShift API URL (e.g., https://api.cluster.example.com:6443)
            token: Bearer token for authentication
            env_file: Path to the .env file for storing/loading credentials
            pull_secret_file: Path to the file for storing the pull secret
            verify_ssl: Whether to verify SSL certificates
        """
        self.env_file = Path(env_file)
        self.pull_secret_file = Path(pull_secret_file)
        self.verify_ssl = verify_ssl
        self._api_client: ApiClient | None = None
        self._cluster_name: str | None = None

        # Load environment variables from .env file
        if self.env_file.exists():
            load_dotenv(self.env_file)

        # Use provided values or fall back to environment variables
        self.api_url = api_url or os.getenv("OPENSHIFT_API_URL")
        self.token = token or os.getenv("OPENSHIFT_TOKEN")

    def _extract_cluster_name(self) -> str:
        """
        Extract cluster name with base domain from API URL.
        Example: https://api.mycluster.example.com:6443 -> mycluster.example.com
        """
        if not self.api_url:
            return "unknown"

        try:
            parsed = urlparse(self.api_url)
            hostname = parsed.hostname or ""

            # Remove 'api.' prefix if present
            # Pattern: api.<clustername>.<basedomain> -> <clustername>.<basedomain>
            if hostname.startswith("api."):
                return hostname[4:]  # Remove 'api.' prefix

            # Fallback: return full hostname
            return hostname if hostname else "unknown"
        except Exception:
            return "unknown"

    def connect(self) -> bool:
        """
        Connect to the OpenShift cluster.

        Returns:
            True if connection successful, raises exception otherwise.

        Raises:
            ValueError: If API URL or token is not provided.
            Exception: If connection fails.
        """
        if not self.api_url:
            raise ValueError(
                "OpenShift API URL not provided. Pass it as parameter or set OPENSHIFT_API_URL in .env file."
            )

        if not self.token:
            raise ValueError("OpenShift token not provided. Pass it as parameter or set OPENSHIFT_TOKEN in .env file.")

        # Configure the client
        configuration = Configuration()
        configuration.host = self.api_url
        configuration.api_key = {"BearerToken": self.token}
        configuration.api_key_prefix = {"BearerToken": "Bearer"}
        configuration.verify_ssl = self.verify_ssl

        # Honour NO_PROXY / no_proxy env vars for the kubernetes client.
        # The kubernetes Python library uses urllib3 directly and does not
        # automatically respect the standard proxy env vars, so we read them
        # here and set them explicitly on the Configuration object.
        _no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
        _proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
            or ""
        )
        if _no_proxy:
            configuration.no_proxy = _no_proxy
        if _proxy:
            _host = urlparse(self.api_url).hostname or ""
            _bypass = any(
                _host == e.strip().lstrip(".") or _host.endswith("." + e.strip().lstrip("."))
                for e in _no_proxy.split(",")
                if e.strip()
            )
            if not _bypass:
                configuration.proxy = _proxy

        # Create API client
        self._api_client = ApiClient(configuration)

        # Test connection by getting cluster version
        try:
            version_api = client.VersionApi(self._api_client)
            version_info = version_api.get_code()
            username = self._get_authenticated_username()
            logger.debug("Connected to OpenShift cluster")
            logger.debug("Kubernetes version: %s", version_info.git_version)
            logger.debug("Authenticated OpenShift user: %s", username)
            print("✓ Connected to OpenShift cluster")
            print(f"  Kubernetes version: {version_info.git_version}")

            self._cluster_name = self._extract_cluster_name()
            logger.debug("Cluster name: %s", self._cluster_name)
            print(f"  Cluster name: {self._cluster_name}")

            self._save_to_env()
            self._download_pull_secret()

            return True

        except Exception as e:
            self._api_client = None
            raise Exception(f"Failed to connect to OpenShift cluster: {e}")

    def _get_authenticated_username(self) -> str:
        """Return the current authenticated OpenShift username."""
        try:
            user = self.get_custom_objects_api().get_cluster_custom_object(
                group="user.openshift.io",
                version="v1",
                plural="users",
                name="~",
            )
        except ApiException as e:
            if e.status in (401, 403):
                raise RuntimeError(
                    f"token was not accepted for authenticated OpenShift API access ({e.status} {e.reason})"
                ) from e
            raise

        username = user.get("metadata", {}).get("name", "")
        if not username:
            raise RuntimeError("authenticated OpenShift user lookup returned no metadata.name")
        return username

    def _save_to_env(self) -> None:
        """Save API URL and token to .env file."""
        # Create .env file if it doesn't exist
        if not self.env_file.exists():
            self.env_file.touch()

        # Save credentials
        set_key(str(self.env_file), "OPENSHIFT_API_URL", self.api_url)
        set_key(str(self.env_file), "OPENSHIFT_TOKEN", self.token)
        logger.debug("Credentials saved to %s", self.env_file)
        print(f"✓ Credentials saved to {self.env_file}")

    def _download_pull_secret(self) -> bool:
        """
        Download the cluster pull-secret from openshift-config namespace
        and save it to the pull-secret file.

        If the pull-secret file already exists, the download is skipped
        to avoid overwriting a user-provided pull-secret.

        Returns:
            True if successful, False otherwise.
        """
        if self.pull_secret_file.exists():
            logger.debug("Pull secret already exists at %s, skipping download", self.pull_secret_file)
            print(f"✓ Pull secret already exists at {self.pull_secret_file}, skipping download")
            return True

        try:
            core_v1 = self.get_core_v1_api()

            # Get the pull-secret from openshift-config namespace
            secret = core_v1.read_namespaced_secret(name="pull-secret", namespace="openshift-config")

            # Extract the .dockerconfigjson data
            if secret.data and ".dockerconfigjson" in secret.data:
                # Decode from base64
                pull_secret_b64 = secret.data[".dockerconfigjson"]
                pull_secret_json = base64.b64decode(pull_secret_b64).decode("utf-8")

                # Pretty print the JSON
                pull_secret_data = json.loads(pull_secret_json)
                pull_secret_formatted = json.dumps(pull_secret_data, indent=2)

                # Save to file
                self.pull_secret_file.write_text(pull_secret_formatted)

                # Set restrictive permissions (readable only by owner)
                os.chmod(self.pull_secret_file, 0o600)

                logger.debug("Pull secret saved to %s", self.pull_secret_file)
                print(f"✓ Pull secret saved to {self.pull_secret_file}")
                return True
            else:
                logger.debug("Pull secret found but no .dockerconfigjson data")
                print("⚠ Pull secret found but no .dockerconfigjson data")
                return False

        except ApiException as e:
            if e.status == 403:
                logger.debug("No permission to read pull-secret (requires cluster-admin)")
                print("⚠ No permission to read pull-secret (requires cluster-admin)")
            elif e.status == 404:
                logger.debug("Pull secret not found in openshift-config namespace")
                print("⚠ Pull secret not found in openshift-config namespace")
            else:
                logger.debug("Failed to download pull-secret: %s", e.reason)
                print(f"⚠ Failed to download pull-secret: {e.reason}")
            return False
        except Exception as e:
            logger.debug("Error downloading pull-secret: %s", e)
            print(f"⚠ Error downloading pull-secret: {e}")
            return False

    @property
    def api_client(self) -> ApiClient:
        """Get the Kubernetes API client."""
        if not self._api_client:
            raise RuntimeError("Not connected to OpenShift. Call connect() first.")
        return self._api_client

    @property
    def cluster_name(self) -> str:
        """Get the cluster name."""
        if not self._cluster_name:
            self._cluster_name = self._extract_cluster_name()
        return self._cluster_name

    def get_core_v1_api(self) -> client.CoreV1Api:
        """Get CoreV1Api instance."""
        return client.CoreV1Api(self.api_client)

    def get_apps_v1_api(self) -> client.AppsV1Api:
        """Get AppsV1Api instance."""
        return client.AppsV1Api(self.api_client)

    def get_batch_v1_api(self) -> client.BatchV1Api:
        """Get BatchV1Api instance."""
        return client.BatchV1Api(self.api_client)

    def get_custom_objects_api(self) -> client.CustomObjectsApi:
        """Get CustomObjectsApi instance (for OpenShift resources like DeploymentConfig)."""
        return client.CustomObjectsApi(self.api_client)

    def get_internal_registry_route(self) -> str | None:
        """
        Get the default route hostname for the OpenShift internal image registry.

        Queries the route.openshift.io API for the 'default-route' in the
        openshift-image-registry namespace.

        Returns:
            The route hostname (e.g., 'default-route-openshift-image-registry.apps.example.com')
            or None if not available.
        """
        try:
            custom_api = self.get_custom_objects_api()
            route = custom_api.get_namespaced_custom_object(
                group="route.openshift.io",
                version="v1",
                namespace="openshift-image-registry",
                plural="routes",
                name="default-route",
            )
            host = route.get("spec", {}).get("host", "")
            if host:
                logger.debug("Internal registry route: %s", host)
                print(f"✓ Internal registry route: {host}")
                return host
        except ApiException as e:
            if e.status == 404:
                logger.debug("Internal registry default-route not found (not exposed)")
                print("⚠ Internal registry default-route not found (not exposed)")
            elif e.status == 403:
                logger.debug("No permission to read internal registry route")
                print("⚠ No permission to read internal registry route")
            else:
                logger.debug("Error querying internal registry route: %s", e.reason)
                print(f"⚠ Error querying internal registry route: {e.reason}")
        except Exception as e:
            logger.debug("Error querying internal registry route: %s", e)
            print(f"⚠ Error querying internal registry route: {e}")
        return None

    def disconnect(self) -> None:
        """Disconnect from the cluster."""
        if self._api_client:
            self._api_client.close()
            self._api_client = None
            logger.debug("Disconnected from OpenShift cluster")
            print("✓ Disconnected from OpenShift cluster")
