"""Lays asset labels out on A4 sticker sheets, to be cut apart after printing. On a CD label sheet
nothing goes to waste: labels sit radially around each ring, upright inside each centre disc and
upright on the sheet around the rings. On a full sticker sheet they sit on a grid. Every size gets
its own sheets."""

import math
import zlib
from dataclasses import dataclass, field

from .outlines import Placed, group_levels, label_corners, outline_mask

PAGE_SIZE_MM = (210, 297)
# Calibrated for the human partner's printer, paper pushed against the tray guide: see RULES.md in compose/docs.
PRINT_SCALE = 0.975
RING_CENTRES_MM = ((105.4, 72.1), (105.4, 224.3))
RING_OUTER_RADIUS_MM = 58.0 / PRINT_SCALE
RING_HOLE_RADIUS_MM = 20.32 / PRINT_SCALE
RING_SAFETY_MM = 2.0
SHEET_MARGIN_MM = 8.0
SHEET_TYPES = {"cd": "CD label sheet", "full": "Full sticker sheet"}
LABEL_GAP_MM = 1.0
PADDING_MM = 0.6
QR_QUIET_MODULES = 2
PRINT_ORDER = ("large", "standard", "small")
LABEL_SIZES_PRINTED = PRINT_ORDER

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
    """`groups` is where the item is, outermost first: (key, name) pairs of its locations and of the items
    it is installed in. A label without an asset ID is a group's name tag in a spare slot."""
    asset_id: str
    name: str
    url: str
    size: str
    groups: tuple = field(default_factory=tuple)


def text_width(text, size_mm, widths):
    return sum(widths.get(char, 556) for char in text) / 1000 * size_mm


@dataclass
class Slot:
    """Where a label goes: the middle of its bottom edge (y from the top of the page), and the
    direction its top points in, in degrees (90 = up the page)."""
    x: float
    y: float
    angle: float


