"""
OpenShift Client Module
Handles connection to OpenShift cluster via API URL and token.
"""

import os
import re
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

from dotenv import load_dotenv, set_key
from kubernetes import client
from kubernetes.client import Configuration, ApiClient
import urllib3

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class OpenShiftClient:
    """
    Client for connecting to OpenShift clusters.
    Handles authentication via token and API URL.
    """

    def __init__(self, api_url: Optional[str] = None, token: Optional[str] = None, 
                 env_file: str = ".env", verify_ssl: bool = False):
        """
        Initialize the OpenShift client.

        Args:
            api_url: OpenShift API URL (e.g., https://api.cluster.example.com:6443)
            token: Bearer token for authentication
            env_file: Path to the .env file for storing/loading credentials
            verify_ssl: Whether to verify SSL certificates
        """
        self.env_file = Path(env_file)
        self.verify_ssl = verify_ssl
        self._api_client: Optional[ApiClient] = None
        self._cluster_name: Optional[str] = None
        
        # Load environment variables from .env file
        if self.env_file.exists():
            load_dotenv(self.env_file)
        
        # Use provided values or fall back to environment variables
        self.api_url = api_url or os.getenv("OPENSHIFT_API_URL")
        self.token = token or os.getenv("OPENSHIFT_TOKEN")

    def _extract_cluster_name(self) -> str:
        """
        Extract cluster name from API URL.
        Example: https://api.mycluster.example.com:6443 -> mycluster
        """
        if not self.api_url:
            return "unknown"
        
        try:
            parsed = urlparse(self.api_url)
            hostname = parsed.hostname or ""
            
            # Try to extract cluster name from hostname
            # Pattern: api.<clustername>.<domain>
            match = re.match(r"api\.([^.]+)\.", hostname)
            if match:
                return match.group(1)
            
            # Fallback: use first part of hostname
            parts = hostname.split(".")
            if parts and parts[0] == "api" and len(parts) > 1:
                return parts[1]
            elif parts:
                return parts[0]
            
            return "unknown"
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
                "OpenShift API URL not provided. "
                "Pass it as parameter or set OPENSHIFT_API_URL in .env file."
            )
        
        if not self.token:
            raise ValueError(
                "OpenShift token not provided. "
                "Pass it as parameter or set OPENSHIFT_TOKEN in .env file."
            )

        # Configure the client
        configuration = Configuration()
        configuration.host = self.api_url
        configuration.api_key = {"authorization": f"Bearer {self.token}"}
        configuration.verify_ssl = self.verify_ssl
        
        # Create API client
        self._api_client = ApiClient(configuration)
        
        # Test connection by getting cluster version
        try:
            version_api = client.VersionApi(self._api_client)
            version_info = version_api.get_code()
            print(f"✓ Connected to OpenShift cluster")
            print(f"  Kubernetes version: {version_info.git_version}")
            
            # Extract and store cluster name
            self._cluster_name = self._extract_cluster_name()
            print(f"  Cluster name: {self._cluster_name}")
            
            # Save credentials to .env file
            self._save_to_env()
            
            return True
            
        except Exception as e:
            self._api_client = None
            raise Exception(f"Failed to connect to OpenShift cluster: {e}")

    def _save_to_env(self) -> None:
        """Save API URL and token to .env file."""
        # Create .env file if it doesn't exist
        if not self.env_file.exists():
            self.env_file.touch()
        
        # Save credentials
        set_key(str(self.env_file), "OPENSHIFT_API_URL", self.api_url)
        set_key(str(self.env_file), "OPENSHIFT_TOKEN", self.token)
        print(f"✓ Credentials saved to {self.env_file}")

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

    def disconnect(self) -> None:
        """Disconnect from the cluster."""
        if self._api_client:
            self._api_client.close()
            self._api_client = None
            print("✓ Disconnected from OpenShift cluster")

