"""Tests for the auth_utils module."""

import base64
import json

from src.auth_utils import generate_registry_auth_json

# ---------------------------------------------------------------------------
# TestGenerateRegistryAuthJson
# ---------------------------------------------------------------------------


class TestGenerateRegistryAuthJson:
    """Test generate_registry_auth_json."""

    def test_generates_valid_json(self, tmp_path):
        output = tmp_path / "auth.json"
        generate_registry_auth_json("quay.example.com", "mytoken", str(output))

        data = json.loads(output.read_text())
        assert "auths" in data
        assert "quay.example.com" in data["auths"]

    def test_auth_is_base64_oauthtoken(self, tmp_path):
        output = tmp_path / "auth.json"
        generate_registry_auth_json("quay.example.com", "secret123", str(output))

        data = json.loads(output.read_text())
        encoded = data["auths"]["quay.example.com"]["auth"]
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "$oauthtoken:secret123"

    def test_registry_host_used_as_key(self, tmp_path):
        output = tmp_path / "auth.json"
        generate_registry_auth_json("my-registry.io", "tok", str(output))

        data = json.loads(output.read_text())
        assert "my-registry.io" in data["auths"]

    def test_file_created_at_output_path(self, tmp_path):
        output = tmp_path / "custom-auth.json"
        generate_registry_auth_json("quay.io", "tok", str(output))
        assert output.exists()

    def test_returns_absolute_path(self, tmp_path):
        output = tmp_path / "auth.json"
        result = generate_registry_auth_json("quay.io", "tok", str(output))
        assert result == str(output.resolve())

    def test_overwrites_existing_file(self, tmp_path):
        output = tmp_path / "auth.json"
        output.write_text("old content")

        generate_registry_auth_json("quay.io", "newtok", str(output))

        data = json.loads(output.read_text())
        decoded = base64.b64decode(data["auths"]["quay.io"]["auth"]).decode()
        assert decoded == "$oauthtoken:newtok"

    def test_json_structure(self, tmp_path):
        output = tmp_path / "auth.json"
        generate_registry_auth_json("quay.example.com", "tok", str(output))

        data = json.loads(output.read_text())
        assert isinstance(data, dict)
        assert isinstance(data["auths"], dict)
        assert isinstance(data["auths"]["quay.example.com"], dict)
        assert "auth" in data["auths"]["quay.example.com"]
