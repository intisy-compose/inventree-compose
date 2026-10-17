import os

from .api import Client, UnreachableError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
CATALOG_PATH = os.path.join(DATA_DIR, "catalog.toml")
CONFIG_PATH = os.path.join(ROOT, "config.env")


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


LOOPBACK_URL = "http://localhost:8441"


def connect():
    """@implNote The tailnet name resolves only while this PC is on the tailnet; the gateway serves
    the same InvenTree on the host's loopback (RULES.md section 2), so filing never waits on it."""
    config = read_config()
    user, password = config["INVENTREE_ADMIN_USER"], config["INVENTREE_ADMIN_PASSWORD"]
    try:
        return Client(site_url(config), user, password)
    except UnreachableError:
        return Client(LOOPBACK_URL, user, password)
