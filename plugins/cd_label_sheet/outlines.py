"""Outlines around the labels of each group (a machine and its parts, a location), drawn in the cutting
gaps, nested. See docs/specs/2026-10-08-label-group-outlines.md in the compose org.

Drawn as a raster mask with PIL, which the InvenTree container has, so any slot geometry works without a
geometry library.
"""

import math
from dataclasses import dataclass

PIXELS_PER_MM = 20
LEVEL_OFFSETS_MM = (0.15, 0.30, 0.45)
LINE_WIDTH_MM = 0.12
BRIDGE_REACH_MM = 10.0
MAX_LEVELS = len(LEVEL_OFFSETS_MM)


@dataclass
class Placed:
    """A label on the page: its corners (mm, y down) and the groups it belongs to, outermost first."""
    corners: list
    groups: tuple


def label_corners(slot, width, height):
    """A slot is the middle of the label's bottom edge and the direction its top points in."""
    angle = math.radians(slot.angle)
    up = (math.cos(angle), -math.sin(angle))
    right = (math.sin(angle), math.cos(angle))
    return [(slot.x + across * right[0] + outward * up[0], slot.y + across * right[1] + outward * up[1])
            for across, outward in ((-width / 2, 0), (width / 2, 0), (width / 2, height), (-width / 2, height))]


def convex_hull(points):
    points = sorted(set(points))
    if len(points) < 3:
        return points

    def cross(origin, a, b):
        return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])

    lower, upper = [], []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def axes(polygon):
    return [(polygon[index][1] - polygon[index - 1][1], polygon[index - 1][0] - polygon[index][0]) for index in range(len(polygon))]


def overlaps(first, second, margin=0.0):
    """Separating axis test for convex polygons; `margin` shrinks the overlap so touching does not count."""
    for axis in axes(first) + axes(second):
        length = math.hypot(*axis) or 1.0
        unit = (axis[0] / length, axis[1] / length)
        first_span = [point[0] * unit[0] + point[1] * unit[1] for point in first]
        second_span = [point[0] * unit[0] + point[1] * unit[1] for point in second]
        if max(first_span) - margin <= min(second_span) or max(second_span) - margin <= min(first_span):
            return False
    return True


def centre(polygon):
    return (sum(point[0] for point in polygon) / len(polygon), sum(point[1] for point in polygon) / len(polygon))


def radius(polygon):
    middle = centre(polygon)
    return max(math.hypot(point[0] - middle[0], point[1] - middle[1]) for point in polygon)


def near(first, second, reach):
    distance = math.hypot(centre(first)[0] - centre(second)[0], centre(first)[1] - centre(second)[1])
    return distance <= radius(first) + radius(second) + reach


def gap_between(first, second):
    """The smallest distance between two convex polygons that do not overlap, from vertex to edge."""
    return min(distance_to_polygon(point, polygon) for points, polygon in ((first, second), (second, first)) for point in points)


def point_to_segment(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = dx * dx + dy * dy or 1.0
    t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length))
    return math.hypot(point[0] - start[0] - t * dx, point[1] - start[1] - t * dy)


def distance_to_polygon(point, polygon):
    return min(point_to_segment(point, polygon[index - 1], polygon[index]) for index in range(len(polygon)))


def facing_side(polygon, other):
    """The side of a label that faces another: the edge pointing most directly at the other's centre. On a
    rectangle the direction from its centre to an edge's middle is that edge's outward normal."""
    own, target = centre(polygon), centre(other)
    towards = (target[0] - own[0], target[1] - own[1])
    edges = [(polygon[index - 1], polygon[index]) for index in range(len(polygon))]

    def facing(edge):
        middle = ((edge[0][0] + edge[1][0]) / 2 - own[0], (edge[0][1] + edge[1][1]) / 2 - own[1])
        return (middle[0] * towards[0] + middle[1] * towards[1]) / (math.hypot(*middle) or 1.0)

    return max(edges, key=facing)


def bridges(members, everything):
    """The strip between the facing sides of two labels of a group that sit close together, wherever it
    touches no other label, so the outline runs around the group instead of around every label. Between
    radial labels on a ring the strip is the widening wedge."""
    found = []
    member_ids = {id(polygon) for polygon in members}
    strangers = [other for other in everything if id(other) not in member_ids]
    for index, first in enumerate(members):
        for second in members[index + 1:]:
            if not near(first, second, BRIDGE_REACH_MM) or gap_between(first, second) > BRIDGE_REACH_MM:
                continue
            hull = convex_hull(list(facing_side(first, second)) + list(facing_side(second, first)))
            if not any(overlaps(hull, other, margin=0.05) for other in strangers if near(hull, other, 0)):
                found.append(hull)
    return found


def group_levels(placed):
    """Each drawn group's nesting level: 0 for one with no drawn group inside it, else one more than the
    highest inside. A group holding every label on the page is left out; so is anything above level 2."""
    every = len(placed)
    members = {}
    for index, label in enumerate(placed):
        for group in label.groups:
            members.setdefault(group, set()).add(index)
    drawn = {group for group, indexes in members.items() if len(indexes) < every}
    children = {group: set() for group in drawn}
    for label in placed:
        chain = [group for group in label.groups if group in drawn]
        for outer, inner in zip(chain, chain[1:]):
            children[outer].add(inner)
    levels = {}

    def level(group):
        if group not in levels:
            levels[group] = 1 + max((level(child) for child in children[group]), default=-1)
        return levels[group]

    return {group: level(group) for group in drawn if level(group) < MAX_LEVELS}, members


def outline_mask(placed, page_size_mm):
    """A 1-bit page image, white where an outline goes."""
    from PIL import Image, ImageChops

    width, height = (round(size * PIXELS_PER_MM) for size in page_size_mm)
    mask = Image.new("1", (width, height), 0)
    levels, members = group_levels(placed)
    everything = [label.corners for label in placed]
    for group, level in levels.items():
        polygons = [placed[index].corners for index in sorted(members[group])]
        region = polygons + bridges(polygons, everything)
        offset = LEVEL_OFFSETS_MM[level]
        ring = grown(region, offset, (width, height))
        ring_inside = grown(region, offset - LINE_WIDTH_MM, (width, height))
        mask = ImageChops.logical_or(mask, ImageChops.logical_xor(ring, ring_inside))
    return mask


def grown(polygons, distance_mm, size):
    """The union of convex polygons grown by a distance: each one filled, its edges drawn that thick and its
    corners rounded, which is the exact Minkowski sum with a disc."""
    from PIL import Image, ImageDraw

    image = Image.new("1", size, 0)
    draw = ImageDraw.Draw(image)
    reach = distance_mm * PIXELS_PER_MM
    for polygon in polygons:
        pixels = [(x * PIXELS_PER_MM, y * PIXELS_PER_MM) for x, y in polygon]
        draw.polygon(pixels, fill=1)
        if reach <= 0:
            continue
        for index in range(len(pixels)):
            draw.line([pixels[index - 1], pixels[index]], fill=1, width=max(1, round(2 * reach)))
        for x, y in pixels:
            draw.ellipse([x - reach, y - reach, x + reach, y + reach], fill=1)
    return image
