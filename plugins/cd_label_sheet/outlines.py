"""PDF paths for group outlines: a rounded rectangle on the flat sheet, a ring segment on a CD ring. Every
coordinate comes in mm from the top-left of the page and goes out in PDF space, y up."""

import math

LINE_WIDTH_MM = 0.2
CORNER_RADIUS_MM = 0.8
KAPPA = 0.5523


def label_corners(slot, width, height):
    """A slot is the middle of the label's bottom edge and the direction its top points in."""
    angle = math.radians(slot.angle)
    up = (math.cos(angle), -math.sin(angle))
    right = (math.sin(angle), math.cos(angle))
    return [(slot.x + across * right[0] + outward * up[0], slot.y + across * right[1] + outward * up[1])
            for across, outward in ((-width / 2, 0), (width / 2, 0), (width / 2, height), (-width / 2, height))]


def rectangle_path(box, page_height):
    left, top, right, bottom = box
    y_low, y_high = page_height - bottom, page_height - top
    r = min(CORNER_RADIUS_MM, (right - left) / 2, (bottom - top) / 2)
    k = KAPPA * r
    return (f"{left + r:.3f} {y_low:.3f} m {right - r:.3f} {y_low:.3f} l "
            f"{right - r + k:.3f} {y_low:.3f} {right:.3f} {y_low + r - k:.3f} {right:.3f} {y_low + r:.3f} c "
            f"{right:.3f} {y_high - r:.3f} l "
            f"{right:.3f} {y_high - r + k:.3f} {right - r + k:.3f} {y_high:.3f} {right - r:.3f} {y_high:.3f} c "
            f"{left + r:.3f} {y_high:.3f} l "
            f"{left + r - k:.3f} {y_high:.3f} {left:.3f} {y_high - r + k:.3f} {left:.3f} {y_high - r:.3f} c "
            f"{left:.3f} {y_low + r:.3f} l "
            f"{left:.3f} {y_low + r - k:.3f} {left + r - k:.3f} {y_low:.3f} {left + r:.3f} {y_low:.3f} c S")


def arc(centre, radius, start, end, page_height):
    """Bezier segments from angle `start` to `end` (degrees, counter-clockwise positive), at most 45 each."""
    steps = max(1, math.ceil(abs(end - start) / 45))
    sweep = math.radians((end - start) / steps)
    handle = 4 / 3 * math.tan(sweep / 4) * radius
    parts = []
    for step in range(steps):
        a0 = math.radians(start) + step * sweep
        a1 = a0 + sweep
        x0, y0 = centre[0] + radius * math.cos(a0), page_height - centre[1] + radius * math.sin(a0)
        x1, y1 = centre[0] + radius * math.cos(a1), page_height - centre[1] + radius * math.sin(a1)
        parts.append(f"{x0 - handle * math.sin(a0):.3f} {y0 + handle * math.cos(a0):.3f} "
                     f"{x1 + handle * math.sin(a1):.3f} {y1 - handle * math.cos(a1):.3f} {x1:.3f} {y1:.3f} c")
    return " ".join(parts)


def sector_path(shape, page_height):
    centre, inner, outer, start, end = shape

    def point(radius, angle):
        return (centre[0] + radius * math.cos(math.radians(angle)), page_height - centre[1] + radius * math.sin(math.radians(angle)))

    begin, corner = point(inner, start), point(outer, end)
    return (f"{begin[0]:.3f} {begin[1]:.3f} m {arc(centre, inner, start, end, page_height)} "
            f"{corner[0]:.3f} {corner[1]:.3f} l {arc(centre, outer, end, start, page_height)} h S")


def outline_operators(outlines, page_height):
    paths = [rectangle_path(shape, page_height) if kind == "rectangle" else sector_path(shape, page_height)
             for kind, shape in outlines]
    return [f"q {LINE_WIDTH_MM} w 0 G"] + paths + ["Q"] if paths else []
