"""Assets are serialized stock items: one per physical thing, its asset ID as the serial number."""

import re

from .sync import UNTESTED_STATE, Change, by_name, tags_by_pk
from .taxonomy import LABEL_SIZES, CatalogError, label_size, require

ASSET_KEYS = {"id", "model", "location", "installed_in", "condition", "value", "description", "label", "quantity"}
ASSET_ID = re.compile(r"^SAM-\d{4,}$")
CONDITIONS = {"Tested working": 10, "Untested": UNTESTED_STATE["key"], "Needs repair": 50, "Broken": 55}
LABEL_TAG = "label-"
# Marks an asset whose label size was set on the asset itself, so sync leaves it alone. It must not start
# with LABEL_TAG, which the label printer reads as a size.
OWN_LABEL_TAG = "own-label"


def remote_items(client):
    label_tags = tags_by_pk(client, "/api/stock/", [LABEL_TAG + size for size in LABEL_SIZES] + [OWN_LABEL_TAG])
    items = {}
    for item in client.get("/api/stock/", part_detail="true"):
        if item.get("serial"):
            item["tags"] = sorted(label_tags.get(item["pk"], set()))
            items[item["serial"]] = item
    return items


def next_ids(existing_ids, count):
    numbers = [int(asset_id.split("-")[1]) for asset_id in existing_ids if ASSET_ID.match(asset_id)]
    start = max(numbers, default=0) + 1
    return [f"SAM-{number:04d}" for number in range(start, start + count)]


def validate_entry(entry, taxonomy, known_ids, adding):
    context = f"asset {entry.get('id', entry.get('model', '?'))}"
    unknown = set(entry) - ASSET_KEYS
    if unknown:
        raise CatalogError(f"{context}: unknown keys {', '.join(sorted(unknown))}")
    if "id" in entry and not ASSET_ID.match(entry["id"]):
        raise CatalogError(f"{context}: id must look like SAM-0001")
    if adding:
        for key in ("model", "condition"):
            if key not in entry:
                raise CatalogError(f"{context}: '{key}' is required")
        if ("location" in entry) == ("installed_in" in entry):
            raise CatalogError(f"{context}: give exactly one of 'location' or 'installed_in'")
    if "model" in entry:
        require(taxonomy, "models", entry["model"], context)
    if "location" in entry:
        require(taxonomy, "locations", entry["location"], context)
    if "installed_in" in entry and entry["installed_in"] not in known_ids:
        raise CatalogError(f"{context}: installed_in '{entry['installed_in']}' is not an asset")
    if "condition" in entry and entry["condition"] not in CONDITIONS:
        raise CatalogError(f"{context}: condition must be one of {', '.join(CONDITIONS)}")
    if "value" in entry and (isinstance(entry["value"], bool) or not isinstance(entry["value"], (int, float)) or entry["value"] < 0):
        raise CatalogError(f"{context}: value must be a number of euros")
    if "label" in entry and entry["label"] not in LABEL_SIZES:
        raise CatalogError(f"{context}: label must be one of {', '.join(LABEL_SIZES)}")


def hosts_first(batch):
    """Orders a batch so an item is created before anything installed in it."""
    ordered, placed, pending = [], set(), list(batch)
    while pending:
        ready = [entry for entry in pending if entry.get("installed_in") not in {e["id"] for e in pending} or entry["installed_in"] in placed]
        if not ready:
            raise CatalogError("installed_in links form a cycle")
        for entry in ready:
            ordered.append(entry)
            placed.add(entry["id"])
            pending.remove(entry)
    return ordered


def item_body(entry, parts, locations, items):
    body = {}
    if "model" in entry:
        body["part"] = parts[entry["model"].lower()]["pk"]
    if "location" in entry:
        body["location"] = locations[entry["location"].lower()]["pk"]
    if "installed_in" in entry:
        body["belongs_to"] = items[entry["installed_in"]]["pk"]
        body["location"] = None
    if "condition" in entry:
        body["status_custom_key"] = CONDITIONS[entry["condition"]]
    if "value" in entry:
        body["purchase_price"] = str(entry["value"])
        body["purchase_price_currency"] = "EUR"
    if "description" in entry:
        body["notes"] = entry["description"]
    return body


def label_tags(taxonomy, entry, current_model_name):
    model = require(taxonomy, "models", entry.get("model", current_model_name), f"asset {entry.get('id')}")
    tags = [LABEL_TAG + label_size(taxonomy, model, entry.get("label"))]
    return tags + [OWN_LABEL_TAG] if entry.get("label") else tags


def is_stock(entry):
    """A quantity of identical small parts, one stock item without a serial number or a label."""
    return "quantity" in entry


