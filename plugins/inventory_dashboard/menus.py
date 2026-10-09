"""The data behind the inventory menus: Value, Efficiency, Attention, Machines and Stickers, each a tab on a
location, scoped to it and everything below it. See docs/specs/2026-10-09-inventory-menus.md in the compose
org."""

from . import power

STICKER_KEY = "sticker"
LABEL_TAG = "label-"
PRINTED_SIZES = ("large", "standard", "small")
CONDITIONS = {11: "Untested", 50: "Needs repair", 55: "Broken"}
NOTES_LIMIT = 300


def condition_of(item):
    """A built-in status is stored in `status`, a custom one only in `status_custom_key`."""
    return CONDITIONS.get(item.status_custom_key) or CONDITIONS.get(item.status)


def label_size(item):
    """The same rule as the label printer: one `label-*` tag gives the size, anything else is standard."""
    sizes = [tag.name[len(LABEL_TAG):] for tag in item.tags.all() if tag.name.startswith(LABEL_TAG)]
    return sizes[0] if len(sizes) == 1 else "standard"


def price_of(item):
    return float(item.purchase_price.amount) if item.purchase_price is not None else None


def where_of(item):
    if item.belongs_to_id:
        return f"in {item.belongs_to.serial}"
    return item.location.pathstring if item.location else ""


def role_of(item):
    roles = [tag.name[len(power.ROLE_TAG):] for tag in item.tags.all() if tag.name.startswith(power.ROLE_TAG)]
    return roles[0] if len(roles) == 1 else None


def link_of(item):
    return {"pk": item.pk, "id": item.serial, "name": item.part.name, "url": f"/web/stock/item/{item.pk}"}


class Scope:
    """A location with everything placed in it or below, and everything installed in those, with the stock
    items loaded once. No location means every location: the Stock page above them all."""

    def __init__(self, inventory, location_pk):
        from stock.models import StockItem

        self.inventory = inventory
        self.location_pk = location_pk
        self.location_pks = set(inventory.locations) if location_pk is None else inventory.locations_below(location_pk)
        self.assets = list(inventory.assets) if location_pk is None else inventory.location_and_below(location_pk)
        self.pks = {asset.pk for asset in self.assets}
        self.items = {item.pk: item for item in StockItem.objects.filter(pk__in=self.pks)
                      .select_related("part", "part__category", "location", "belongs_to").prefetch_related("tags")}
        self.children = {}
        for asset in self.assets:
            if asset.belongs_to is not None:
                self.children.setdefault(asset.belongs_to, []).append(self.items[asset.pk])

    def installed(self, item):
        return self.children.get(item.pk, [])

    def subtree(self, item):
        return [item] + [part for child in self.installed(item) for part in self.subtree(child)]

    def placed_at(self, location_pk):
        return [item for item in self.items.values() if item.location_id == location_pk and not item.belongs_to_id]

    def sorted_items(self):
        return sorted(self.items.values(), key=lambda item: item.serial)


def value_menu(scope):
    rows = [{**link_of(item), "category": item.part.category.name if item.part.category else "",
             "where": where_of(item), "price": price_of(item)} for item in scope.sorted_items()]
    priced = [row for row in rows if row["price"] is not None]
    categories = {}
    for row in rows:
        entry = categories.setdefault(row["category"], {"name": row["category"], "count": 0, "value": 0.0})
        entry["count"] += 1
        entry["value"] += row["price"] or 0.0
    locations = []
    for pk in scope.location_pks:
        below = {asset.pk for asset in scope.inventory.location_and_below(pk)}
        found = [row for row in rows if row["pk"] in below]
        if found:
            locations.append({"name": scope.inventory.locations[pk]["pathstring"], "count": len(found),
                              "value": sum(row["price"] or 0.0 for row in found)})
    machines = []
    for item in scope.sorted_items():
        if scope.installed(item):
            parts = scope.subtree(item)
            machines.append({**link_of(item), "count": len(parts), "value": sum(price_of(part) or 0.0 for part in parts)})
    return {"count": len(rows), "value": sum(row["price"] for row in priced), "unpriced": len(rows) - len(priced),
            "categories": sorted(categories.values(), key=lambda entry: -entry["value"]),
            "locations": sorted(locations, key=lambda entry: entry["name"]),
            "machines": sorted(machines, key=lambda entry: -entry["value"]), "assets": rows}


