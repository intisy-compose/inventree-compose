"""Lays asset labels and group name tags out on A4 sticker sheets, to be cut apart after printing. Sizes
mix on one page. On a full sticker sheet labels fill the page; on a CD label sheet they sit radially around
each ring, upright inside each centre disc and upright on the sheet around the rings. With groups on, labels
follow where their items are, each group opens with its name tag, and nested outlines run around every
group, across pages when a group continues."""

import math
from dataclasses import dataclass, field

from .layout import FlatArea, FlowItem, RingArea, lay_out
from .outlines import outline_operators

PAGE_SIZE_MM = (210, 297)
# Calibrated for the human partner's printer, paper pushed against the tray guide: see RULES.md in compose/docs.
PRINT_SCALE = 0.975
RING_CENTRES_MM = ((105.4, 72.1), (105.4, 224.3))
RING_OUTER_RADIUS_MM = 58.0 / PRINT_SCALE
RING_HOLE_RADIUS_MM = 20.32 / PRINT_SCALE
RING_SAFETY_MM = 2.0
SHEET_MARGIN_MM = 8.0
SHEET_TYPES = {"full": "Full sticker sheet", "cd": "CD label sheet"}
PADDING_MM = 0.6
QR_QUIET_MODULES = 2
LABEL_SIZES_PRINTED = ("large", "standard", "small")
SIZE_RANK = {size: rank for rank, size in enumerate(LABEL_SIZES_PRINTED)}
TAG_NAME_TEXT_MM = 2.2
TAG_CONTENT_TEXT_MM = 1.6
TAG_MIN_WIDTH_MM = 12.0
TAG_MAX_WIDTH_MM = {"full": 60.0, "cd": 33.0}
CONTINUED = " (continued)"
BOLD_WIDENING = 1.07

HELVETICA_BOLD = {"S": 667, "A": 722, "M": 833, "-": 333, **{digit: 556 for digit in "0123456789"}}
HELVETICA = dict(zip(
    " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~",
    [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 +
    [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722,
     778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500,
     556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500,
     500, 500, 334, 260, 334, 584]))


@dataclass
class LabelSize:
    width: float
    height: float
    id_text: float
    name_text: float
    with_qr: bool


SIZES = {
    "large": LabelSize(22, 28, 2.8, 1.7, True),
    "standard": LabelSize(13, 15, 2.6, 0, True),
    "small": LabelSize(13.5, 4.5, 2.5, 0, False),
}


@dataclass
class Label:
    """An asset's label. `groups` is where the item is, outermost first: (key, name, contents) for each of
    its locations and of the items it is installed in; contents are the IDs installed directly in an item."""
    asset_id: str
    name: str
    url: str
    size: str
    groups: tuple = field(default_factory=tuple)

    @property
    def width(self):
        return SIZES[self.size].width

    @property
    def height(self):
        return SIZES[self.size].height


@dataclass
class Group:
    key: str
    name: str
    contents: tuple
    tag: object = None
    labels: list = field(default_factory=list)
    children: list = field(default_factory=list)


@dataclass
class NameTag:
    """A group's name at the start of its labels, and for a machine every ID installed directly in it."""
    name: str
    contents: tuple
    max_width: float
    name_lines: list = field(init=False)
    content_lines: list = field(init=False)
    width: float = field(init=False)
    height: float = field(init=False)

    def __post_init__(self):
        room = self.max_width - 2 * PADDING_MM
        self.name_lines = wrap(self.name, TAG_NAME_TEXT_MM * BOLD_WIDENING, room, 4)
        self.content_lines = wrap(" ".join(self.contents), TAG_CONTENT_TEXT_MM, room, 50) if self.contents else []
        widest = max([bold_width(line, TAG_NAME_TEXT_MM) for line in self.name_lines] +
                     [text_width(line, TAG_CONTENT_TEXT_MM, HELVETICA) for line in self.content_lines])
        self.width = min(self.max_width, max(TAG_MIN_WIDTH_MM, widest + 2 * PADDING_MM))
        self.height = (2 * PADDING_MM + len(self.name_lines) * TAG_NAME_TEXT_MM * 1.15
                       + (0.3 + len(self.content_lines) * TAG_CONTENT_TEXT_MM * 1.2 if self.content_lines else 0))


def text_width(text, size_mm, widths):
    return sum(widths.get(char, 556) for char in text) / 1000 * size_mm


def bold_width(text, size_mm):
    return text_width(text, size_mm, HELVETICA) * BOLD_WIDENING


def qr_modules(url):
    import qrcode

    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=0)
    code.add_data(url)
    code.make(fit=True)
    return code.get_matrix()


