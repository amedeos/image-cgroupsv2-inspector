"""
OpenShift Client Module
Handles connection to OpenShift cluster via API URL and token.
"""

import base64
import json
import os
import re
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

from dotenv import load_dotenv, set_key
from kubernetes import client
from kubernetes.client import Configuration, ApiClient
from kubernetes.client.rest import ApiException
import urllib3

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class OpenShiftClient:
    """
    Client for connecting to OpenShift clusters.
    Handles authentication via token and API URL.
    """

    def __init__(self, api_url: Optional[str] = None, token: Optional[str] = None, 
                 env_file: str = ".env", pull_secret_file: str = ".pull-secret",
                 verify_ssl: bool = False):
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
            
            # Download and save pull-secret
            self._download_pull_secret()
            
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

    def _download_pull_secret(self) -> bool:
        """
        Download the cluster pull-secret from openshift-config namespace
        and save it to the pull-secret file.

        Returns:
            True if successful, False otherwise.
        """
        try:
            core_v1 = self.get_core_v1_api()
            
            # Get the pull-secret from openshift-config namespace
            secret = core_v1.read_namespaced_secret(
                name="pull-secret",
                namespace="openshift-config"
            )
            
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
                
                print(f"✓ Pull secret saved to {self.pull_secret_file}")
                return True
            else:
                print(f"⚠ Pull secret found but no .dockerconfigjson data")
                return False
                
        except ApiException as e:
            if e.status == 403:
                print(f"⚠ No permission to read pull-secret (requires cluster-admin)")
            elif e.status == 404:
                print(f"⚠ Pull secret not found in openshift-config namespace")
            else:
                print(f"⚠ Failed to download pull-secret: {e.reason}")
            return False
        except Exception as e:
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

    def disconnect(self) -> None:
        """Disconnect from the cluster."""
        if self._api_client:
            self._api_client.close()
            self._api_client = None
            print("✓ Disconnected from OpenShift cluster")