def efficiency_menu(scope, config):
    if config is None:
        return {"missing": True}
    machines = power.machine_summaries(scope.inventory, config, within=scope.pks)
    for row in machines:
        row["url"] = f"/web/stock/item/{row['pk']}"
    return {"machines": sorted(machines, key=lambda row: row["name"].split(" ", 1)[-1]),
            "locations": power.location_summaries(scope.inventory, config, within=scope.location_pks),
            "scale": {"utilisation": config["utilisation"], "resources": config["resources"], "profiles": config["profiles"],
                      "set": config.get("references_set", "")}}


def attention_menu(scope):
    rows = []
    for item in scope.sorted_items():
        condition = condition_of(item)
        if condition:
            notes = (item.notes or "").strip()
            rows.append({**link_of(item), "condition": condition, "where": where_of(item),
                         "notes": notes[:NOTES_LIMIT] + ("..." if len(notes) > NOTES_LIMIT else "")})
    return {"counts": {label: sum(row["condition"] == label for row in rows) for label in CONDITIONS.values()}, "items": rows}


def machines_menu(scope, config):
    summaries = {row["pk"]: row for row in power.machine_summaries(scope.inventory, config)} if config else {}

    def node(item):
        parts = scope.subtree(item)
        summary = summaries.get(item.pk, {})
        return {**link_of(item), "price": price_of(item), "value": sum(price_of(part) or 0.0 for part in parts), "role": role_of(item),
                "average_w": summary.get("average_w"), "score": summary.get("score"),
                "children": [node(child) for child in sorted(scope.installed(item), key=lambda child: child.serial)]}

    hosts = [item for item in scope.sorted_items() if scope.installed(item) and not item.belongs_to_id]
    return {"machines": [node(item) for item in hosts]}


def sticker_menu(scope):
    """Every asset that gets a sticker, in the order of the printed sheet: a group's own stickers (largest
    first), then its subgroups by name; a location and every machine (an item with parts in it) is a group."""
    def sticker(item):
        size = label_size(item)
        if size not in PRINTED_SIZES:
            return None
        return {"kind": "sticker", **link_of(item), "size": size, "stuck": (item.metadata or {}).get(STICKER_KEY)}

    def own_rows(items, depth):
        found = [row for row in (sticker(item) for item in items) if row]
        found.sort(key=lambda row: (PRINTED_SIZES.index(row["size"]), row["id"]))
        return [{**row, "depth": depth} for row in found]

    def group(name, own, subgroups, depth):
        """`subgroups` are (name, builder) pairs, built in name order; an empty group is left out."""
        inside = own_rows(own, depth + 1)
        for _, build in sorted(subgroups, key=lambda pair: pair[0]):
            inside += build(depth + 1)
        return [{"kind": "group", "name": name, "depth": depth}] + inside if inside else []

    def machine(item):
        parts = scope.installed(item)
        return lambda depth: group(f"{item.serial} {item.part.name}", [item] + [part for part in parts if not scope.installed(part)],
                                   [(f"{part.serial} {part.part.name}", machine(part)) for part in parts if scope.installed(part)], depth)

    def location(pk):
        placed = scope.placed_at(pk)
        sublocations = [child for child in scope.location_pks if scope.inventory.locations[child]["parent"] == pk]
        subgroups = ([(scope.inventory.locations[child]["name"], location(child)) for child in sublocations] +
                     [(f"{item.serial} {item.part.name}", machine(item)) for item in placed if scope.installed(item)])
        return lambda depth: group(scope.inventory.locations[pk]["name"], [item for item in placed if not scope.installed(item)],
                                   subgroups, depth)

    if scope.location_pk is not None:
        rows = location(scope.location_pk)(0)
    else:
        roots = [pk for pk in scope.location_pks if scope.inventory.locations[pk]["parent"] is None]
        rows = [row for pk in sorted(roots, key=lambda pk: scope.inventory.locations[pk]["name"]) for row in location(pk)(0)]
        rows += group("No location", [item for item in scope.placed_at(None) if not scope.installed(item)],
                      [(f"{item.serial} {item.part.name}", machine(item)) for item in scope.placed_at(None) if scope.installed(item)], 0)
    stickers = [row for row in rows if row["kind"] == "sticker"]
    return {"rows": rows, "total": len(stickers), "stuck": sum(bool(row["stuck"]) for row in stickers)}
