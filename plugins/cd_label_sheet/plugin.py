"""A label printer that turns the stock items selected in InvenTree into A4 sticker sheets, CD label
sheets or full sticker sheets: one PDF to download and print."""

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
    it is installed in, then the item itself when parts are installed in it (a machine's own label)."""
    hosts = []
    host = item.belongs_to
    while host is not None:
        hosts.insert(0, host)
        host = host.belongs_to
    outermost = hosts[0] if hosts else item
    locations = list(outermost.location.get_ancestors(include_self=True)) if outermost.location else []
    if item.installed_parts.exists():
        hosts.append(item)
    return tuple([(f"location-{location.pk}", location.name) for location in locations] +
                 [(f"item-{host.pk}", f"{host.serial} {host.part.name}") for host in hosts])


def site_url(request):
    """Printing runs in the background worker without a request, so the configured site URL comes first."""
    from django.conf import settings

    configured = getattr(settings, "SITE_URL", None)
    return (configured or request.build_absolute_uri("/")).rstrip("/")


class CdLabelSheetPlugin(LabelPrintingMixin, InvenTreePlugin):
    NAME = "CdLabelSheet"
    SLUG = "cd-label-sheet"
    TITLE = "Label sheets"
    DESCRIPTION = "Prints asset labels onto A4 CD label sheets or full sticker sheets, every size on its own sheets"
    VERSION = "1.0.0"
    AUTHOR = "intisy"

    class PrintingOptionsSerializer(serializers.Serializer):
        sheet = serializers.ChoiceField(choices=list(SHEET_TYPES.items()), default="cd", label="Sticker paper")
        size = serializers.ChoiceField(
            choices=[(SIZE_FROM_TAG, "Each asset's own size"), *[(size, size.capitalize()) for size in LABEL_SIZES_PRINTED]],
            default=SIZE_FROM_TAG, label="Label size",
            help_text="Assets whose own size is none are skipped unless a size is chosen here")
        outline = serializers.BooleanField(default=False, label="Draw the ring edges",
                                           help_text="CD label sheets only: for a test print against a sheet")
        groups = serializers.BooleanField(default=False, label="Outline groups",
                                          help_text="Order the labels by where they are and outline each machine and location in the gaps")

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
        labels = self.labels_for(items, request, options.get("size", SIZE_FROM_TAG))
        if not labels:
            raise ValidationError("None of the selected items gets a label: they need a serial number and a size other than none")
        pdf, _ = sheets_pdf(labels, bool(options.get("outline")), options.get("sheet", "cd"), bool(options.get("groups")))
        output.mark_complete(progress=len(items), output=ContentFile(pdf, "cd-labels.pdf"))