def dark_runs(row):
    runs, start = [], None
    for index, dark in enumerate(list(row) + [0]):
        if dark and start is None:
            start = index
        elif not dark and start is not None:
            runs.append((start, index - start))
            start = None
    return runs


def wrap(text, size_mm, max_width, max_lines):
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if text_width(candidate, size_mm, HELVETICA) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and text_width(lines[-1] + "...", size_mm, HELVETICA) > max_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "..."
    return lines


def pdf_text(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace").decode("latin-1")


def text_operator(font, size_mm, x, y, text):
    return f"BT /{font} {size_mm} Tf {x:.3f} {y:.3f} Td ({pdf_text(text)}) Tj ET"


def label_drawing(label):
    """PDF operators for one label in its own frame: x across, y outwards from the ring centre, in mm."""
    size = SIZES[label.size]
    operators = [f"0.1 w 0.6 G {-size.width / 2:.3f} 0 {size.width:.3f} {size.height:.3f} re S", "0 g"]
    baseline = PADDING_MM + 0.2
    if size.name_text:
        for line in reversed(wrap(label.name, size.name_text, size.width - 2 * PADDING_MM, 2)):
            operators.append(text_operator("F2", size.name_text, -text_width(line, size.name_text, HELVETICA) / 2, baseline, line))
            baseline += size.name_text * 1.1
        baseline += 0.3
    id_width = text_width(label.asset_id, size.id_text, HELVETICA_BOLD)
    operators.append(text_operator("F1", size.id_text, -id_width / 2, baseline, label.asset_id))
    if size.with_qr:
        operators += qr_operators(label.url, size, baseline + 0.75 * size.id_text + 0.4)
    return "\n".join(operators)


def tag_drawing(tag):
    """A group's name tag: a light grey card with the name, and for a machine what is installed in it."""
    operators = [f"0.9 g {-tag.width / 2:.3f} 0 {tag.width:.3f} {tag.height:.3f} re f", "0 g"]
    baseline = tag.height - PADDING_MM - TAG_NAME_TEXT_MM * 0.8
    for line in tag.name_lines:
        operators.append(text_operator("F1", TAG_NAME_TEXT_MM, -bold_width(line, TAG_NAME_TEXT_MM) / 2, baseline, line))
        baseline -= TAG_NAME_TEXT_MM * 1.15
    baseline -= 0.3
    for line in tag.content_lines:
        operators.append(text_operator("F2", TAG_CONTENT_TEXT_MM, -text_width(line, TAG_CONTENT_TEXT_MM, HELVETICA) / 2, baseline, line))
        baseline -= TAG_CONTENT_TEXT_MM * 1.2
    return "\n".join(operators)


def entry_drawing(entry):
    return tag_drawing(entry) if isinstance(entry, NameTag) else label_drawing(entry)


def qr_operators(url, size, bottom):
    modules = qr_modules(url)
    side = min(size.width - 2 * PADDING_MM, size.height - bottom - PADDING_MM)
    module = side / (len(modules) + 2 * QR_QUIET_MODULES)
    left = -side / 2 + QR_QUIET_MODULES * module
    top = bottom + side - QR_QUIET_MODULES * module
    operators = []
    for row_index, row in enumerate(modules):
        y = top - (row_index + 1) * module
        for start, length in dark_runs(row):
            operators.append(f"{left + start * module:.3f} {y:.3f} {length * module:.3f} {module:.3f} re")
    return operators + ["f"]


def circle_path(x, y, radius):
    k = 0.5523 * radius
    return (f"{x + radius:.3f} {y:.3f} m {x + radius:.3f} {y + k:.3f} {x + k:.3f} {y + radius:.3f} {x:.3f} {y + radius:.3f} c "
            f"{x - k:.3f} {y + radius:.3f} {x - radius:.3f} {y + k:.3f} {x - radius:.3f} {y:.3f} c "
            f"{x - radius:.3f} {y - k:.3f} {x - k:.3f} {y - radius:.3f} {x:.3f} {y - radius:.3f} c "
            f"{x + k:.3f} {y - radius:.3f} {x + radius:.3f} {y - k:.3f} {x + radius:.3f} {y:.3f} c S")


def sheet_content(placed, outline, group_outlines=()):
    """One page: every (slot, drawing), with y flipped so slots read from the top-left. The outline
    draws the CD rings, for a test print against a sheet; the group outlines run around each group."""
    points_per_mm = 72 / 25.4
    operators = [f"{points_per_mm:.6f} 0 0 {points_per_mm:.6f} 0 0 cm"] + outline_operators(group_outlines, PAGE_SIZE_MM[1])
    if outline:
        operators.append("0.2 w 0 G [1 1] 0 d")
        for centre_x, centre_y in RING_CENTRES_MM:
            for radius in (RING_OUTER_RADIUS_MM, RING_HOLE_RADIUS_MM):
                operators.append(circle_path(centre_x, PAGE_SIZE_MM[1] - centre_y, radius))
        operators.append("[] 0 d")
    for slot, drawing in placed:
        cos, sin = math.cos(math.radians(slot.angle)), math.sin(math.radians(slot.angle))
        operators.append(f"q {sin:.6f} {-cos:.6f} {cos:.6f} {sin:.6f} {slot.x:.3f} {PAGE_SIZE_MM[1] - slot.y:.3f} cm\n{drawing}\nQ")
    return "\n".join(operators)


def pdf_document(pages):
    """A minimal PDF: Helvetica and Helvetica-Bold, one uncompressed content stream per page."""
    width, height = (size * 72 / 25.4 for size in PAGE_SIZE_MM)
    page_ids = [5 + 2 * index for index in range(len(pages))]
    objects = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] /Count {len(pages)} >>",
        3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        4: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }
    for page_id, content in zip(page_ids, pages):
        objects[page_id] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] "
                            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {page_id + 1} 0 R >>")
        objects[page_id + 1] = f"<< /Length {len(content.encode('latin-1'))} >>\nstream\n{content}\nendstream"
    output = b"%PDF-1.4\n"
    offsets = {}
    for object_id in sorted(objects):
        offsets[object_id] = len(output)
        output += f"{object_id} 0 obj\n{objects[object_id]}\nendobj\n".encode("latin-1")
    xref = len(output)
    output += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
    output += "".join(f"{offsets[object_id]:010d} 00000 n \n" for object_id in sorted(objects)).encode("latin-1")
    output += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1")
    return output


