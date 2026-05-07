"""Tests for the JfrogClient module."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.jfrog_client import (
    JfrogAPIError,
    JfrogAuthenticationError,
    JfrogClient,
    JfrogConnectionError,
    JfrogNotFoundError,
    _iso8601_to_epoch,
)


@pytest.fixture
def mock_session():
    """Create a mock requests.Session attached to JfrogClient."""
    with patch("src.jfrog_client.requests.Session") as mock:
        session_instance = MagicMock()
        mock.return_value = session_instance
        yield session_instance


@pytest.fixture
def client(mock_session):
    """Create a JfrogClient with a mocked session."""
    return JfrogClient(
        base_url="https://artifactory.example.com",
        token="test-token",
        verify_ssl=True,
    )


def _response(status_code: int, *, json_payload=None, text: str = "") -> MagicMock:
    """Build a MagicMock that mimics requests.Response."""
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    if json_payload is not None:
        response.json.return_value = json_payload
    return response


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestJfrogClientInit:
    def test_session_headers_use_bearer_and_json_accept(self, client, mock_session):
        mock_session.headers.update.assert_called_once_with(
            {
                "Authorization": "Bearer test-token",
                "Accept": "application/json",
            }
        )

    def test_base_url_trailing_slash_stripped(self, mock_session):
        c = JfrogClient(base_url="https://artifactory.example.com/", token="t")
        assert c.base_url == "https://artifactory.example.com"

    def test_api_base_includes_artifactory_prefix(self, client):
        assert client.api_base == "https://artifactory.example.com/artifactory"

    def test_ssl_verification_disabled_disables_warnings(self, mock_session):
        with patch("src.jfrog_client.urllib3.disable_warnings") as mock_disable:
            JfrogClient(base_url="https://x", token="t", verify_ssl=False)
            mock_disable.assert_called_once()
            assert mock_session.verify is False


# ---------------------------------------------------------------------------
# _request
# ---------------------------------------------------------------------------


class TestJfrogClientRequest:
    def test_happy_path_returns_json(self, client, mock_session):
        mock_session.request.return_value = _response(200, json_payload={"ok": True})
        assert client._request("GET", "/api/foo") == {"ok": True}
        mock_session.request.assert_called_once_with(
            "GET",
            "https://artifactory.example.com/artifactory/api/foo",
            timeout=30,
        )

    def test_parse_json_false_returns_text(self, client, mock_session):
        mock_session.request.return_value = _response(200, text="OK")
        assert client._request("GET", "/api/system/ping", parse_json=False) == "OK"

    def test_401_raises_authentication_error(self, client, mock_session):
        mock_session.request.return_value = _response(401, text="unauth")
        with pytest.raises(JfrogAuthenticationError):
            client._request("GET", "/api/foo")

    def test_403_raises_authentication_error(self, client, mock_session):
        mock_session.request.return_value = _response(403, text="forbidden")
        with pytest.raises(JfrogAuthenticationError):
            client._request("GET", "/api/foo")

    def test_404_raises_not_found(self, client, mock_session):
        mock_session.request.return_value = _response(404, text="missing")
        with pytest.raises(JfrogNotFoundError):
            client._request("GET", "/api/foo")

    def test_500_raises_api_error(self, client, mock_session):
        mock_session.request.return_value = _response(500, text="boom")
        with pytest.raises(JfrogAPIError):
            client._request("GET", "/api/foo")

    def test_other_4xx_raises_api_error_with_body(self, client, mock_session):
        mock_session.request.return_value = _response(406, text="Not Acceptable")
        with pytest.raises(JfrogAPIError, match="Not Acceptable"):
            client._request("GET", "/api/foo")

    def test_connection_error_wrapped(self, client, mock_session):
        mock_session.request.side_effect = requests.ConnectionError("dns")
        with pytest.raises(JfrogConnectionError):
            client._request("GET", "/api/foo")

    def test_timeout_wrapped(self, client, mock_session):
        mock_session.request.side_effect = requests.Timeout("slow")
        with pytest.raises(JfrogConnectionError):
            client._request("GET", "/api/foo")

    def test_429_retries_then_succeeds(self, client, mock_session):
        with patch("src.jfrog_client.time.sleep") as mock_sleep:
            mock_session.request.side_effect = [
                _response(429, text="rate"),
                _response(200, json_payload={"v": 1}),
            ]
            assert client._request("GET", "/api/foo") == {"v": 1}
            assert mock_session.request.call_count == 2
            mock_sleep.assert_called_once()

    def test_429_exhausts_retries(self, client, mock_session):
        with patch("src.jfrog_client.time.sleep"):
            mock_session.request.return_value = _response(429, text="rate")
            with pytest.raises(JfrogAPIError, match="Rate limit"):
                client._request("GET", "/api/foo")


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


class TestJfrogClientTestConnection:
    def test_ping_ok_returns_true(self, client, mock_session):
        mock_session.request.return_value = _response(200, text="OK")
        assert client.test_connection() is True

    def test_ping_overrides_accept_header(self, client, mock_session):
        mock_session.request.return_value = _response(200, text="OK")
        client.test_connection()
        # Confirm we passed an Accept override (otherwise JFrog returns 406).
        call_kwargs = mock_session.request.call_args.kwargs
        assert call_kwargs["headers"] == {"Accept": "text/plain"}

    def test_ping_unexpected_body_raises(self, client, mock_session):
        mock_session.request.return_value = _response(200, text="not-ok")
        with pytest.raises(JfrogAPIError, match="Unexpected ping response"):
            client.test_connection()


# ---------------------------------------------------------------------------
# list_repositories / check_repository
# ---------------------------------------------------------------------------


_REPO_LIST = [
    {"key": "docker-local", "type": "LOCAL", "packageType": "Docker"},
    {"key": "docker-snapshots", "type": "LOCAL", "packageType": "Docker"},
]


class TestJfrogClientRepositories:
    def test_list_repositories_local(self, client, mock_session):
        mock_session.request.return_value = _response(200, json_payload=_REPO_LIST)
        result = client.list_repositories(repo_type="local")
        assert result == _REPO_LIST
        call_kwargs = mock_session.request.call_args.kwargs
        assert call_kwargs["params"] == {"type": "local"}

    def test_check_repository_found(self, client, mock_session):
        mock_session.request.return_value = _response(200, json_payload=_REPO_LIST)
        match = client.check_repository("docker-local")
        assert match["key"] == "docker-local"

    def test_check_repository_not_found_raises(self, client, mock_session):
        mock_session.request.return_value = _response(200, json_payload=_REPO_LIST)
        with pytest.raises(JfrogNotFoundError, match="docker-virtual"):
            client.check_repository("docker-virtual")


# ---------------------------------------------------------------------------
# list_images (Docker v2 catalog)
# ---------------------------------------------------------------------------


class TestJfrogClientListImages:
    def test_single_page_catalog(self, client, mock_session):
        mock_session.request.return_value = _response(
            200,
            json_payload={"repositories": ["alpha", "beta", "alpha"]},
        )
        result = client.list_images("docker-local")
        # Sorted + deduped.
        assert result == ["alpha", "beta"]

    def test_paginated_catalog(self, client, mock_session):
        # First page hits page_size=100 ⇒ continues; second page returns less ⇒ stops.
        first_page = {"repositories": [f"img-{i}" for i in range(100)]}
        second_page = {"repositories": ["img-100", "img-101"]}
        mock_session.request.side_effect = [
            _response(200, json_payload=first_page),
            _response(200, json_payload=second_page),
        ]
        result = client.list_images("docker-local")
        assert len(result) == 102
        assert "img-99" in result and "img-101" in result
        # Second call should include `last` cursor.
        second_call_kwargs = mock_session.request.call_args_list[1].kwargs
        assert second_call_kwargs["params"]["last"] == "img-99"


# ---------------------------------------------------------------------------
# list_tags (Docker v2 + storage info)
# ---------------------------------------------------------------------------


class TestJfrogClientListTags:
    def test_list_tags_with_timestamps(self, client, mock_session):
        # 1) tags/list, 2) storage info per tag.
        mock_session.request.side_effect = [
            _response(200, json_payload={"tags": ["v1", "v2"]}),
            _response(
                200,
                json_payload={"lastModified": "2026-05-07T12:00:00.000+02:00"},
            ),
            _response(
                200,
                json_payload={"lastModified": "2026-05-07T13:00:00.000+02:00"},
            ),
        ]
        result = client.list_tags("docker-local", "java-compatible")
        assert [t["name"] for t in result] == ["v1", "v2"]
        assert result[0]["last_modified"] == "2026-05-07T12:00:00.000+02:00"
        assert result[0]["start_ts"] > 0
        assert result[1]["start_ts"] > result[0]["start_ts"]

    def test_list_tags_skip_timestamps(self, client, mock_session):
        mock_session.request.return_value = _response(200, json_payload={"tags": ["v1", "v2"]})
        result = client.list_tags("docker-local", "java-compatible", fetch_timestamps=False)
        assert [t["name"] for t in result] == ["v1", "v2"]
        assert all(t["start_ts"] == 0 for t in result)
        # Only the tags/list call was made.
        assert mock_session.request.call_count == 1

    def test_list_tags_storage_failure_keeps_tag_without_timestamp(self, client, mock_session):
        mock_session.request.side_effect = [
            _response(200, json_payload={"tags": ["v1"]}),
            _response(500, text="boom"),
        ]
        result = client.list_tags("docker-local", "java-compatible")
        assert result == [{"name": "v1", "last_modified": None, "start_ts": 0}]


# ---------------------------------------------------------------------------
# _iso8601_to_epoch
# ---------------------------------------------------------------------------


class TestIso8601ToEpoch:
    def test_round_trip_with_offset(self):
        assert _iso8601_to_epoch("2026-05-07T19:29:19.323+02:00") > 0

    def test_round_trip_utc(self):
        assert _iso8601_to_epoch("2026-05-07T17:29:19.000+00:00") > 0

    def test_unparseable_returns_zero(self):
        assert _iso8601_to_epoch("not a date") == 0

    def test_none_returns_zero(self):
        assert _iso8601_to_epoch(None) == 0
