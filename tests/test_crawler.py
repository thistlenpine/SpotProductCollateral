from types import SimpleNamespace
from spot_product_collateral.crawler import crawl_tasting_profile


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _search_result_block(urls):
    return SimpleNamespace(
        type="web_search_tool_result",
        content=[SimpleNamespace(url=u) for u in urls],
    )


def test_crawl_with_sources_and_text_is_found():
    response = SimpleNamespace(content=[
        _text_block("This vodka has notes of citrus and pepper, ABV 40%."),
        _search_result_block(["https://example.com/a", "https://example.com/b"]),
    ])
    client = _FakeClient(response)
    result = crawl_tasting_profile("Example Vodka 750ML", client=client)
    assert result.found is True
    assert "citrus" in result.tasting_profile
    assert result.sources == ["https://example.com/a", "https://example.com/b"]
    assert client.messages.last_kwargs["model"] == "claude-opus-5"
    tools = client.messages.last_kwargs["tools"]
    assert tools[0]["type"] == "web_search_20260209"
    assert tools[0]["name"] == "web_search"


def test_crawl_with_no_sources_is_not_found():
    response = SimpleNamespace(content=[
        _text_block("I could not find reliable information."),
    ])
    client = _FakeClient(response)
    result = crawl_tasting_profile("Obscure Item", client=client)
    assert result.found is False
    assert result.sources == []


def test_crawl_with_no_text_is_not_found():
    response = SimpleNamespace(content=[
        _search_result_block(["https://example.com/a"]),
    ])
    client = _FakeClient(response)
    result = crawl_tasting_profile("Item", client=client)
    assert result.found is False