def label_order(label):
    return SIZE_RANK[label.size], label.asset_id


def group_tree(labels, tag_width):
    """Every location and every item with parts in it is a group that opens with its name tag; labels sit in
    their innermost group, largest first."""
    root = Group("", "", ())
    for label in labels:
        node = root
        for depth, (key, name, contents) in enumerate(label.groups):
            child = next((group for group in node.children if group.key == key), None)
            if child is None:
                child = Group(key, name, contents, NameTag(name, contents, tag_width))
                node.children.append(child)
            node = child
        node.labels.append(label)

    def order(group):
        group.labels.sort(key=label_order)
        group.children.sort(key=lambda child: child.name)
        for child in group.children:
            order(child)

    order(root)
    return root


def flow_sequence(labels, grouped, tag_width):
    """The labels and name tags in flow order: the group tree depth first, each group its name tag, its own
    labels, then its subgroups."""
    if not grouped:
        return [FlowItem(Label(label.asset_id, label.name, label.url, label.size), ())
                for label in sorted(labels, key=label_order)]

    def walk(group, chain):
        items = [FlowItem(group.tag, chain, group.key)] + [FlowItem(label, chain) for label in group.labels]
        for child in group.children:
            items += walk(child, chain + (child.key,))
        return items

    root = group_tree(labels, tag_width)
    sequence = [FlowItem(label, ()) for label in root.labels]
    for child in root.children:
        sequence += walk(child, (child.key,))
    return sequence


