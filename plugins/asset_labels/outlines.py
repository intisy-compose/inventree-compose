"""Group outlines: the edge of a union of rectangles, traced into polygons and drawn as PDF paths, with
rounded corners on the flat sheet and as ring segments on a CD ring. Coordinates come in mm from the
top-left of the page and go out in PDF space, y up."""

import math
from dataclasses import dataclass

CORNER_RADIUS_MM = 0.8
KAPPA = 0.5523
LOCATION_LINE_WIDTH_MM = 0.35
MACHINE_LINE_WIDTH_MM = 0.2


@dataclass(frozen=True)
class Rect:
    left: float
    top: float
    right: float
    bottom: float


def union_outline(rects):
    """The boundary loops of the union, each a list of corners. The rectangles' own edges make a grid of
    cells; the edges between a covered and an uncovered cell, walked around each covered cell in one
    direction, chain into closed loops."""
    rects = [Rect(*(round(value, 4) for value in (rect.left, rect.top, rect.right, rect.bottom))) for rect in rects]
    xs = sorted({value for rect in rects for value in (rect.left, rect.right)})
    ys = sorted({value for rect in rects for value in (rect.top, rect.bottom)})

    def covered(column, row):
        if not (0 <= column < len(xs) - 1 and 0 <= row < len(ys) - 1):
            return False
        x, y = (xs[column] + xs[column + 1]) / 2, (ys[row] + ys[row + 1]) / 2
        return any(rect.left < x < rect.right and rect.top < y < rect.bottom for rect in rects)

    grid = {(column, row) for column in range(len(xs) - 1) for row in range(len(ys) - 1) if covered(column, row)}
    edges = {}
    for column, row in grid:
        top_left, top_right = (column, row), (column + 1, row)
        bottom_left, bottom_right = (column, row + 1), (column + 1, row + 1)
        for neighbour, start, end in (((column, row - 1), top_left, top_right), ((column + 1, row), top_right, bottom_right),
                                      ((column, row + 1), bottom_right, bottom_left), ((column - 1, row), bottom_left, top_left)):
            if neighbour not in grid:
                edges.setdefault(start, []).append(end)
    loops = []
    while edges:
        start = next(iter(edges))
        loop, point = [start], start
        while True:
            following = edges[point].pop()
            if not edges[point]:
                del edges[point]
            if following == start:
                break
            loop.append(following)
            point = following
        loops.append([(xs[column], ys[row]) for column, row in without_straight_points(loop)])
    return loops


def without_straight_points(loop):
    """Corners only; a loop through a pinch point visits it twice in a row, which collapses too."""
    loop = [point for index, point in enumerate(loop) if point != loop[index - 1]]
    corners = []
    for index, point in enumerate(loop):
        before, after = loop[index - 1], loop[(index + 1) % len(loop)]
        if not (before[0] == point[0] == after[0] or before[1] == point[1] == after[1]):
            corners.append(point)
    return corners


def flat_path(corners, page_height):
    """A closed polygon with every corner rounded, the radius shrinking on short edges."""
    def pdf(point):
        return f"{point[0]:.3f} {page_height - point[1]:.3f}"

    def toward(point, target, distance):
        length = math.dist(point, target)
        return (point[0] + (target[0] - point[0]) * distance / length, point[1] + (target[1] - point[1]) * distance / length)

    parts = []
    for index, corner in enumerate(corners):
        before, after = corners[index - 1], corners[(index + 1) % len(corners)]
        radius = min(CORNER_RADIUS_MM, math.dist(before, corner) / 2, math.dist(corner, after) / 2)
        entry, leave = toward(corner, before, radius), toward(corner, after, radius)
        first, second = toward(entry, corner, radius * KAPPA), toward(leave, corner, radius * KAPPA)
        parts.append(f"{pdf(entry)} {'m' if index == 0 else 'l'} {pdf(first)} {pdf(second)} {pdf(leave)} c")
    return " ".join(parts) + " h S"


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


def ring_path(corners, centre, page_height):
    """A polygon given as (angle, radius) corners: edges at one radius are arcs, edges at one angle radial lines."""
    def point(angle, radius):
        return (centre[0] + radius * math.cos(math.radians(angle)), page_height - centre[1] + radius * math.sin(math.radians(angle)))

    first = point(*corners[0])
    parts = [f"{first[0]:.3f} {first[1]:.3f} m"]
    for index, (angle, radius) in enumerate(corners):
        next_angle, next_radius = corners[(index + 1) % len(corners)]
        if math.isclose(radius, next_radius):
            parts.append(arc(centre, radius, angle, next_angle, page_height))
        else:
            end = point(next_angle, next_radius)
            parts.append(f"{end[0]:.3f} {end[1]:.3f} l")
    return " ".join(parts) + " h S"


def outline_operators(outlines, page_height):
    """`outlines` are (group key, area, loops); locations get the heavier line."""
    operators = []
    for key, area, loops in outlines:
        width = LOCATION_LINE_WIDTH_MM if key.startswith("location-") else MACHINE_LINE_WIDTH_MM
        operators.append(f"{width} w " + " ".join(area.outline_path(loop, page_height) for loop in loops))
    return ["q 0 G 1 j"] + operators + ["Q"] if operators else []
