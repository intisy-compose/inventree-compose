"""Keeps an InvenTree inventory consistent by driving it from a declared taxonomy.

`data/catalog.toml` declares the categories, fields, tags, locations and models (parts) the inventory
may use. `sync` makes InvenTree match it, `check` lists every difference, and `add` / `update` write
assets from batch files validated against it first. Run through the CLI:
`.\\docker-compose.ps1 catalog <command> [file]`.
"""

import argparse
import sys

from inventory import assets, images, sync
from inventory.api import ApiError
from inventory.settings import connect
from inventory.taxonomy import CatalogError, load_catalog, load_toml


def batch_from(path):
    if not path:
        raise CatalogError("this command needs a batch file")
    batch = load_toml(path).get("assets", [])
    if not batch:
        raise CatalogError(f"{path} has no [[assets]] entries")
    return batch


def run(arguments):
    taxonomy = load_catalog()
    client = connect()
    command = arguments.command
    if command == "check":
        lines = sync.check(taxonomy, client) + assets.check_items(client)
        print("\n".join(lines) if lines else "catalog and InvenTree agree")
        return 1 if lines else 0
    if command == "sync":
        lines = sync.sync(taxonomy, client) + images.apply_model_images(taxonomy, client, only_missing=True)
    elif command == "images":
        lines = images.apply_model_images(taxonomy, client, only_missing=False)
    elif command == "add":
        lines = assets.add_assets(batch_from(arguments.file), taxonomy, client)
    elif command == "update":
        lines = assets.update_assets(batch_from(arguments.file), taxonomy, client)
    else:
        lines = assets.list_assets(client)
    print("\n".join(lines) if lines else "nothing to do")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="docker-compose.ps1 catalog")
    parser.add_argument("command", choices=["check", "sync", "add", "update", "list", "images"])
    parser.add_argument("file", nargs="?", help="batch file for add / update")
    try:
        return run(parser.parse_args())
    except (CatalogError, ApiError) as error:
        print(f"catalog: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
