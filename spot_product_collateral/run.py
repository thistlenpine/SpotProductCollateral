import json
import logging
from datetime import datetime, timezone

import anthropic
import requests

from spot_product_collateral.bottlepos_scan import find_items_needing_enrichment
from spot_product_collateral.crawler import crawl_tasting_profile
from spot_product_collateral.enrichment import build_product_fields
from spot_product_collateral.pocketbase_client import PocketBaseClient
from spot_product_collateral.state import State
from spot_product_collateral.upc_lookup import lookup_upc
from spot_product_collateral.verifier import verify_manifest

logger = logging.getLogger(__name__)


def _download_image(url: str):
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "image/jpeg")
    filename = url.rsplit("/", 1)[-1] or "image.jpg"
    return {"image": (filename, resp.content, content_type)}


def run_once(config, bottlepos_items: list, state_path: str, manifest_path: str) -> dict:
    pb_client = PocketBaseClient(config.pocketbase_url, config.pb_superuser_email, config.pb_superuser_password)
    anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y-%m-%d")
    manifest = {
        "run_id": run_id,
        "generated_at": now.isoformat(),
        "items": [],
        "errors": [],
    }

    pending = find_items_needing_enrichment(bottlepos_items, pb_client)
    for item, item_hash in pending:
        try:
            upc_result = lookup_upc(item.code)
            tasting_result = crawl_tasting_profile(item.name, client=anthropic_client)
            fields = build_product_fields(item, item_hash, upc_result, tasting_result, now.isoformat())

            files = None
            if upc_result.image_url:
                try:
                    files = _download_image(upc_result.image_url)
                except Exception as exc:
                    logger.warning(
                        "Failed to download image %s: %s", upc_result.image_url, exc
                    )
                    files = None

            pb_client.upsert_by_upc("products", item.code, fields, files=files)
            manifest["items"].append({"upc": item.code, "status": fields["status"]})
        except Exception as exc:
            manifest["errors"].append({"upc": getattr(item, "code", None), "error": str(exc)})

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    state = State.load(state_path)
    if verify_manifest(manifest):
        state.consecutive_failures = 0
        state.last_run = now.isoformat()
        state.last_run_id = run_id
    else:
        state.consecutive_failures += 1
    state.save(state_path)

    return manifest
