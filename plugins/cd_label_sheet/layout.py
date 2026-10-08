"""Packs labels and group name tags of mixed sizes into nested blocks, and the blocks into a page's areas.

A group (a location or a machine) is a block: its name tag, its labels and its subgroups' blocks packed
inside a padding its outline runs in. Blocks fill the page's areas in order; an area is a rectangle on the
sheet, or a ring bent into one, x running around the ring and y outwards. Packing is a skyline: each item
drops to the lowest free spot, then the leftmost, so small labels fill in beside large ones. A block too big
for any area is split into its children and keeps only its name tag. See
docs/specs/2026-10-08-label-group-outlines.md in the compose org.
"""

import math
from dataclasses import dataclass, field

TOLERANCE = 1e-6

LABEL_GAP_MM = 1.0
BLOCK_GAP_MM = 3.0
BLOCK_PADDING_MM = 1.2


@dataclass
class Slot:
    """Where an entry goes: the middle of its bottom edge (y from the top of the page), and the
    direction its top points in, in degrees (90 = up the page)."""
    x: float
    y: float
    angle: float


@dataclass
class Group:
    key: str
    name: str
    contents: tuple
    tag: object = None
    labels: list = field(default_factory=list)
    children: list = field(default_factory=list)


@dataclass
class Block:
    """A laid-out group: its size, every entry at (x, y) from its top-left, and the outline rectangles
    (its own and its subgroups') in the same frame."""
    width: float
    height: float
    entries: list
    outlines: list


def spacing(first_is_block, second_is_block):
    return BLOCK_GAP_MM if first_is_block or second_is_block else LABEL_GAP_MM


@dataclass
class Box:
    left: float
    top: float
    right: float
    bottom: float
    is_block: bool


class Packer:
    """Skyline packing inside a width and an optional height: each item takes the lowest, then leftmost,
    spot where it keeps its spacing to everything placed before."""

    def __init__(self, width, height=math.inf):
        self.width, self.height = width, height
        self.boxes = []

    def take(self, item, height=None):
        """`height` is how far the item reaches; on a ring that is more than the item's own height."""
        height = item.height if height is None else height
        if item.width > self.width + TOLERANCE or height > self.height + TOLERANCE:
            return None
        is_block = isinstance(item, Block)
        best = None
        for x in sorted({0.0} | {box.right + spacing(box.is_block, is_block) for box in self.boxes}):
            if x + item.width > self.width + TOLERANCE:
                continue
            y = 0.0
            for box in self.boxes:
                room = spacing(box.is_block, is_block)
                if box.left < x + item.width + room and box.right + room > x:
                    y = max(y, box.bottom + room)
            if y + height <= self.height + TOLERANCE and (best is None or (y, x) < best):
                best = (y, x)
        if best is None:
            return None
        y, x = best
        self.boxes.append(Box(x, y, x + item.width, y + height, is_block))
        return x, y

    def extent(self):
        return max((box.right for box in self.boxes), default=0.0), max((box.bottom for box in self.boxes), default=0.0)


WIDTH_FRACTIONS = (1.0, 0.75, 0.6, 0.5, 0.4, 0.33, 0.25)


def upright_reach(item):
    return item.height


def lay_out_group(group, max_width, max_height=math.inf, cache=None, reach=upright_reach):
    """The group at the width, out of a few up to `max_width`, that leaves it the most square while it stays
    within `max_height`: square blocks sit side by side and nest, where the smallest area gave tall columns
    that no longer fit their parent."""
    shapes = group_shapes(group, max_width, max_height, cache, reach)
    return shapes[0] if shapes else None


def group_shapes(group, max_width, max_height=math.inf, cache=None, reach=upright_reach):
    """Every shape the group can take within the width and height, the most square first."""
    cache = {} if cache is None else cache
    key = (id(group), round(max_width, 2))
    if key not in cache:
        cache[key] = [block for block in (pack_group(group, max_width * fraction, cache, reach) for fraction in WIDTH_FRACTIONS)
                      if block is not None]
    fitting = [block for block in cache[key] if block.height <= max_height + TOLERANCE]
    return sorted(fitting, key=lambda block: (max(block.width, block.height), block.width * block.height))


def pack_group(group, max_width, cache, reach):
    inner = max_width - 2 * BLOCK_PADDING_MM
    children = [lay_out_group(child, inner, cache=cache, reach=reach) for child in group.children]
    if any(child is None for child in children):
        return None
    items = ([group.tag] if group.tag else []) + group.labels + children
    packer = Packer(inner)
    positions = [packer.take(item, item.height if isinstance(item, Block) else reach(item)) for item in items]
    if any(position is None for position in positions):
        return None
    width, height = packer.extent()
    entries, outlines = [], []
    for item, (x, y) in zip(items, positions):
        x, y = x + BLOCK_PADDING_MM, y + BLOCK_PADDING_MM
        if isinstance(item, Block):
            entries += [(x + inner_x, y + inner_y, entry) for inner_x, inner_y, entry in item.entries]
            outlines += [(x + left, y + top, x + right, y + bottom) for left, top, right, bottom in item.outlines]
        else:
            entries.append((x, y, item))
    width, height = width + 2 * BLOCK_PADDING_MM, height + 2 * BLOCK_PADDING_MM
    return Block(width, height, entries, outlines + [(0.0, 0.0, width, height)])


