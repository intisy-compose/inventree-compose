"""Prints asset labels onto A4 CD label sheets: labels placed radially around each ring, cut apart
after printing. Every size gets its own sheets; `none` items are only listed."""

import math
import os
from dataclasses import dataclass

PAGE_SIZE_MM = (210, 297)
# Measured on a test print against a real sheet: the rings sit 5 mm left of the page centre.
RING_CENTRES_MM = ((100, 72), (100, 225))
RING_OUTER_RADIUS_MM = 58.5
RING_HOLE_RADIUS_MM = 20.5
RING_SAFETY_MM = 2.5
LABEL_GAP_MM = 1.0
PADDING_MM = 0.6
QR_QUIET_MODULES = 2
PRINT_ORDER = ("large", "standard", "small")

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
    asset_id: str
    name: str
    url: str
    size: str


def text_width(text, size_mm, widths):
    return sum(widths.get(char, 556) for char in text) / 1000 * size_mm


def ring_slots(size):
    """(inner radius, angle) per label, in as many circles as fit between the hole and the edge.

    Radially placed labels only spread apart outwards, so neighbours are spaced by their inner corners
    and the next circle starts beyond the outer corners."""
    radius = RING_HOLE_RADIUS_MM + RING_SAFETY_MM
    limit = RING_OUTER_RADIUS_MM - RING_SAFETY_MM
    slots = []
    while math.hypot(radius + size.height, size.width / 2) <= limit:
        pitch = 2 * math.degrees(math.atan((size.width + LABEL_GAP_MM) / 2 / radius))
        count = int(360 // pitch)
        slots += [(radius, 90 - index * 360 / count) for index in range(count)]
        radius = math.hypot(radius + size.height, size.width / 2) + LABEL_GAP_MM
    return slots


def qr_modules(url):
    import segno
    return segno.make(url, error="l", boost_error=False).matrix


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


def sheet_content(placed, outline):
    """One page: every (ring centre, slot, drawing), with y flipped so centres read from the top-left."""
    points_per_mm = 72 / 25.4
    operators = [f"{points_per_mm:.6f} 0 0 {points_per_mm:.6f} 0 0 cm"]
    if outline:
        operators.append("0.2 w 0 G [1 1] 0 d")
        for centre_x, centre_y in RING_CENTRES_MM:
            for radius in (RING_OUTER_RADIUS_MM, RING_HOLE_RADIUS_MM):
                operators.append(circle_path(centre_x, PAGE_SIZE_MM[1] - centre_y, radius))
        operators.append("[] 0 d")
    for (centre_x, centre_y), (radius, angle), drawing in placed:
        cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        origin_x = centre_x + cos * radius
        origin_y = PAGE_SIZE_MM[1] - centre_y + sin * radius
        operators.append(f"q {sin:.6f} {-cos:.6f} {cos:.6f} {sin:.6f} {origin_x:.3f} {origin_y:.3f} cm\n{drawing}\nQ")
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


def size_pages(labels, size, outline):
    slots = [(centre, slot) for centre in RING_CENTRES_MM for slot in ring_slots(SIZES[size])]
    pages = []
    for first in range(0, len(labels), len(slots)):
        batch = labels[first:first + len(slots)]
        placed = [(centre, slot, label_drawing(label)) for (centre, slot), label in zip(slots, batch)]
        pages.append(sheet_content(placed, outline))
    return pages, len(slots)


def write_sheets(labels, output, outline):
    pages, lines = [], []
    for size in PRINT_ORDER:
        sized = [label for label in labels if label.size == size]
        if not sized:
            continue
        size_pages_list, per_sheet = size_pages(sized, size, outline)
        pages += size_pages_list
        lines.append(f"  {size}: {len(sized)} labels on {len(size_pages_list)} sheet(s), {per_sheet} per sheet")
    if not pages:
        return lines
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "wb") as handle:
        handle.write(pdf_document(pages))
    return [f"+ {output}; print at actual size"] + lines