def continuation_maker(sequence, tag_width):
    """Name tags for a group that goes on in a new area: the whole path, so one tag says which outline is which."""
    names = {item.opens: item.entry.name for item in sequence if item.opens}

    def continuation(chain, max_width):
        return NameTag(" > ".join(names[key] for key in chain) + CONTINUED, (), min(tag_width, max_width))

    return continuation


def cd_areas():
    """Both rings and their centre discs, then the sheet beside and between the rings; everything 2 mm
    from a cut edge. The corners of the sheet around the rings stay empty."""
    inner = RING_HOLE_RADIUS_MM + RING_SAFETY_MM
    outer = RING_OUTER_RADIUS_MM - RING_SAFETY_MM
    disc = RING_HOLE_RADIUS_MM - RING_SAFETY_MM
    disc_half_width, disc_half_height = 0.6 * disc, 0.77 * disc
    areas = []
    for centre_x, centre_y in RING_CENTRES_MM:
        areas.append(RingArea((centre_x, centre_y), inner, outer))
        areas.append(FlatArea(centre_x - disc_half_width, centre_y - disc_half_height, centre_x + disc_half_width, centre_y + disc_half_height))
    clear = RING_OUTER_RADIUS_MM + RING_SAFETY_MM
    left, top, right, bottom = sheet_box()
    ring_left = min(x for x, _ in RING_CENTRES_MM) - clear
    ring_right = max(x for x, _ in RING_CENTRES_MM) + clear
    band_top = RING_CENTRES_MM[0][1] + clear
    band_bottom = RING_CENTRES_MM[1][1] - clear
    return areas + [FlatArea(left, top, ring_left, bottom), FlatArea(ring_left, band_top, ring_right, band_bottom),
                    FlatArea(ring_right, top, right, bottom)]


def sheet_box():
    return SHEET_MARGIN_MM, SHEET_MARGIN_MM, PAGE_SIZE_MM[0] - SHEET_MARGIN_MM, PAGE_SIZE_MM[1] - SHEET_MARGIN_MM


def sheets_pdf(labels, outline, sheet="full", grouped=False):
    """The whole print job as PDF bytes, and a summary line. `grouped` outlines every location and machine,
    opened by its name tag."""
    sequence = flow_sequence(labels, grouped, TAG_MAX_WIDTH_MM[sheet])
    pages = lay_out(sequence, cd_areas if sheet == "cd" else lambda: [FlatArea(*sheet_box())],
                    continuation_maker(sequence, TAG_MAX_WIDTH_MM[sheet]))
    contents = [sheet_content([(slot, entry_drawing(entry)) for slot, entry in placed], outline and sheet == "cd", outlines)
                for placed, outlines in pages]
    tags = sum(isinstance(entry, NameTag) for placed, _ in pages for _, entry in placed)
    line = f"  {len(labels)} labels and {tags} name tags on {len(pages)} sheet(s)"
    return (pdf_document(contents) if contents else None), [line]