class FlatArea(Packer):
    """A rectangle of the sheet, entries upright."""

    def __init__(self, left, top, right, bottom):
        super().__init__(right - left, bottom - top)
        self.left, self.top = left, top

    def slot(self, x, y, entry):
        return Slot(self.left + x + entry.width / 2, self.top + y + entry.height, 90.0)

    def reach(self, entry):
        return entry.height

    def outline(self, left, top, right, bottom):
        return ("rectangle", (self.left + left, self.top + top, self.left + right, self.top + bottom))


class RingArea(Packer):
    """A ring unrolled at its inner radius: x runs clockwise around the ring from the top, y outwards.
    Entries stand radially; spacing them at the inner radius keeps them apart, since they only spread
    further apart outwards."""

    def __init__(self, centre, inner_radius, outer_limit):
        super().__init__(2 * math.pi * inner_radius - BLOCK_GAP_MM, outer_limit - inner_radius)
        self.centre, self.inner_radius = centre, inner_radius

    def reach(self, entry):
        """How far out a radial entry reaches at the inner radius, its outer corners included: wider entries
        bulge further, so rows packed by this never collide."""
        return math.hypot(self.inner_radius + entry.height, entry.width / 2) - self.inner_radius

    def angle_at(self, x):
        return 90.0 - math.degrees(x / self.inner_radius)

    def slot(self, x, y, entry):
        angle = self.angle_at(x + entry.width / 2)
        radius = self.inner_radius + y
        return Slot(self.centre[0] + math.cos(math.radians(angle)) * radius,
                    self.centre[1] - math.sin(math.radians(angle)) * radius, angle)

    def outline(self, left, top, right, bottom):
        return ("sector", (self.centre, self.inner_radius + top, self.inner_radius + bottom, self.angle_at(left), self.angle_at(right)))


class Page:
    def __init__(self, areas):
        self.areas = areas
        self.placed = []
        self.outlines = []
        self.caches = [{} for _ in areas]

    def put(self, item):
        """Places a label, tag or group in the first area it fits, a group in the first of its shapes that
        fits there; False when it fits nowhere on this page."""
        for area, cache in zip(self.areas, self.caches):
            shapes = group_shapes(item, area.width, area.height, cache, area.reach) if isinstance(item, Group) else [item]
            for shape in shapes:
                spot = area.take(shape, shape.height if isinstance(shape, Block) else area.reach(shape))
                if spot is None:
                    continue
                x, y = spot
                if isinstance(shape, Block):
                    self.placed += [(area.slot(x + inner_x, y + inner_y, entry), entry) for inner_x, inner_y, entry in shape.entries]
                    self.outlines += [area.outline(x + left, y + top, x + right, y + bottom) for left, top, right, bottom in shape.outlines]
                else:
                    self.placed.append((area.slot(x, y, shape), shape))
                return True
        return False

    def could_hold(self, group):
        return any(group_shapes(group, area.width, area.height, cache, area.reach) for area, cache in zip(self.areas, self.caches))


def size_of(item):
    if isinstance(item, Group):
        return sum(size_of(part) for part in ([item.tag] if item.tag else []) + item.labels + item.children)
    return item.width * item.height


def lay_out(roots, make_areas):
    """Pages of (placed entries, outlines). `roots` are the top-level labels and groups in order. Each goes
    on the first page with room, so a block that does not fit leaves its space to the smaller ones after it.
    A group no empty page can hold is split: its name tag and its own labels stay one block, then its
    subgroups follow, the biggest first."""
    pages = []

    def place(item):
        for page in pages:
            if page.put(item):
                return
        if isinstance(item, Group) and item.children and not Page(make_areas()).could_hold(item):
            own = Group(item.key, item.name, item.contents, item.tag, item.labels, [])
            for part in [own] + sorted(item.children, key=size_of, reverse=True):
                place(part)
            return
        if isinstance(item, Group) and not item.children and len(item.labels) > 1 and not Page(make_areas()).could_hold(item):
            half = len(item.labels) // 2
            for labels in (item.labels[:half], item.labels[half:]):
                place(Group(item.key, item.name, item.contents, item.tag, labels, []))
            return
        pages.append(Page(make_areas()))
        if not pages[-1].put(item):
            raise ValueError(f"{getattr(item, 'asset_id', '') or item.name} does not fit on an empty page")

    for root in roots:
        place(root)
    return [(page.placed, page.outlines) for page in pages if page.placed]
