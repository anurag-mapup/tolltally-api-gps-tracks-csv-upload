"""
Tests for gps-tracks-csv-upload.py

Inspired by the testing patterns in mapup-product-frontend (Jest / TypeScript):
  - Group tests by function (analogous to describe() blocks → pytest classes)
  - Mock HTTP calls at the call site, capture args, verify URL / headers / body
  - Cover success, edge-case, and exhausted-retry paths
  - Reset mocks between tests via autouse fixtures
  - One assertion per concern — names describe what is verified

Dependencies:
    pip install pytest requests
"""

import sys
import os
import json
import importlib.util
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
MOCK_API_KEY = "test-api-key-123"
MOCK_CSV_CONTENT = b"latitude,longitude,timestamp\n47.24157,0.69426,2023-01-12T13:40:35Z\n"
MOCK_CSV_PATH = "Sample-GPS-tracks/france-GPS-Track-sample.csv"

_SCRIPT_PATH = str(Path(__file__).parent.parent / "gps-tracks-csv-upload.py")


def _make_response(body: dict) -> MagicMock:
    """Return a mock requests.Response whose .text is the JSON-encoded body."""
    resp = MagicMock()
    resp.text = json.dumps(body)
    return resp


# ---------------------------------------------------------------------------
# Import guard
#
# The script file is named with hyphens (not a valid Python identifier), so
# standard `import` won't work.  importlib.util lets us load it by path.
#
# The module also executes print() + real API calls at load time (lines 62-67).
# Every dependency that causes I/O must be mocked before exec_module() runs so
# the test suite loads cleanly without a live API key or network.
# ---------------------------------------------------------------------------
_import_side_effects = [
    _make_response({"status": "success", "id": "import-sync"}),   # gps_tracks_csv_upload()
    _make_response({"status": "success", "id": "import-async"}),  # gps_tracks_csv_upload(is_async=True)
    _make_response({"status": "success", "data": {}}),            # gps_tracks_csv_download()
]

_spec = importlib.util.spec_from_file_location("gps_tracks_csv_upload", _SCRIPT_PATH)
module = importlib.util.module_from_spec(_spec)
sys.modules["gps_tracks_csv_upload"] = module

with (
    patch.dict("os.environ", {"TOLLGURU_API_KEY": MOCK_API_KEY}),
    patch("requests.request", side_effect=_import_side_effects),
    patch("builtins.open", mock_open(read_data=MOCK_CSV_CONTENT)),
    patch("time.sleep"),
):
    _spec.loader.exec_module(module)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def set_api_key():
    """Pin TOLLGURU_API_KEY on the module object for every test."""
    original = module.TOLLGURU_API_KEY
    module.TOLLGURU_API_KEY = MOCK_API_KEY
    yield
    module.TOLLGURU_API_KEY = original


# ---------------------------------------------------------------------------
# describe("gps_tracks_csv_upload")
# ---------------------------------------------------------------------------

class TestGpsTracksCsvUpload:
    """Unit tests for the gps_tracks_csv_upload() function."""

    def _call(self, is_async: bool = False):
        """Helper: call the function under test with all I/O mocked."""
        mock_resp = _make_response({"status": "success", "id": "t-1"})
        mock_req = MagicMock(return_value=mock_resp)
        with (
            patch("requests.request", mock_req),
            patch("builtins.open", mock_open(read_data=MOCK_CSV_CONTENT)),
        ):
            result = module.gps_tracks_csv_upload(is_async=is_async)
        return result, mock_req

    # --- HTTP method -----------------------------------------------------------

    def test_uses_post_method(self):
        _, mock_req = self._call()
        assert mock_req.call_args[0][0] == "POST"

    # --- URL construction ------------------------------------------------------

    def test_posts_to_upload_endpoint(self):
        """URL path must end with the GPS upload endpoint name."""
        _, mock_req = self._call()
        url = mock_req.call_args[0][1]
        assert urlparse(url).path.endswith(module.GPS_UPLOAD_ENDPOINT)

    def test_url_uses_configured_api_base(self):
        _, mock_req = self._call()
        url = mock_req.call_args[0][1]
        assert url.startswith(module.TOLLGURU_API_URL)

    def test_sync_mode_sets_is_async_false_in_query(self):
        _, mock_req = self._call(is_async=False)
        params = parse_qs(urlparse(mock_req.call_args[0][1]).query)
        assert params["isAsync"][0] == "False"

    def test_async_mode_sets_is_async_true_in_query(self):
        _, mock_req = self._call(is_async=True)
        params = parse_qs(urlparse(mock_req.call_args[0][1]).query)
        assert params["isAsync"][0] == "True"

    def test_url_includes_vehicle_weight(self):
        _, mock_req = self._call()
        params = parse_qs(urlparse(mock_req.call_args[0][1]).query)
        assert params["weight"][0] == str(module.PARAMETERS["vehicle"]["weight"])

    def test_url_includes_vehicle_height(self):
        _, mock_req = self._call()
        params = parse_qs(urlparse(mock_req.call_args[0][1]).query)
        assert params["height"][0] == str(module.PARAMETERS["vehicle"]["height"])

    def test_url_includes_vehicle_type(self):
        _, mock_req = self._call()
        params = parse_qs(urlparse(mock_req.call_args[0][1]).query)
        assert params["type"][0] == module.PARAMETERS["vehicle"]["type"]

    # --- Headers ---------------------------------------------------------------

    def test_sends_api_key_header(self):
        """x-api-key header must carry the value from TOLLGURU_API_KEY."""
        _, mock_req = self._call()
        assert mock_req.call_args[1]["headers"]["x-api-key"] == MOCK_API_KEY

    def test_sends_content_type_text_csv(self):
        _, mock_req = self._call()
        assert mock_req.call_args[1]["headers"]["Content-Type"] == "text/csv"

    # --- File I/O --------------------------------------------------------------

    def test_opens_csv_file_in_binary_mode(self):
        """The CSV payload file must be opened in binary ('rb') mode."""
        mock_resp = _make_response({"status": "success"})
        with (
            patch("requests.request", return_value=mock_resp),
            patch("builtins.open", mock_open(read_data=MOCK_CSV_CONTENT)) as m_open,
        ):
            module.gps_tracks_csv_upload()

        m_open.assert_called_once_with(MOCK_CSV_PATH, "rb")

    # --- Return value ----------------------------------------------------------

    def test_returns_raw_response_object(self):
        """The requests.Response object must be returned unchanged."""
        mock_resp = _make_response({"status": "success", "id": "t-99"})
        with (
            patch("requests.request", return_value=mock_resp),
            patch("builtins.open", mock_open(read_data=MOCK_CSV_CONTENT)),
        ):
            result = module.gps_tracks_csv_upload()

        assert result is mock_resp

    # --- Call count ------------------------------------------------------------

    def test_makes_exactly_one_http_call(self):
        _, mock_req = self._call()
        assert mock_req.call_count == 1


