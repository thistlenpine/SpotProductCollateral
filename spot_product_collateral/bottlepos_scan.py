import hashlib


def snapshot_hash(item) -> str:
    basis = f"{item.name}|{item.description}|{item.category_name}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def find_items_needing_enrichment(items, pb_client):
    to_enrich = []
    for item in items:
        if not item.code:
            continue
        new_hash = snapshot_hash(item)
        existing = pb_client.find_by_upc("products", item.code)
        if existing is None or existing.get("bottlepos_snapshot_hash") != new_hash:
            to_enrich.append((item, new_hash))
    return to_enrich
