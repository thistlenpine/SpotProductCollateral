# tests/test_upc_lookup.py
import pytest

from spot_product_collateral.upc_lookup import lookup_upc


class _FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json_data = json_data

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 429:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.last_call = None

    def get(self, url, params=None, timeout=None):
        self.last_call = (url, params, timeout)
        return self._response


def test_lookup_found_returns_populated_result():
    response = _FakeResponse(200, {
        "code": "OK",
        "items": [{
            "title": "Example Vodka 750ML",
            "description": "A smooth vodka.",
            "images": ["https://example.com/vodka.jpg", "https://example.com/other.jpg"],
        }],
    })
    session = _FakeSession(response)
    result = lookup_upc("012345678905", session=session)
    assert result.found is True
    assert result.name == "Example Vodka 750ML"
    assert result.description == "A smooth vodka."
    assert result.image_url == "https://example.com/vodka.jpg"
    assert session.last_call[1] == {"upc": "012345678905"}


def test_lookup_no_items_returns_not_found():
    response = _FakeResponse(200, {"code": "OK", "items": []})
    session = _FakeSession(response)
    result = lookup_upc("000000000000", session=session)
    assert result.found is False


def test_lookup_rate_limited_raises():
    """A 429 is 'we couldn't check', not 'nothing found' — it must raise."""
    response = _FakeResponse(429, {})
    session = _FakeSession(response)
    with pytest.raises(RuntimeError):
        lookup_upc("000000000000", session=session)


def test_lookup_no_images_leaves_image_url_none():
    response = _FakeResponse(200, {
        "code": "OK",
        "items": [{"title": "No Image Item", "description": "desc", "images": []}],
    })
    session = _FakeSession(response)
    result = lookup_upc("111", session=session)
    assert result.found is True
    assert result.image_url is None