def ring_slots(size, centre):
    """Radially placed labels in as many circles as fit between the hole and the edge. They only spread
    apart outwards, so neighbours are spaced by their inner corners and the next circle starts
    beyond the outer corners."""
    radius = RING_HOLE_RADIUS_MM + RING_SAFETY_MM
    limit = RING_OUTER_RADIUS_MM - RING_SAFETY_MM
    slots = []
    while math.hypot(radius + size.height, size.width / 2) <= limit:
        pitch = 2 * math.degrees(math.atan((size.width + LABEL_GAP_MM) / 2 / radius))
        count = int(360 // pitch)
        for index in range(count):
            angle = 90 - index * 360 / count
            slots.append(Slot(centre[0] + math.cos(math.radians(angle)) * radius,
                              centre[1] - math.sin(math.radians(angle)) * radius, angle))
        radius = math.hypot(radius + size.height, size.width / 2) + LABEL_GAP_MM
    return slots


def grid(size, left, top, right, bottom):
    """Upright label rectangles (left, top, right, bottom) on a regular grid inside a box, centred."""
    step_x, step_y = size.width + LABEL_GAP_MM, size.height + LABEL_GAP_MM
    columns = int((right - left + LABEL_GAP_MM) // step_x)
    rows = int((bottom - top + LABEL_GAP_MM) // step_y)
    start_x = left + (right - left - (columns * step_x - LABEL_GAP_MM)) / 2
    start_y = top + (bottom - top - (rows * step_y - LABEL_GAP_MM)) / 2
    return [(start_x + column * step_x, start_y + row * step_y, start_x + column * step_x + size.width,
             start_y + row * step_y + size.height) for row in range(rows) for column in range(columns)]


def distance_to_rectangle(point, rectangle):
    left, top, right, bottom = rectangle
    dx = max(left - point[0], 0, point[0] - right)
    dy = max(top - point[1], 0, point[1] - bottom)
    return math.hypot(dx, dy)


def farthest_corner(point, rectangle):
    left, top, right, bottom = rectangle
    return max(math.hypot(x - point[0], y - point[1]) for x in (left, right) for y in (top, bottom))


def upright(rectangle):
    left, _, right, bottom = rectangle
    return Slot((left + right) / 2, bottom, 90)


def disc_slots(size, centre):
    limit = RING_HOLE_RADIUS_MM - RING_SAFETY_MM
    box = (centre[0] - limit, centre[1] - limit, centre[0] + limit, centre[1] + limit)
    return [upright(rectangle) for rectangle in grid(size, *box) if farthest_corner(centre, rectangle) <= limit]


def outside_slots(size):
    box = (SHEET_MARGIN_MM, SHEET_MARGIN_MM, PAGE_SIZE_MM[0] - SHEET_MARGIN_MM, PAGE_SIZE_MM[1] - SHEET_MARGIN_MM)
    clearance = RING_OUTER_RADIUS_MM + RING_SAFETY_MM
    return [upright(rectangle) for rectangle in grid(size, *box)
            if all(distance_to_rectangle(centre, rectangle) >= clearance for centre in RING_CENTRES_MM)]


def cd_sheet_slots(size):
    slots = []
    for centre in RING_CENTRES_MM:
        slots += ring_slots(size, centre) + disc_slots(size, centre)
    return slots + outside_slots(size)


def full_sheet_slots(size):
    box = (SHEET_MARGIN_MM, SHEET_MARGIN_MM, PAGE_SIZE_MM[0] - SHEET_MARGIN_MM, PAGE_SIZE_MM[1] - SHEET_MARGIN_MM)
    return [upright(rectangle) for rectangle in grid(size, *box)]


def page_slots(size, sheet):
    return cd_sheet_slots(size) if sheet == "cd" else full_sheet_slots(size)


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
    if not label.asset_id:
        return name_tag_drawing(label)
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


def name_tag_drawing(label):
    """A group's name in a spare slot, as large as fits on up to three lines."""
    size = SIZES[label.size]
    available = size.width - 2 * PADDING_MM
    for text_size in (2.4, 2.0, 1.7, 1.4):
        max_lines = max(1, int((size.height - 2 * PADDING_MM) // (text_size * 1.15)))
        lines = wrap(label.name, text_size, available, min(max_lines, 3))
        if not lines[-1].endswith("..."):
            break
    block = len(lines) * text_size * 1.15
    baseline = (size.height + block) / 2 - text_size
    operators = []
    for line in lines:
        operators.append(text_operator("F2", text_size, -text_width(line, text_size, HELVETICA) / 2, baseline, line))
        baseline -= text_size * 1.15
    return "\n".join(operators)


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


def sheet_content(placed, outline, with_mask=False):
    """One page: every (slot, drawing), with y flipped so slots read from the top-left. The outline
    draws the CD rings, for a test print against a sheet; the mask is the group outlines' image."""
    points_per_mm = 72 / 25.4
    operators = [f"{points_per_mm:.6f} 0 0 {points_per_mm:.6f} 0 0 cm"]
    if with_mask:
        operators.append(f"q 0 g {PAGE_SIZE_MM[0]} 0 0 {PAGE_SIZE_MM[1]} 0 0 cm /Outlines Do Q")
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
    """A minimal PDF: Helvetica and Helvetica-Bold, one uncompressed content stream per page, and per page
    an optional 1-bit image mask (the group outlines). `pages` holds (content, mask or None)."""
    width, height = (size * 72 / 25.4 for size in PAGE_SIZE_MM)
    page_ids = [5 + 3 * index for index in range(len(pages))]
    objects = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] /Count {len(pages)} >>",
        3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        4: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }
    for page_id, (content, mask) in zip(page_ids, pages):
        images = f"/XObject << /Outlines {page_id + 2} 0 R >> " if mask is not None else ""
        objects[page_id] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] "
                            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> {images}>> /Contents {page_id + 1} 0 R >>")
        objects[page_id + 1] = stream("", content.encode("latin-1"))
        if mask is not None:
            objects[page_id + 2] = stream(f"/Type /XObject /Subtype /Image /Width {mask.width} /Height {mask.height} "
                                          "/ImageMask true /BitsPerComponent 1 /Decode [1 0] /Filter /FlateDecode ",
                                          zlib.compress(mask.tobytes(), 9))
    output = b"%PDF-1.4\n"
    offsets = {}
    for object_id in sorted(objects):
        offsets[object_id] = len(output)
        body = objects[object_id]
        output += f"{object_id} 0 obj\n".encode("latin-1") + (body if isinstance(body, bytes) else body.encode("latin-1")) + b"\nendobj\n"
    xref = len(output)
    output += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
    output += "".join(f"{offsets[object_id]:010d} 00000 n \n" for object_id in sorted(objects)).encode("latin-1")
    output += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1")
    return output


def stream(dictionary, data):
    return f"<< {dictionary}/Length {len(data)} >>\nstream\n".encode("latin-1") + data + b"\nendstream"


def by_group(labels):
    return sorted(labels, key=lambda label: ([name for _, name in label.groups], label.asset_id))


def with_name_tags(batch, spare):
    """Spends a page's spare slots on group names, each at the start of its group, innermost groups first."""
    placed = [Placed([], label.groups) for label in batch]
    levels, members = group_levels(placed)
    chosen = sorted(levels, key=lambda group: (levels[group], min(members[group])))[:spare]
    first_of = {}
    for group in chosen:
        first_of.setdefault(min(members[group]), []).append(group)
    result = []
    for index, label in enumerate(batch):
        for group in sorted(first_of.get(index, []), key=lambda group: -levels[group]):
            chain = label.groups[:label.groups.index(group) + 1]
            result.append(Label("", group[1], "", label.size, chain))
        result.append(label)
    return result


def page_batches(labels, capacity, grouped):
    """Full pages first; only the last page has spare slots, and with groups on they carry the names."""
    batches = [labels[first:first + capacity] for first in range(0, len(labels), capacity)]
    if grouped and batches and len(batches[-1]) < capacity:
        batches[-1] = with_name_tags(batches[-1], capacity - len(batches[-1]))
    return batches


def walking_order(slots, size):
    """The slots as a walk from the top-left, always on to the nearest free one, so labels that follow each
    other sit next to each other and a group's labels stay together."""
    centres = [centre_of(slot, size) for slot in slots]
    remaining = set(range(len(slots)))
    current = min(remaining, key=lambda index: centres[index][0] + centres[index][1])
    order = []
    while remaining:
        remaining.discard(current)
        order.append(slots[current])
        if remaining:
            here = centres[current]
            current = min(remaining, key=lambda index: math.hypot(centres[index][0] - here[0], centres[index][1] - here[1]))
    return order


def centre_of(slot, size):
    angle = math.radians(slot.angle)
    return slot.x + math.cos(angle) * size.height / 2, slot.y - math.sin(angle) * size.height / 2


def size_pages(labels, size, outline, sheet, grouped=False):
    label_size = SIZES[size]
    slots = page_slots(label_size, sheet)
    if grouped:
        slots = walking_order(slots, label_size)
    pages = []
    for batch in page_batches(by_group(labels) if grouped else labels, len(slots), grouped):
        mask = None
        if grouped:
            placed = [Placed(label_corners(slot, label_size.width, label_size.height), label.groups)
                      for slot, label in zip(slots, batch)]
            mask = outline_mask(placed, PAGE_SIZE_MM)
        drawings = [(slot, label_drawing(label)) for slot, label in zip(slots, batch)]
        pages.append((sheet_content(drawings, outline, mask is not None), mask))
    return pages, len(slots)


def sheets_pdf(labels, outline, sheet="cd", grouped=False):
    """The whole print job as PDF bytes, and one summary line per size. `grouped` orders the labels by
    where they are and outlines each group."""
    pages, lines = [], []
    for size in PRINT_ORDER:
        sized = [label for label in labels if label.size == size]
        if not sized:
            continue
        size_pages_list, per_sheet = size_pages(sized, size, outline and sheet == "cd", sheet, grouped)
        pages += size_pages_list
        lines.append(f"  {size}: {len(sized)} labels on {len(size_pages_list)} sheet(s), {per_sheet} per sheet")
    return (pdf_document(pages) if pages else None), lines
