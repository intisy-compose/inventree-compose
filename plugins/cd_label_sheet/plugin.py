"""A label printer that turns the stock items selected in InvenTree into CD label sheets: the same
layout as `catalog labels`, one PDF to download and print."""

from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError

from rest_framework import serializers

from plugin import InvenTreePlugin
from plugin.mixins import LabelPrintingMixin

from .sheet import LABEL_SIZES_PRINTED, Label, sheets_pdf

SIZE_FROM_TAG = "tag"
LABEL_TAG = "label-"


def tagged_size(item):
    sizes = [name[len(LABEL_TAG):] for name in item.tags.names() if name.startswith(LABEL_TAG)]
    return sizes[0] if len(sizes) == 1 else "standard"


def site_url(request):
    """Printing runs in the background worker without a request, so the configured site URL comes first."""
    from django.conf import settings

    configured = getattr(settings, "SITE_URL", None)
    return (configured or request.build_absolute_uri("/")).rstrip("/")


class CdLabelSheetPlugin(LabelPrintingMixin, InvenTreePlugin):
    NAME = "CdLabelSheet"
    SLUG = "cd-label-sheet"
    TITLE = "CD label sheet"
    DESCRIPTION = "Prints asset labels onto A4 CD label sheets, every size on its own sheets"
    VERSION = "1.0.0"
    AUTHOR = "intisy"

    class PrintingOptionsSerializer(serializers.Serializer):
        size = serializers.ChoiceField(
            choices=[(SIZE_FROM_TAG, "Each asset's own size"), *[(size, size.capitalize()) for size in LABEL_SIZES_PRINTED]],
            default=SIZE_FROM_TAG, label="Label size",
            help_text="Assets whose own size is none are skipped unless a size is chosen here")
        outline = serializers.BooleanField(default=False, label="Draw the ring edges",
                                           help_text="For a test print on plain paper")

    def labels_for(self, items, request, size_override):
        labels = []
        for item in items:
            if not getattr(item, "serial", None):
                continue
            size = size_override if size_override != SIZE_FROM_TAG else tagged_size(item)
            if size != "none":
                labels.append(Label(item.serial, item.part.name, f"{site_url(request)}/web/stock/item/{item.pk}", size))
        return sorted(labels, key=lambda label: label.asset_id)

    def print_labels(self, label, output, items, request, **kwargs):
        options = kwargs.get("printing_options") or {}
        labels = self.labels_for(items, request, options.get("size", SIZE_FROM_TAG))
        if not labels:
            raise ValidationError("None of the selected items gets a label: they need a serial number and a size other than none")
        pdf, _ = sheets_pdf(labels, bool(options.get("outline")))
        output.mark_complete(progress=len(items), output=ContentFile(pdf, "cd-labels.pdf"))
