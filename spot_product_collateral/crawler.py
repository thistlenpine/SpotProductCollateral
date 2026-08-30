from dataclasses import dataclass, field


@dataclass
class TastingProfileResult:
    found: bool
    tasting_profile: str | None = None
    sources: list[str] = field(default_factory=list)


def crawl_tasting_profile(product_name: str, client) -> TastingProfileResult:
    response = client.messages.create(
        model="claude-opus-5",
        max_tokens=1024,
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}],
        messages=[{
            "role": "user",
            "content": (
                f"Search the web for tasting notes, region of origin, and ABV for "
                f'the product "{product_name}". Write a short original summary in '
                "your own words (do not quote source text verbatim) covering "
                "tasting profile, region, and ABV if you can find them. If you "
                "cannot find reliable information, say so plainly."
            ),
        }],
    )

    text_parts = []
    sources = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "web_search_tool_result":
            content = block.content
            if isinstance(content, list):
                for result in content:
                    url = getattr(result, "url", None)
                    if url:
                        sources.append(url)

    summary = "\n".join(text_parts).strip()
    if not sources or not summary:
        return TastingProfileResult(found=False)
    return TastingProfileResult(found=True, tasting_profile=summary, sources=sources)
