"""
Authentication Utilities Module

Provides helper functions for generating container registry
authentication files compatible with podman.
"""

import base64
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_registry_auth_json(
    registry_host: str,
    token: str,
    output_path: str = ".pull-secret-registry",
) -> str:
    """Generate a podman-compatible auth.json from a Quay token.

    For OAuth tokens, uses "$oauthtoken" as the username.
    The generated file is in the standard podman auth format.

    If the file already exists, it is overwritten.

    Args:
        registry_host: Registry hostname (e.g., "quay.example.com").
        token: Quay OAuth token or robot account token.
        output_path: Path to write the auth.json file.

    Returns:
        Absolute path to the generated auth.json file.
    """
    credentials = f"$oauthtoken:{token}"
    encoded = base64.b64encode(credentials.encode()).decode()

    auth_data = {
        "auths": {
            registry_host: {
                "auth": encoded,
            }
        }
    }

    path = Path(output_path)
    path.write_text(json.dumps(auth_data, indent=2))

    logger.info("Generated registry auth file: %s", path.resolve())
    return str(path.resolve())
