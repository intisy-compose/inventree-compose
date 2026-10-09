"""Dashboard widgets for a personal hardware inventory kept by the catalog tool: assets are serialized
stock items, conditions are stock statuses, label sizes are `label-*` tags."""

import json

from django.db.models import Count, Q, Sum

from plugin import InvenTreePlugin
from plugin.mixins import SettingsMixin, UserInterfaceMixin

from . import menus, power
from .menus import CONDITIONS, STICKER_KEY, condition_of

LABEL_SIZES = ("large", "standard", "small", "none")
RECENT_COUNT = 8
TOP_CATEGORIES = 10


def item_link(item):
    return {"id": item.serial, "name": item.part.name, "url": f"/web/stock/item/{item.pk}"}


def assets():
    from stock.models import StockItem
    return StockItem.objects.filter(serial__startswith="SAM-").select_related("part", "part__category", "location")


def overview():
    items = assets()
    by_category = (items.values("part__category__name").annotate(count=Count("pk"), value=Sum("purchase_price"))
                   .order_by("-value", "-count")[:TOP_CATEGORIES])
    total = items.aggregate(value=Sum("purchase_price"))["value"] or 0
    return {"count": items.count(), "value": float(total),
            "categories": [{"name": row["part__category__name"], "count": row["count"], "value": float(row["value"] or 0)}
                           for row in by_category]}


def with_condition(items, key):
    """A built-in status is stored in `status`, a custom one only in `status_custom_key`."""
    return items.filter(Q(status_custom_key=key) | Q(status=key, status_custom_key__isnull=True))


def attention():
    items = assets()
    counts = {label: with_condition(items, key).count() for key, label in CONDITIONS.items()}
    faulty = (with_condition(items, 50) | with_condition(items, 55)).order_by("serial")
    return {"counts": counts, "faulty": [{**item_link(item), "condition": condition_of(item)} for item in faulty]}


def machines():
    hosts = assets().annotate(parts=Count("installed_parts")).filter(parts__gt=0).order_by("-parts")
    places = (assets().filter(belongs_to__isnull=True).exclude(location__isnull=True)
              .values("location__name").annotate(count=Count("pk")).order_by("-count"))
    return {"hosts": [{**item_link(host), "parts": host.parts} for host in hosts],
            "locations": [{"name": row["location__name"], "count": row["count"]} for row in places]}


def recent():
    return {"items": [{**item_link(item), "created": item.creation_date.strftime("%Y-%m-%d") if item.creation_date else ""}
                      for item in assets().order_by("-creation_date", "-pk")[:RECENT_COUNT]]}


def labels():
    items = assets()
    counts = {size: items.filter(tags__name=f"label-{size}").count() for size in LABEL_SIZES}
    stuck = sum(bool((metadata or {}).get(STICKER_KEY)) for metadata in items.values_list("metadata", flat=True))
    return {"counts": counts, "untagged": items.count() - sum(counts.values()), "stuck": stuck}


def power_inventory():
    from common.models import Parameter
    from stock.models import StockLocation

    rows = assets().values("pk", "serial", "part__pk", "part__name", "part__category__name", "location_id", "belongs_to_id")
    part_names = {row["part__pk"]: row["part__name"] for row in rows}
    parameters = {}
    for row in Parameter.objects.filter(model_type__model="part", model_id__in=part_names).values("model_id", "template__name", "data"):
        parameters.setdefault(part_names[row["model_id"]], {})[row["template__name"]] = row["data"]
    locations = {row["pk"]: {"name": row["name"], "parent": row["parent_id"], "pathstring": row["pathstring"]}
                 for row in StockLocation.objects.values("pk", "name", "parent_id", "pathstring")}
    inventory_assets = [power.Asset(row["serial"], row["pk"], row["part__name"], row["part__category__name"] or "",
                                    row["location_id"], row["belongs_to_id"]) for row in rows]
    return power.Inventory(inventory_assets, locations, parameters)


MENUS = (
    ("value", "Value", "ti:currency-euro:outline", "renderValueMenu"),
    ("efficiency", "Efficiency", "ti:bolt:outline", "renderEfficiencyMenu"),
    ("attention", "Attention", "ti:alert-triangle:outline", "renderAttentionMenu"),
    ("machines", "Machines", "ti:server:outline", "renderMachinesMenu"),
    ("stickers", "Stickers", "ti:sticker:outline", "renderStickersMenu"),
)


