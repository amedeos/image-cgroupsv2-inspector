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
    username: str = "$oauthtoken",
) -> str:
    """Generate a podman-compatible auth.json from a registry token.

    The username defaults to ``$oauthtoken`` which is the convention
    Quay uses for OAuth tokens. For other registries (e.g. JFrog with
    a Bearer access token) pass the actual login username instead.

    The generated file is in the standard podman auth format. If the
    file already exists, it is overwritten.

    Args:
        registry_host: Registry hostname (e.g., "quay.example.com" or
            "acme.jfrog.io").
        token: Registry token used as the password component.
        output_path: Path to write the auth.json file.
        username: Username paired with ``token`` in the basic-auth
            credential. Defaults to ``$oauthtoken`` (Quay convention).

    Returns:
        Absolute path to the generated auth.json file.
    """
    credentials = f"{username}:{token}"
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