# ---------------------------------------------------------------------------
# describe("gps_tracks_csv_download")
# ---------------------------------------------------------------------------

class TestGpsTracksCsvDownload:
    """Unit tests for the gps_tracks_csv_download() function."""

    # Simulates the raw bytes that gps_tracks_csv_upload() returns as a response
    UPLOAD_RESPONSE_BODY = json.dumps({"status": "success", "id": "t-1"}).encode()

    # --- HTTP method -----------------------------------------------------------

    def test_uses_post_method(self):
        mock_resp = _make_response({"status": "success"})
        with (
            patch("requests.request", return_value=mock_resp) as mock_req,
            patch("gps_tracks_csv_upload.sleep"),
        ):
            module.gps_tracks_csv_download(self.UPLOAD_RESPONSE_BODY, retry=1, delay=0)

        assert mock_req.call_args[0][0] == "POST"

    # --- URL construction ------------------------------------------------------

    def test_posts_to_download_endpoint(self):
        mock_resp = _make_response({"status": "success"})
        with (
            patch("requests.request", return_value=mock_resp) as mock_req,
            patch("gps_tracks_csv_upload.sleep"),
        ):
            module.gps_tracks_csv_download(self.UPLOAD_RESPONSE_BODY, retry=1, delay=0)

        url = mock_req.call_args[0][1]
        assert urlparse(url).path.endswith(module.GPS_DOWNLOAD_ENDPOINT)

    def test_url_uses_configured_api_base(self):
        mock_resp = _make_response({"status": "success"})
        with (
            patch("requests.request", return_value=mock_resp) as mock_req,
            patch("gps_tracks_csv_upload.sleep"),
        ):
            module.gps_tracks_csv_download(self.UPLOAD_RESPONSE_BODY, retry=1, delay=0)

        assert mock_req.call_args[0][1].startswith(module.TOLLGURU_API_URL)

    # --- Headers ---------------------------------------------------------------

    def test_sends_api_key_header(self):
        mock_resp = _make_response({"status": "success"})
        with (
            patch("requests.request", return_value=mock_resp) as mock_req,
            patch("gps_tracks_csv_upload.sleep"),
        ):
            module.gps_tracks_csv_download(self.UPLOAD_RESPONSE_BODY, retry=1, delay=0)

        assert mock_req.call_args[1]["headers"]["x-api-key"] == MOCK_API_KEY

    def test_sends_content_type_application_json(self):
        mock_resp = _make_response({"status": "success"})
        with (
            patch("requests.request", return_value=mock_resp) as mock_req,
            patch("gps_tracks_csv_upload.sleep"),
        ):
            module.gps_tracks_csv_download(self.UPLOAD_RESPONSE_BODY, retry=1, delay=0)

        assert mock_req.call_args[1]["headers"]["Content-Type"] == "application/json"

    # --- Request body ----------------------------------------------------------

    def test_forwards_upload_response_as_request_body(self):
        """The upload response must be forwarded verbatim as the POST body."""
        mock_resp = _make_response({"status": "success"})
        with (
            patch("requests.request", return_value=mock_resp) as mock_req,
            patch("gps_tracks_csv_upload.sleep"),
        ):
            module.gps_tracks_csv_download(self.UPLOAD_RESPONSE_BODY, retry=1, delay=0)

        assert mock_req.call_args[1]["data"] == self.UPLOAD_RESPONSE_BODY

    # --- Retry logic -----------------------------------------------------------

    def test_stops_on_first_successful_response(self):
        """Must stop polling as soon as the API returns a non-ERROR status."""
        mock_resp = _make_response({"status": "success", "data": {"tolls": []}})
        with (
            patch("requests.request", return_value=mock_resp) as mock_req,
            patch("gps_tracks_csv_upload.sleep"),
        ):
            module.gps_tracks_csv_download(self.UPLOAD_RESPONSE_BODY, retry=5, delay=0)

        assert mock_req.call_count == 1

    def test_retries_while_status_is_error(self):
        """Must keep polling while the API returns status=ERROR."""
        responses = [
            _make_response({"status": "ERROR"}),
            _make_response({"status": "ERROR"}),
            _make_response({"status": "success", "data": {}}),
        ]
        with (
            patch("requests.request", side_effect=responses) as mock_req,
            patch("gps_tracks_csv_upload.sleep"),
        ):
            module.gps_tracks_csv_download(self.UPLOAD_RESPONSE_BODY, retry=5, delay=0)

        assert mock_req.call_count == 3

    def test_exhausts_all_retries_and_returns_last_error_response(self):
        """After retry attempts are exhausted, the last response must be returned."""
        error_resp = _make_response({"status": "ERROR", "msg": "still processing"})
        with (
            patch("requests.request", return_value=error_resp),
            patch("gps_tracks_csv_upload.sleep"),
        ):
            result = module.gps_tracks_csv_download(
                self.UPLOAD_RESPONSE_BODY, retry=3, delay=0
            )

        assert result["status"] == "ERROR"

    def test_zero_retries_still_makes_one_request(self):
        """retry=0 means the loop body runs exactly once (while count >= 0)."""
        mock_resp = _make_response({"status": "ERROR"})
        with (
            patch("requests.request", return_value=mock_resp) as mock_req,
            patch("gps_tracks_csv_upload.sleep"),
        ):
            module.gps_tracks_csv_download(self.UPLOAD_RESPONSE_BODY, retry=0, delay=0)

        assert mock_req.call_count == 1

    # --- Sleep / delay ---------------------------------------------------------

    def test_sleeps_after_each_iteration(self):
        """sleep() must be called once per loop iteration."""
        responses = [
            _make_response({"status": "ERROR"}),
            _make_response({"status": "success"}),
        ]
        with (
            patch("requests.request", side_effect=responses),
            patch("gps_tracks_csv_upload.sleep") as mock_sleep,
        ):
            module.gps_tracks_csv_download(self.UPLOAD_RESPONSE_BODY, retry=5, delay=3)

        assert mock_sleep.call_count == 2

    def test_sleeps_with_configured_delay(self):
        """sleep() must receive the caller-supplied delay value."""
        mock_resp = _make_response({"status": "success"})
        with (
            patch("requests.request", return_value=mock_resp),
            patch("gps_tracks_csv_upload.sleep") as mock_sleep,
        ):
            module.gps_tracks_csv_download(self.UPLOAD_RESPONSE_BODY, retry=1, delay=7)

        mock_sleep.assert_called_with(7)

    def test_default_delay_is_five_seconds(self):
        """The default delay=5 must be forwarded to sleep()."""
        mock_resp = _make_response({"status": "success"})
        with (
            patch("requests.request", return_value=mock_resp),
            patch("gps_tracks_csv_upload.sleep") as mock_sleep,
        ):
            module.gps_tracks_csv_download(self.UPLOAD_RESPONSE_BODY)

        mock_sleep.assert_called_with(5)

    # --- Return value ----------------------------------------------------------

    def test_returns_parsed_json_dict(self):
        """Return value must be a dict (JSON-parsed), not a raw response object."""
        expected = {"status": "success", "data": {"tolls": [{"cost": 5.0}]}}
        with (
            patch("requests.request", return_value=_make_response(expected)),
            patch("gps_tracks_csv_upload.sleep"),
        ):
            result = module.gps_tracks_csv_download(
                self.UPLOAD_RESPONSE_BODY, retry=1, delay=0
            )

        assert result == expected


# ---------------------------------------------------------------------------
# describe("module-level constants")
# ---------------------------------------------------------------------------

class TestModuleConstants:
    """Sanity-check that the API configuration values are correct."""

    def test_api_base_url(self):
        assert module.TOLLGURU_API_URL == "https://apis.tollguru.com/toll/v2"

    def test_upload_endpoint(self):
        assert module.GPS_UPLOAD_ENDPOINT == "gps-tracks-csv-upload"

    def test_download_endpoint(self):
        assert module.GPS_DOWNLOAD_ENDPOINT == "gps-tracks-csv-download"

    def test_default_vehicle_type(self):
        assert module.PARAMETERS["vehicle"]["type"] == "5AxlesTruck"

    def test_default_vehicle_weight(self):
        assert module.PARAMETERS["vehicle"]["weight"] == 3000

    def test_default_vehicle_height(self):
        assert module.PARAMETERS["vehicle"]["height"] == 10
