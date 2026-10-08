import os

from .api import Client

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
CATALOG_PATH = os.path.join(DATA_DIR, "catalog.toml")
CONFIG_PATH = os.path.join(ROOT, "config.env")
LABELS_PATH = os.path.join(DATA_DIR, "labels", "labels.pdf")


def read_config():
    values = {}
    with open(CONFIG_PATH, encoding="utf-8") as handle:
        for line in handle:
            name, separator, value = line.strip().partition("=")
            if separator and not name.startswith("#"):
                values[name.strip()] = value.strip().strip('"')
    return values


def site_url(config):
    return f"https://{config['INVENTREE_HOST']}"


def connect():
    config = read_config()
    return Client(site_url(config), config["INVENTREE_ADMIN_USER"], config["INVENTREE_ADMIN_PASSWORD"])
