"""Tests for the QuayClient module."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.quay_client import (
    QuayAPIError,
    QuayAuthenticationError,
    QuayClient,
    QuayConnectionError,
    QuayNotFoundError,
)


@pytest.fixture
def mock_session():
    """Create a mock requests.Session."""
    with patch("src.quay_client.requests.Session") as mock:
        session_instance = MagicMock()
        mock.return_value = session_instance
        yield session_instance


@pytest.fixture
def client(mock_session):
    """Create a QuayClient with mocked session."""
    return QuayClient(
        base_url="https://quay.example.com",
        token="test-token",
        verify_ssl=True,
    )


class TestQuayClientInit:
    """Test QuayClient initialization."""

    def test_session_created_with_correct_headers(self, client, mock_session):
        mock_session.headers.update.assert_called_once_with(
            {
                "Authorization": "Bearer test-token",
                "Accept": "application/json",
            }
        )

    def test_base_url_trailing_slash_stripped(self, mock_session):
        c = QuayClient(base_url="https://quay.example.com/", token="tok")
        assert c.base_url == "https://quay.example.com"

    def test_api_base_url_constructed(self, client):
        assert client.api_base == "https://quay.example.com/api/v1"

    def test_ssl_verification_propagated(self, mock_session):
        QuayClient(base_url="https://quay.example.com", token="tok", verify_ssl=True)
        assert mock_session.verify is True

    def test_ssl_verification_disabled(self, mock_session):
        with patch("src.quay_client.urllib3.disable_warnings") as mock_disable:
            QuayClient(base_url="https://quay.example.com", token="tok", verify_ssl=False)
            mock_disable.assert_called_once()
            assert mock_session.verify is False


class TestQuayClientTestConnection:
    """Test the test_connection method."""

    def test_successful_connection(self, client, mock_session):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"username": "testuser"}
        mock_session.request.return_value = response

        assert client.test_connection() is True
        mock_session.request.assert_called_once_with(
            "GET",
            "https://quay.example.com/api/v1/user/",
            timeout=30,
        )

    def test_401_raises_authentication_error(self, client, mock_session):
        response = MagicMock()
        response.status_code = 401
        response.text = "Unauthorized"
        mock_session.request.return_value = response

        with pytest.raises(QuayAuthenticationError, match=r"(?i)invalid or expired token"):
            client.test_connection()

    def test_connection_error_raises_quay_connection_error(self, client, mock_session):
        mock_session.request.side_effect = requests.ConnectionError("Connection refused")

        with pytest.raises(QuayConnectionError, match="Failed to connect"):
            client.test_connection()

    def test_timeout_raises_quay_connection_error(self, client, mock_session):
        mock_session.request.side_effect = requests.Timeout("timed out")

        with pytest.raises(QuayConnectionError, match="timed out"):
            client.test_connection()


class TestQuayClientGetOrganization:
    """Test the get_organization method."""

    def test_successful_response(self, client, mock_session):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"name": "myorg", "email": "org@example.com"}
        mock_session.request.return_value = response

        result = client.get_organization("myorg")
        assert result == {"name": "myorg", "email": "org@example.com"}
        mock_session.request.assert_called_once_with(
            "GET",
            "https://quay.example.com/api/v1/organization/myorg",
            timeout=30,
        )

    def test_404_raises_not_found_error(self, client, mock_session):
        response = MagicMock()
        response.status_code = 404
        response.text = "Not Found"
        mock_session.request.return_value = response

        with pytest.raises(QuayNotFoundError, match="not found"):
            client.get_organization("nonexistent")

    def test_401_raises_authentication_error(self, client, mock_session):
        response = MagicMock()
        response.status_code = 401
        response.text = "Unauthorized"
        mock_session.request.return_value = response

        with pytest.raises(QuayAuthenticationError):
            client.get_organization("myorg")


class TestQuayClientListRepositories:
    """Test the list_repositories method."""

    def test_single_page(self, client, mock_session):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "repositories": [
                {
                    "namespace": "myorg",
                    "name": "repo1",
                    "description": "First repo",
                    "is_public": False,
                    "kind": "image",
                    "state": "NORMAL",
                    "last_modified": 1704067200,
                }
            ],
        }
        mock_session.request.return_value = response

        repos = client.list_repositories("myorg")
        assert len(repos) == 1
        assert repos[0]["name"] == "repo1"
        assert mock_session.request.call_count == 1

    def test_multi_page_pagination(self, client, mock_session):
        page1_response = MagicMock()
        page1_response.status_code = 200
        page1_response.json.return_value = {
            "repositories": [
                {"namespace": "myorg", "name": "repo1", "state": "NORMAL"},
            ],
            "next_page": "token123",
        }
        page2_response = MagicMock()
        page2_response.status_code = 200
        page2_response.json.return_value = {
            "repositories": [
                {"namespace": "myorg", "name": "repo2", "state": "NORMAL"},
            ],
            "next_page": "token456",
        }
        page3_response = MagicMock()
        page3_response.status_code = 200
        page3_response.json.return_value = {
            "repositories": [
                {"namespace": "myorg", "name": "repo3", "state": "NORMAL"},
            ],
        }
        mock_session.request.side_effect = [page1_response, page2_response, page3_response]

        repos = client.list_repositories("myorg")
        assert len(repos) == 3
        assert [r["name"] for r in repos] == ["repo1", "repo2", "repo3"]
        assert mock_session.request.call_count == 3

    def test_empty_organization(self, client, mock_session):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"repositories": []}
        mock_session.request.return_value = response

        repos = client.list_repositories("emptyorg")
        assert repos == []

    def test_filters_non_normal_state(self, client, mock_session):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "repositories": [
                {"namespace": "myorg", "name": "good-repo", "state": "NORMAL"},
                {"namespace": "myorg", "name": "deleting-repo", "state": "MARKED_FOR_DELETION"},
                {"namespace": "myorg", "name": "another-good", "state": "NORMAL"},
            ],
        }
        mock_session.request.return_value = response

        repos = client.list_repositories("myorg")
        assert len(repos) == 2
        assert [r["name"] for r in repos] == ["good-repo", "another-good"]

    def test_401_raises_authentication_error(self, client, mock_session):
        response = MagicMock()
        response.status_code = 401
        response.text = "Unauthorized"
        mock_session.request.return_value = response

        with pytest.raises(QuayAuthenticationError):
            client.list_repositories("myorg")


class TestQuayClientListTags:
    """Test the list_tags method."""

    def test_single_page(self, client, mock_session):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "tags": [
                {
                    "name": "v1.0",
                    "manifest_digest": "sha256:abc123",
                    "size": 123456789,
                    "last_modified": "Mon, 01 Jan 2024 00:00:00 -0000",
                    "start_ts": 1704067200,
                }
            ],
            "page": 1,
            "has_additional": False,
        }
        mock_session.request.return_value = response

        tags = client.list_tags("myorg", "myrepo")
        assert len(tags) == 1
        assert tags[0]["name"] == "v1.0"
        assert mock_session.request.call_count == 1

    def test_multi_page_pagination(self, client, mock_session):
        page1_response = MagicMock()
        page1_response.status_code = 200
        page1_response.json.return_value = {
            "tags": [
                {
                    "name": "v1.0",
                    "manifest_digest": "sha256:aaa",
                    "size": 100,
                    "last_modified": "Mon, 01 Jan 2024 00:00:00 -0000",
                    "start_ts": 1704067200,
                },
                {
                    "name": "v1.1",
                    "manifest_digest": "sha256:bbb",
                    "size": 200,
                    "last_modified": "Tue, 02 Jan 2024 00:00:00 -0000",
                    "start_ts": 1704153600,
                },
            ],
            "page": 1,
            "has_additional": True,
        }
        page2_response = MagicMock()
        page2_response.status_code = 200
        page2_response.json.return_value = {
            "tags": [
                {
                    "name": "v2.0",
                    "manifest_digest": "sha256:ccc",
                    "size": 300,
                    "last_modified": "Wed, 03 Jan 2024 00:00:00 -0000",
                    "start_ts": 1704240000,
                },
            ],
            "page": 2,
            "has_additional": False,
        }
        mock_session.request.side_effect = [page1_response, page2_response]

        tags = client.list_tags("myorg", "myrepo")
        assert len(tags) == 3
        assert [t["name"] for t in tags] == ["v1.0", "v1.1", "v2.0"]
        assert mock_session.request.call_count == 2

    def test_empty_repo(self, client, mock_session):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"tags": [], "page": 1, "has_additional": False}
        mock_session.request.return_value = response

        tags = client.list_tags("myorg", "emptyrepo")
        assert tags == []

    def test_404_raises_not_found_error(self, client, mock_session):
        response = MagicMock()
        response.status_code = 404
        response.text = "Not Found"
        mock_session.request.return_value = response

        with pytest.raises(QuayNotFoundError):
            client.list_tags("myorg", "nonexistent")


class TestQuayClientRetry:
    """Test retry logic for rate limiting."""

    @patch("src.quay_client.time.sleep")
    def test_429_retries_then_succeeds(self, mock_sleep, client, mock_session):
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"username": "testuser"}

        mock_session.request.side_effect = [
            rate_limit_response,
            rate_limit_response,
            success_response,
        ]

        result = client.test_connection()
        assert result is True
        assert mock_session.request.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1)
        mock_sleep.assert_any_call(2)

    @patch("src.quay_client.time.sleep")
    def test_429_exhausts_retries(self, mock_sleep, client, mock_session):
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429

        mock_session.request.return_value = rate_limit_response

        with pytest.raises(QuayAPIError, match="Rate limit exceeded"):
            client.test_connection()
        assert mock_session.request.call_count == 4  # 1 initial + 3 retries
        assert mock_sleep.call_count == 3


class TestQuayClientErrorHandling:
    """Test error handling for various failure modes."""

    def test_500_raises_api_error(self, client, mock_session):
        response = MagicMock()
        response.status_code = 500
        response.text = "Internal Server Error"
        mock_session.request.return_value = response

        with pytest.raises(QuayAPIError, match="Server error 500"):
            client.test_connection()

    def test_connection_error_raises_quay_connection_error(self, client, mock_session):
        mock_session.request.side_effect = requests.ConnectionError("refused")

        with pytest.raises(QuayConnectionError, match="Failed to connect"):
            client.get_organization("myorg")

    def test_timeout_raises_quay_connection_error(self, client, mock_session):
        mock_session.request.side_effect = requests.Timeout("timed out")

        with pytest.raises(QuayConnectionError, match="timed out"):
            client.list_repositories("myorg")

    def test_malformed_json_raises_error(self, client, mock_session):
        response = MagicMock()
        response.status_code = 200
        response.json.side_effect = requests.exceptions.JSONDecodeError("", "", 0)
        mock_session.request.return_value = response

        with pytest.raises(requests.exceptions.JSONDecodeError):
            client.test_connection()

    def test_403_raises_authentication_error(self, client, mock_session):
        response = MagicMock()
        response.status_code = 403
        response.text = "Forbidden"
        mock_session.request.return_value = response

        with pytest.raises(QuayAuthenticationError, match="Insufficient permissions"):
            client.get_organization("myorg")