class InventoryDashboardPlugin(SettingsMixin, UserInterfaceMixin, InvenTreePlugin):
    NAME = "InventoryDashboard"
    SLUG = "inventory-dashboard"
    TITLE = "Inventory dashboard"
    DESCRIPTION = "Dashboard widgets for a hardware inventory kept by the inventree-compose catalog tool"
    VERSION = "1.0.0"
    AUTHOR = "intisy"

    SETTINGS = {
        "POWER": {
            "name": "Power settings",
            "description": "Utilisation, reference points and machines as JSON, written by the catalog tool from catalog.toml; edit it there",
            "default": "",
        },
    }

    def power_config(self):
        """None until the catalog tool has written the settings, so nothing is scored on made-up numbers."""
        try:
            return json.loads(self.get_setting("POWER") or "null")
        except ValueError:
            return None

    def widget(self, key, title, description, function, data, width=4, height=3):
        return {"key": key, "title": title, "description": description,
                "source": self.plugin_static_file(f"dashboard.js:{function}"),
                "context": data, "options": {"width": width, "height": height}}

    def get_ui_dashboard_items(self, request, context, **kwargs):
        return [
            self.widget("overview", "Inventory overview", "Asset count and value, by category", "renderOverview", overview()),
            self.widget("attention", "Needs attention", "Untested, faulty and broken assets", "renderAttention", attention()),
            self.widget("machines", "Machines", "Parts installed in each machine, and items per location", "renderMachines", machines()),
            self.widget("recent", "Recently added", "The newest assets", "renderRecent", recent()),
            self.widget("labels", "Labels", "Sticker sizes to print", "renderLabels", labels(), width=3, height=2),
            *self.power_widgets(),
        ]

    def power_widgets(self):
        config = self.power_config()
        if config is None:
            return []
        inventory = power_inventory()
        machines = sorted(power.machine_summaries(inventory, config), key=lambda row: row["name"].split(" ", 1)[-1])
        data = {"machines": [{**row, "parts": []} for row in machines],
                "locations": power.location_summaries(inventory, config)}
        return [self.widget("power", "Power and efficiency", "Watts and score of every machine and location", "renderPower",
                            data, width=8, height=5)]

    def panel(self, key, title, function, data, icon="ti:bolt:outline"):
        return {"key": key, "title": title, "description": title, "icon": icon,
                "source": self.plugin_static_file(f"dashboard.js:{function}"), "context": data}

    def get_ui_navigation_items(self, request, context, **kwargs):
        """The menus open as tabs on the Stock page above every location, since a plugin cannot add a page of
        its own to the app."""
        return [{"key": f"menu-{key}", "title": title, "icon": icon, "options": {"url": f"/stock/location/index/{key}"}}
                for key, title, icon, _ in MENUS]

    def menu_panels(self, inventory, config, pk):
        scope = menus.Scope(inventory, pk)
        data = {"value": lambda: menus.value_menu(scope), "efficiency": lambda: menus.efficiency_menu(scope, config),
                "attention": lambda: menus.attention_menu(scope), "machines": lambda: menus.machines_menu(scope, config),
                "stickers": lambda: menus.sticker_menu(scope)}
        return [self.panel(key, title, function, data[key](), icon) for key, title, icon, function in MENUS]

    def get_ui_panels(self, request, context, **kwargs):
        config = self.power_config()
        target, pk = context.get("target_model"), context.get("target_id")
        if target == "stocklocation" and pk is None:
            return self.menu_panels(power_inventory(), config, None)
        if pk is None:
            return []
        inventory = power_inventory()
        if target == "stocklocation":
            power_panels = self.location_panel(inventory, config, int(pk)) if config else []
            return power_panels + self.menu_panels(inventory, config, int(pk))
        if config is None:
            return []
        if target == "stockitem":
            return self.machine_panel(inventory, config, int(pk))
        if target == "part":
            return self.part_panel(inventory, config, int(pk))
        return []

    def machine_panel(self, inventory, config, pk):
        host = inventory.by_pk.get(pk)
        parts = inventory.installed_in(host) if host else []
        if not parts:
            return []
        found = power.totals([host, *parts], inventory.parameters_of)
        data = power.summary(f"{host.serial} {host.part}", found, config, power.utilisation_of(host.serial, config),
                             power.measured_of(host.serial, config), power.on_share_of(host.serial, config))
        return [self.panel("power", "Power", "renderPowerPanel", data)] if data["average_w"] > 0 else []

    def location_panel(self, inventory, config, pk):
        name = inventory.locations.get(pk, {}).get("name", "")
        powered = power.powered_assets(inventory, config)
        below = [asset for asset in inventory.location_and_below(pk) if asset.pk in powered]
        found = power.totals(below, inventory.parameters_of)
        data = power.summary(name, found, config, power.utilisation_of(name, config), power.measured_of(name, config),
                             power.on_share_of(name, config))
        return [self.panel("power", "Power", "renderPowerPanel", data)] if data["average_w"] > 0 else []

    def part_panel(self, inventory, config, pk):
        from part.models import Part

        part = Part.objects.filter(pk=pk).select_related("category").first()
        if part is None:
            return []
        asset = power.Asset("", 0, part.name, part.category.name if part.category else "", None, None)
        parameters = inventory.parameters_of(part.name)
        score = power.part_score(asset, parameters, config)
        resources = power.part_resource_scores(asset, parameters, config)
        idle, load = power.number(parameters, power.IDLE), power.number(parameters, power.LOAD)
        if score is None and idle is None:
            return []
        data = {"idle_w": idle, "load_w": load, "score": None if resources else score, "resources": resources,
                "utilisation": config["utilisation"], "source": parameters.get("Power source", "")}
        return [self.panel("power", "Power", "renderPartPower", data)]
