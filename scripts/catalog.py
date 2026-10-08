"""Keeps an InvenTree inventory consistent by driving it from a declared taxonomy.

`data/catalog.toml` declares the categories, fields, tags, locations and models (parts) the inventory
may use. `sync` makes InvenTree match it, `check` lists every difference, and `add` / `update` write
assets from batch files validated against it first. Run through the CLI:
`.\\docker-compose.ps1 catalog <command> [file]`.
"""

import argparse
import sys

from inventory import assets, images, labels, sync
from inventory.api import ApiError
from inventory.settings import LABELS_PATH, connect, read_config, site_url
from inventory.taxonomy import CatalogError, load_catalog, load_toml


def batch_from(path):
    if not path:
        raise CatalogError("this command needs a batch file")
    batch = load_toml(path).get("assets", [])
    if not batch:
        raise CatalogError(f"{path} has no [[assets]] entries")
    return batch


def print_labels(client, arguments):
    wanted = [part.strip() for part in arguments.ids.split(",")] if arguments.ids else []
    chosen, unlabelled = assets.collect_labels(client, site_url(read_config()), wanted)
    lines = labels.write_sheets(chosen, arguments.file or LABELS_PATH, arguments.outline)
    if unlabelled:
        lines.append(f"  none: {len(unlabelled)} assets get no label: {', '.join(unlabelled)}")
    return lines


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
    elif command == "list":
        lines = assets.list_assets(client)
    else:
        lines = print_labels(client, arguments)
    print("\n".join(lines) if lines else "nothing to do")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="docker-compose.ps1 catalog")
    parser.add_argument("command", choices=["check", "sync", "add", "update", "list", "images", "labels"])
    parser.add_argument("file", nargs="?", help="batch file for add / update, PDF to write for labels")
    parser.add_argument("--ids", help="labels: only these assets, comma separated, e.g. SAM-0001,SAM-0007")
    parser.add_argument("--outline", action="store_true", help="labels: also draw the ring edges, for a test print")
    try:
        return run(parser.parse_args())
    except (CatalogError, ApiError) as error:
        print(f"catalog: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
