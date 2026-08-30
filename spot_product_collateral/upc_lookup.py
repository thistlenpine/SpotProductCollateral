# spot_product_collateral/upc_lookup.py
from dataclasses import dataclass

import requests

UPCITEMDB_TRIAL_URL = "https://api.upcitemdb.com/prod/trial/lookup"


@dataclass
class UpcLookupResult:
    found: bool
    name: str | None = None
    image_url: str | None = None
    description: str | None = None


def lookup_upc(upc: str, session=None) -> UpcLookupResult:
    session = session or requests
    resp = session.get(UPCITEMDB_TRIAL_URL, params={"upc": upc}, timeout=10)
    if resp.status_code == 429:
        return UpcLookupResult(found=False)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items") or []
    if not items:
        return UpcLookupResult(found=False)
    item = items[0]
    images = item.get("images") or []
    return UpcLookupResult(
        found=True,
        name=item.get("title"),
        image_url=images[0] if images else None,
        description=item.get("description"),
    )
