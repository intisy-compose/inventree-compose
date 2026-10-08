"""One-time move from shelf-compose: reads its catalog.toml and its database (read-only) and writes this
repo's data/catalog.toml and one import batch with every asset under its existing ID.

    python scripts/import_shelf.py <shelf-compose checkout> [--db-container shelf-db]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from collections import defaultdict

from inventory.settings import CATALOG_PATH, DATA_DIR

LABEL_DEFAULTS = {
    "large": ["Computers", "Drive enclosures", "Cases", "Power supplies", "UPS units", "Network equipment", "Backup drives"],
    "standard": ["Graphics cards", "Storage drives", "Motherboards", "Storage controllers", "CPU coolers", "Carrier boards",
                 "Compute modules", "Optical drives", "Internal boards", "Displays"],
    "small": ["Memory", "Fans", "USB drives", "Wireless adapters", "Add-on boards", "Drive caddies", "Processors"],
    "none": ["Memory cards", "Batteries", "Input devices", "Chassis parts", "Cameras", "Network adapters"],
}
HOST_CATEGORIES = ("Computers", "Drive enclosures")
SUPPORTED_TYPES = {"TEXT", "NUMBER", "OPTION", "BOOLEAN"}
UNIT_FIELDS = {"Condition"}
LOCATED_IN = re.compile(r"is an asset located in '[^']+'")
IMPORT_FILE = "intake/2026-10-08-import-from-shelf.toml"


def query(container, select_sql):
    command = ["docker", "exec", "-i", container, "psql", "-U", "postgres", "-d", "postgres", "-tA", "-c",
               f"select coalesce(json_agg(q), '[]') from ({select_sql}) q"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        sys.exit(result.stderr)
    return json.loads(result.stdout)


def read_shelf(container):
    assets = query(container, 'select a."sequentialId" as id, m.name as model, c.name as category, l.name as location, '
                              'a.value, a.description from "Asset" a join "AssetModel" m on m.id = a."assetModelId" '
                              'join "Category" c on c.id = a."categoryId" left join "AssetLocation" al on al."assetId" = a.id '
                              'left join "Location" l on l.id = al."locationId" order by a."sequentialId"')
    values = query(container, 'select a."sequentialId" as id, f.name as field, v.value -> \'raw\' as raw from "AssetCustomFieldValue" v '
                              'join "Asset" a on a.id = v."assetId" join "CustomField" f on f.id = v."customFieldId"')
    tags = query(container, 'select a."sequentialId" as id, t.name as tag from "_AssetToTag" x join "Asset" a on a.id = x."A" '
                            'join "Tag" t on t.id = x."B"')
    return assets, values, tags


def host_locations(assets, location_names):
    """A location named after a bought computer or enclosure becomes that item: its parts are installed in it."""
    hosts = {}
    for name in location_names:
        matches = [asset for asset in assets if asset["category"] in HOST_CATEGORIES
                   and (asset["model"] == name or asset["model"].endswith(" " + name))]
        if len(matches) == 1:
            hosts[name] = matches[0]["id"]
    return hosts


def model_fields(assets, values):
    """Model specs are the values all of a model's assets share; anything else stays with the unit."""
    by_asset = defaultdict(dict)
    for row in values:
        by_asset[row["id"]][row["field"]] = row["raw"]
    by_model = defaultdict(list)
    for asset in assets:
        by_model[asset["model"]].append(by_asset[asset["id"]])
    shared, per_unit = {}, defaultdict(dict)
    for model, unit_values in by_model.items():
        names = {name for unit in unit_values for name in unit} - UNIT_FIELDS
        shared[model] = {}
        for name in sorted(names):
            seen = {json.dumps(unit.get(name)) for unit in unit_values}
            if len(seen) == 1:
                shared[model][name] = unit_values[0][name]
    for asset in assets:
        for name, raw in by_asset[asset["id"]].items():
            if name not in UNIT_FIELDS and name not in shared[asset["model"]]:
                per_unit[asset["id"]][name] = raw
    return shared, per_unit, by_asset


def toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(int(value)) if float(value).is_integer() else repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{json.dumps(key)} = {toml_value(item)}" for key, item in value.items()) + " }"
    return json.dumps(value, ensure_ascii=False)


