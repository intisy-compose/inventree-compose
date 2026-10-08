"""Dashboard widgets for a personal hardware inventory kept by the catalog tool: assets are serialized
stock items, conditions are stock statuses, label sizes are `label-*` tags."""

from django.db.models import Count, Q, Sum

from plugin import InvenTreePlugin
from plugin.mixins import UserInterfaceMixin

CONDITIONS = {11: "Untested", 50: "Needs repair", 55: "Broken"}
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


def condition_of(item):
    return CONDITIONS.get(item.status_custom_key) or CONDITIONS.get(item.status)


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
    return {"counts": counts, "untagged": items.count() - sum(counts.values())}


class InventoryDashboardPlugin(UserInterfaceMixin, InvenTreePlugin):
    NAME = "InventoryDashboard"
    SLUG = "inventory-dashboard"
    TITLE = "Inventory dashboard"
    DESCRIPTION = "Dashboard widgets for a hardware inventory kept by the inventree-compose catalog tool"
    VERSION = "1.0.0"
    AUTHOR = "intisy"

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
        ]