def add_assets(batch, taxonomy, client):
    """Creating an item ignores its tags, so the label tag is set right after."""
    items = remote_items(client)
    assets = [entry for entry in batch if not is_stock(entry)]
    known = set(items) | {entry["id"] for entry in assets if "id" in entry}
    fresh = iter(next_ids(known, sum("id" not in entry for entry in assets)))
    for entry in assets:
        if "id" not in entry:
            entry["id"] = next(fresh)
        if entry["id"] in items:
            raise CatalogError(f"asset {entry['id']} already exists; use update")
    known = set(items) | {entry["id"] for entry in assets}
    for entry in batch:
        validate_entry(entry, taxonomy, known, adding=True)
        validate_serialization(entry, taxonomy)
    parts = by_name(client.get("/api/part/"))
    locations = by_name(client.get("/api/stock/location/"))
    lines = []
    for entry in hosts_first(assets):
        body = {**item_body(entry, parts, locations, items), "quantity": 1, "serial_numbers": entry["id"]}
        created = client.post("/api/stock/", body)
        item = created[0] if isinstance(created, list) else created
        client.patch(f"/api/stock/{item['pk']}/", {"tags": label_tags(taxonomy, entry, None)})
        items[entry["id"]] = item
        lines.append(f"+ {entry['id']} {entry['model']}")
    for entry in batch:
        if is_stock(entry):
            client.post("/api/stock/", {**item_body(entry, parts, locations, items), "quantity": entry["quantity"]})
            lines.append(f"+ {entry['quantity']} x {entry['model']}")
    return lines


def validate_serialization(entry, taxonomy):
    model = require(taxonomy, "models", entry["model"], f"asset {entry.get('id', entry['model'])}")
    serialized = model.get("serialized", True)
    if is_stock(entry) == serialized:
        kind = "an asset with an id" if serialized else "stock with a quantity"
        raise CatalogError(f"{entry['model']}: this model is filed as {kind}")
    if is_stock(entry) and (isinstance(entry["quantity"], bool) or not isinstance(entry["quantity"], int) or entry["quantity"] < 1):
        raise CatalogError(f"{entry['model']}: quantity must be a whole number above 0")
    if is_stock(entry) and ("id" in entry or "label" in entry or "installed_in" in entry):
        raise CatalogError(f"{entry['model']}: stock has no id, label or installed_in")


def update_assets(batch, taxonomy, client):
    items = remote_items(client)
    for entry in batch:
        if "id" not in entry or entry["id"] not in items:
            raise CatalogError(f"update needs the id of an existing asset: {entry.get('id')}")
        validate_entry(entry, taxonomy, set(items), adding=False)
        if "model" in entry:
            raise CatalogError(f"asset {entry['id']}: the model of an existing item cannot change; add a new asset")
    parts = by_name(client.get("/api/part/"))
    locations = by_name(client.get("/api/stock/location/"))
    lines = []
    for entry in batch:
        item = items[entry["id"]]
        body = item_body(entry, parts, locations, items)
        move_item(client, item, entry, body, items)
        if "label" in entry:
            body["tags"] = label_tags(taxonomy, entry, item["part_detail"]["name"])
        client.patch(f"/api/stock/{item['pk']}/", body)
        lines.append(f"~ {entry['id']} {item['part_detail']['name']}: {', '.join(sorted(set(entry) - {'id'}))}")
    return lines


def move_item(client, item, entry, body, items):
    """Installing and taking out go through InvenTree's own endpoints, which keep the item's history."""
    if "installed_in" in entry:
        body.pop("belongs_to")
        body.pop("location")
        client.post(f"/api/stock/{items[entry['installed_in']]['pk']}/install/", {"stock_item": item["pk"], "quantity": 1, "note": "catalog update"})
    elif "location" in entry and item.get("belongs_to"):
        client.post(f"/api/stock/{item['pk']}/uninstall/", {"location": body.pop("location"), "note": "catalog update"})


def plan_label_tags(taxonomy, client):
    """Brings every asset's label tag in line with its model and category, unless the asset set its own."""
    changes = []
    for asset_id, item in sorted(remote_items(client).items()):
        model = taxonomy["models"].get(item["part_detail"]["name"].lower())
        if model is None or OWN_LABEL_TAG in item["tags"]:
            continue
        wanted = label_size(taxonomy, model)
        if item_label_size(item) != wanted:
            changes.append(Change(f"~ {asset_id} {model['name']}: label {item_label_size(item)} -> {wanted}",
                                  lambda pk=item["pk"], wanted=wanted: client.patch(f"/api/stock/{pk}/", {"tags": [LABEL_TAG + wanted]})))
    return changes


def item_label_size(item):
    sizes = [tag[len(LABEL_TAG):] for tag in item.get("tags") or [] if tag.startswith(LABEL_TAG)]
    return sizes[0] if len(sizes) == 1 else None


def check_items(client):
    lines = []
    for asset_id, item in sorted(remote_items(client).items()):
        if item_label_size(item) is None:
            lines.append(f"! {asset_id}: needs exactly one label tag, has {item.get('tags')}")
        if item.get("purchase_price") and item.get("purchase_price_currency") != "EUR":
            lines.append(f"! {asset_id}: value is in {item.get('purchase_price_currency')}, not EUR")
    return lines


def list_assets(client):
    items = remote_items(client)
    by_pk = {item["pk"]: serial for serial, item in items.items()}
    locations = {location["pk"]: location["pathstring"] for location in client.get("/api/stock/location/")}
    lines = []
    for asset_id, item in sorted(items.items()):
        where = f"in {by_pk.get(item['belongs_to'], item['belongs_to'])}" if item.get("belongs_to") else locations.get(item.get("location"), "-")
        lines.append(f"{asset_id}  {item['part_detail']['name']}\n    {where}  {item.get('status_text')}  "
                     f"value {item.get('purchase_price') or '-'}  label {item_label_size(item)}")
    return lines