def toml_table(kind, entry):
    return f"[[{kind}]]\n" + "".join(f"{key} = {toml_value(value)}\n" for key, value in entry.items() if value not in (None, "", [], {}))


def new_catalog(old, hosts, shared, model_tags):
    label_of = {category: size for size, names in LABEL_DEFAULTS.items() for category in names}
    blocks = ["# The inventory's taxonomy: every category, field, tag, location and model (part) InvenTree may\n"
              "# use. `.\\docker-compose.ps1 catalog sync` makes InvenTree match this file, and `add` / `update`\n"
              "# refuse anything not declared here. Conventions and the intake procedure are in CATALOG.md.\n"]
    for category in old.get("categories", []):
        blocks.append(toml_table("categories", {"name": category["name"], "description": category.get("description"),
                                                "label": label_of.get(category["name"], "standard")}))
    for field in old.get("fields", []):
        if field["name"] in UNIT_FIELDS:
            continue
        if field.get("type", "TEXT") not in SUPPORTED_TYPES:
            sys.exit(f"field {field['name']}: type {field.get('type')} has no InvenTree equivalent here")
        blocks.append(toml_table("fields", {key: field.get(key) for key in ("name", "type", "options", "help", "categories", "required")}))
    for tag in old.get("tags", []):
        blocks.append(toml_table("tags", {"name": tag["name"], "description": tag.get("description")}))
    for location in old.get("locations", []):
        if location["name"] not in hosts:
            blocks.append(toml_table("locations", {key: location.get(key) for key in ("name", "parent", "description")}))
    for model in old.get("models", []):
        blocks.append(toml_table("models", {"name": model["name"], "category": model["category"], "image": model.get("image"),
                                            "tags": sorted(model_tags.get(model["name"], [])),
                                            "fields": shared.get(model["name"], {})}))
    return "\n".join(blocks)


def unit_description(asset, per_unit):
    description = LOCATED_IN.sub("is an asset installed in it", asset.get("description") or "")
    extras = [f"{name}: {raw}." for name, raw in per_unit.get(asset["id"], {}).items()]
    return " ".join(part for part in [description, *extras] if part)


def import_batch(assets, hosts, per_unit, by_asset):
    blocks = ["# Every asset moved from shelf.nu on 2026-10-08, under its shelf ID. Parts that sat in a location\n"
              "# named after a bought computer or enclosure are installed in that item instead.\n"]
    for asset in assets:
        entry = {"id": asset["id"], "model": asset["model"]}
        if asset["location"] in hosts:
            entry["installed_in"] = hosts[asset["location"]]
        else:
            entry["location"] = asset["location"] or "Home"
        entry["condition"] = by_asset[asset["id"]].get("Condition", "Untested")
        entry["value"] = asset["value"]
        entry["description"] = unit_description(asset, per_unit)
        blocks.append(toml_table("assets", entry))
    return "\n".join(blocks)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("shelf_compose")
    parser.add_argument("--db-container", default="shelf-db")
    arguments = parser.parse_args()
    with open(os.path.join(arguments.shelf_compose, "data", "catalog.toml"), "rb") as handle:
        old = tomllib.load(handle)
    assets, values, tags = read_shelf(arguments.db_container)
    hosts = host_locations(assets, [location["name"] for location in old.get("locations", [])])
    shared, per_unit, by_asset = model_fields(assets, values)
    model_of = {asset["id"]: asset["model"] for asset in assets}
    model_tags = defaultdict(set)
    for row in tags:
        model_tags[model_of[row["id"]]].add(row["tag"])
    with open(CATALOG_PATH, "w", encoding="utf-8", newline="") as handle:
        handle.write(new_catalog(old, hosts, shared, model_tags))
    with open(os.path.join(DATA_DIR, IMPORT_FILE), "w", encoding="utf-8", newline="") as handle:
        handle.write(import_batch(assets, hosts, per_unit, by_asset))
    print(f"hosts: {hosts}")
    print(f"per-unit fields: {dict(per_unit)}")
    print(f"wrote data/catalog.toml and data/{IMPORT_FILE}: {len(assets)} assets")


if __name__ == "__main__":
    main()
