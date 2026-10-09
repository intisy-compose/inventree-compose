"""A label printer that turns the stock items selected in InvenTree into A4 sticker sheets, full sticker
sheets or CD label sheets: one PDF to download and print."""

from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError

from rest_framework import serializers

from plugin import InvenTreePlugin
from plugin.mixins import LabelPrintingMixin

from .sheet import LABEL_SIZES_PRINTED, SHEET_TYPES, Label, sheets_pdf

SIZE_FROM_TAG = "tag"
LABEL_TAG = "label-"


def tagged_size(item):
    sizes = [name[len(LABEL_TAG):] for name in item.tags.names() if name.startswith(LABEL_TAG)]
    return sizes[0] if len(sizes) == 1 else "standard"


def group_chain(item):
    """Where the item is, outermost first: the locations of the outermost item it sits in, then every item
    it is installed in, then the item itself when parts are installed in it (a machine's own label). Each
    is (key, name, the IDs installed directly in it)."""
    hosts = []
    host = item.belongs_to
    while host is not None:
        hosts.insert(0, host)
        host = host.belongs_to
    outermost = hosts[0] if hosts else item
    locations = list(outermost.location.get_ancestors(include_self=True)) if outermost.location else []
    if item.installed_parts.exists():
        hosts.append(item)
    return tuple([(f"location-{location.pk}", location.name, ()) for location in locations] +
                 [(f"item-{host.pk}", f"{host.serial} {host.part.name}", installed_ids(host)) for host in hosts])


def installed_ids(host):
    return tuple(sorted(part.serial for part in host.installed_parts.all() if part.serial))


def with_installed(items):
    """The selected items and everything installed in them, all the way down, each once."""
    seen, result = set(), []
    for item in items:
        for each in [item, *item.get_installed_items(cascade=True)]:
            if each.pk not in seen:
                seen.add(each.pk)
                result.append(each)
    return result


def site_url(request):
    """Printing runs in the background worker without a request, so the configured site URL comes first."""
    from django.conf import settings

    configured = getattr(settings, "SITE_URL", None)
    return (configured or request.build_absolute_uri("/")).rstrip("/")


class AssetLabelsPlugin(LabelPrintingMixin, InvenTreePlugin):
    NAME = "AssetLabels"
    SLUG = "asset-labels"
    TITLE = "Asset labels"
    DESCRIPTION = "Prints asset labels onto A4 full sticker sheets or CD label sheets, grouped by where each item is"
    VERSION = "1.0.0"
    AUTHOR = "intisy"

    class PrintingOptionsSerializer(serializers.Serializer):
        sheet = serializers.ChoiceField(choices=list(SHEET_TYPES.items()), default="full", label="Sticker paper")
        size = serializers.ChoiceField(
            choices=[(SIZE_FROM_TAG, "Each asset's own size"), *[(size, size.capitalize()) for size in LABEL_SIZES_PRINTED]],
            default=SIZE_FROM_TAG, label="Label size",
            help_text="Assets whose own size is none are skipped unless a size is chosen here")
        outline = serializers.BooleanField(default=False, label="Draw the ring edges",
                                           help_text="CD label sheets only: for a test print against a sheet")
        groups = serializers.BooleanField(default=False, label="Outline groups",
                                          help_text="Outline every location and machine, opened by a name tag; groups go on across pages")
        touching = serializers.BooleanField(default=False, label="Labels touch",
                                            help_text="Labels of one group sit edge to edge and share their cut lines, so fewer cuts")
        installed = serializers.BooleanField(default=False, label="Include installed items",
                                             help_text="Also print everything installed in the selected items")

    def labels_for(self, items, request, size_override):
        labels = []
        for item in items:
            if not getattr(item, "serial", None):
                continue
            size = size_override if size_override != SIZE_FROM_TAG else tagged_size(item)
            if size != "none":
                labels.append(Label(item.serial, item.part.name, f"{site_url(request)}/web/stock/item/{item.pk}", size, group_chain(item)))
        return sorted(labels, key=lambda label: label.asset_id)

    def print_labels(self, label, output, items, request, **kwargs):
        options = kwargs.get("printing_options") or {}
        if options.get("installed"):
            items = with_installed(items)
        labels = self.labels_for(items, request, options.get("size", SIZE_FROM_TAG))
        if not labels:
            raise ValidationError("None of the selected items gets a label: they need a serial number and a size other than none")
        pdf, _ = sheets_pdf(labels, bool(options.get("outline")), options.get("sheet", "full"), bool(options.get("groups")),
                            bool(options.get("touching")))
        output.mark_complete(progress=len(items), output=ContentFile(pdf, "asset-labels.pdf"))
