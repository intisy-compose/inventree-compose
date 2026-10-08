"""Flows labels and group name tags through a page's areas in rows, like text, and outlines every group.

The input is the group tree depth first, so every group is one contiguous run and a subgroup's run lies inside
its parent's. Rows fill an area left to right; items of one group that are shorter than the row stack in its
column. A group continues into the next area or page when it has to, opened there by a continuation tag. Gaps
grow only by the outlines that run between two neighbours. See docs/specs/2026-10-08-label-flow-layout.md in
the compose org.
"""

import math
from dataclasses import dataclass, field

from .outlines import Rect, flat_path, ring_path, union_outline

TOLERANCE = 1e-6
LABEL_GAP_MM = 1.0
OUTLINE_MARGIN_MM = 0.8
OUTLINE_STEP_MM = 0.8
OUTLINE_CLEARANCE_MM = 1.2
MIN_BRIDGE_MM = 2.0
MAX_RELAYOUTS = 60


@dataclass
class Slot:
    """Where an entry goes: the middle of its bottom edge (y from the top of the page), and the
    direction its top points in, in degrees (90 = up the page)."""
    x: float
    y: float
    angle: float


@dataclass
class FlowItem:
    """An entry in flow order. `chain` is the keys of the groups it sits in, outermost first; `opens` is the
    key of the group whose name tag it is."""
    entry: object
    chain: tuple
    opens: str = None


def growth(depth):
    """How far the outermost of `depth` nested outlines runs from an item."""
    return 0.0 if depth == 0 else OUTLINE_MARGIN_MM + OUTLINE_STEP_MM * (depth - 1)


def shared_depth(first, second):
    depth = 0
    while depth < min(len(first), len(second)) and first[depth] == second[depth]:
        depth += 1
    return depth


def column_gap(first, second):
    """Room between neighbours: 1 mm inside one group, otherwise every outline between them and clearance."""
    if first == second:
        return LABEL_GAP_MM
    shared = shared_depth(first, second)
    return growth(len(first) - shared) + growth(len(second) - shared) + OUTLINE_CLEARANCE_MM


@dataclass
class Column:
    """Items of one group stacked in sub-rows inside one column of a row."""
    x: float
    chain: tuple
    width: float = 0.0
    placed: list = field(default_factory=list)
    row_top: float = 0.0
    row_x: float = 0.0
    row_height: float = 0.0

    def take(self, entry, reach, row_height, room_right):
        """Places the entry beside the last one or in a new sub-row below; False when neither fits."""
        if self.placed and self.row_x + LABEL_GAP_MM + entry.width <= self.width + TOLERANCE \
                and self.row_top + reach <= row_height + TOLERANCE:
            self.placed.append((self.row_x + LABEL_GAP_MM, self.row_top, entry))
            self.row_x += LABEL_GAP_MM + entry.width
            self.row_height = max(self.row_height, reach)
            return True
        top = self.row_top + self.row_height + LABEL_GAP_MM if self.placed else 0.0
        if top + reach > row_height + TOLERANCE or entry.width > max(self.width, room_right) + TOLERANCE:
            return False
        self.placed.append((0.0, top, entry))
        self.width = max(self.width, entry.width)
        self.row_top, self.row_x, self.row_height = top, entry.width, reach
        return True

    @property
    def right(self):
        return self.x + self.width


@dataclass
class Row:
    columns: list
    height: float
    end: int
    top: float = 0.0


@dataclass
class Box:
    """Something in a row that needs room: a group's outline rectangle, or a column of labels. `up` and `down`
    are how far it reaches beyond the row's band."""
    left: float
    right: float
    up: float
    down: float
    group: str = None
    chain: tuple = ()


class Flow:
    """The layout of one print job: the sequence, the groups' chains, the forced row breaks."""

    def __init__(self, sequence, continuation):
        self.sequence = sequence
        self.continuation = continuation
        self.group_chains = {}
        for item in sequence:
            for depth, key in enumerate(item.chain):
                self.group_chains.setdefault(key, item.chain[:depth + 1])

    def related(self, first, second):
        return first == second or first in self.group_chains[second] or second in self.group_chains[first]

    def needs_clearance(self, first, second):
        if first.group and second.group:
            return not self.related(first.group, second.group)
        if first.group:
            return first.group not in second.chain
        if second.group:
            return second.group not in first.chain
        return False

    def row_boxes(self, row):
        boxes = [Box(column.x, column.right, 0.0, 0.0, chain=column.chain) for column in row.columns]
        extents = {}
        for column in row.columns:
            for depth, key in enumerate(column.chain):
                reach = growth(len(column.chain) - depth)
                left, right, vertical = extents.get(key, (math.inf, -math.inf, 0.0))
                extents[key] = (min(left, column.x - reach), max(right, column.right + reach), max(vertical, reach))
        return boxes + [Box(left, right, vertical, vertical, group=key) for key, (left, right, vertical) in extents.items()]

    def row_gap(self, above, below):
        gap = LABEL_GAP_MM
        for upper in self.row_boxes(above):
            for lower in self.row_boxes(below):
                overlapping = upper.left < lower.right + OUTLINE_CLEARANCE_MM and lower.left < upper.right + OUTLINE_CLEARANCE_MM
                if overlapping and self.needs_clearance(upper, lower):
                    gap = max(gap, upper.down + lower.up + OUTLINE_CLEARANCE_MM)
        return gap

    def margin(self, row):
        return max((growth(len(column.chain)) for column in row.columns), default=0.0)

    def build_row(self, area, sequence, start, forced, height_cap):
        """The longest row from `start` within the area's width; items taller than the cap end it."""
        row_height = self.lookahead_height(area, sequence, start, forced, height_cap)
        columns = []
        index = start
        while index < len(sequence):
            item = sequence[index]
            reach = area.reach(item.entry)
            if (index != start and id(item) in forced) or reach > height_cap + TOLERANCE:
                break
            last = columns[-1] if columns else None
            if self.stack(columns, item, reach, row_height, area.width):
                index += 1
                continue
            x = growth(len(item.chain)) if last is None else last.right + column_gap(last.chain, item.chain)
            if x + item.entry.width + growth(len(item.chain)) > area.width + TOLERANCE:
                break
            row_height = max(row_height, reach)
            column = Column(x, item.chain)
            column.take(item.entry, reach, row_height, item.entry.width)
            columns.append(column)
            index += 1
        if not columns:
            return None
        height = max(top + area.reach(entry) for column in columns for _, top, entry in column.placed)
        return Row(columns, height, index)

    @staticmethod
    def stack(columns, item, reach, row_height, area_width):
        """Puts the item into the first column of its own group in this row with room left, such as the space
        under a name tag. Only the last column may widen."""
        own = []
        for column in reversed(columns):
            if column.chain != item.chain:
                break
            own.insert(0, column)
        for column in own:
            room_right = area_width - growth(len(item.chain)) - column.x if column is columns[-1] else column.width
            if column.take(item.entry, reach, row_height, room_right):
                return True
        return False

    def lookahead_height(self, area, sequence, start, forced, height_cap):
        """The tallest item that would share the row if nothing stacked, so stacking knows its room."""
        height, x, chain = 0.0, None, None
        for index in range(start, len(sequence)):
            item = sequence[index]
            reach = area.reach(item.entry)
            if (index != start and id(item) in forced) or reach > height_cap + TOLERANCE:
                break
            x = growth(len(item.chain)) if x is None else x + column_gap(chain, item.chain)
            if x + item.entry.width + growth(len(item.chain)) > area.width + TOLERANCE:
                break
            x += item.entry.width
            chain = item.chain
            height = max(height, reach)
        return height

    def fill_area(self, area, sequence, start, forced):
        """Rows from `start` until the area is full; the rows and where the next area takes over."""
        rows, bottom = [], 0.0
        index = start
        while index < len(sequence):
            cap = area.height
            row = None
            for _ in range(8):
                row = self.build_row(area, sequence, index, forced, cap)
                if row is None:
                    break
                gap = self.row_gap(rows[-1], row) if rows else self.margin(row)
                overflow = bottom + gap + row.height + self.margin(row) - area.height
                if overflow <= TOLERANCE:
                    break
                cap = row.height - overflow
                row = None
                if cap <= 0:
                    break
            if row is None:
                break
            row.top = bottom + gap
            bottom = row.top + row.height
            rows.append(row)
            index = row.end
        return rows, index

    def open_group(self, sequence, index):
        """The innermost group that started before `index` and goes on after it."""
        item = sequence[index]
        chain = item.chain[:-1] if item.opens else item.chain
        started = {each.opens for each in sequence[:index] if each.opens}
        while chain and chain[-1] not in started:
            chain = chain[:-1]
        return chain

    def lay_out(self, make_areas, forced):
        sequence = list(self.sequence)
        pages, index = [], 0
        while index < len(sequence):
            page = PageLayout(make_areas())
            for area in page.areas:
                if index >= len(sequence):
                    break
                chain = self.open_group(sequence, index) if index > 0 else ()
                if chain:
                    sequence.insert(index, FlowItem(self.continuation(chain, area.width - 2 * growth(len(chain))), chain))
                breaks = forced - {id(sequence[index + 1])} if chain and index + 1 < len(sequence) else forced
                rows, next_index = self.fill_area(area, sequence, index, breaks)
                if chain and next_index <= index + 1:
                    del sequence[index]
                    continue
                page.add(area, rows)
                index = next_index
            if not page.filled:
                entry = sequence[index].entry
                raise ValueError(f"{getattr(entry, 'asset_id', '') or entry.name} does not fit on an empty page")
            pages.append(page)
        return pages

    def badly_started_openers(self, pages):
        """The tags of groups that fall apart in an area: their rows on consecutive lines do not touch, or their
        first row holds nothing but the tag. Each then starts on a new row."""
        openers = []
        for page in pages:
            for _, rows in page.filled:
                for key, spans in self.group_spans(rows).items():
                    opener = next((item for item in self.items_in(rows, key) if item.opens == key), None)
                    if opener is None:
                        continue
                    alone = len(spans) > 1 and self.entries_in_row(rows[spans[0][0]], key) == 1
                    apart = any(row_b == row_a + 1 and min(right_a, right_b) - max(left_a, left_b) < MIN_BRIDGE_MM
                                for (row_a, left_a, right_a), (row_b, left_b, right_b) in zip(spans, spans[1:]))
                    if alone or apart:
                        openers.append(opener)
        return openers

    @staticmethod
    def entries_in_row(row, key):
        return sum(len(column.placed) for column in row.columns if key in column.chain)

    def group_spans(self, rows):
        spans = {}
        for row_index, row in enumerate(rows):
            for box in self.row_boxes(row):
                if box.group:
                    spans.setdefault(box.group, []).append((row_index, box.left, box.right))
        return spans

    def items_in(self, rows, key):
        entries = {id(entry) for row in rows for column in row.columns if key in column.chain for _, _, entry in column.placed}
        return [item for item in self.sequence if id(item.entry) in entries]

    def outlines(self, rows):
        """Every group's outline in this area: its row rectangles and the bridges between consecutive rows."""
        pieces = {}
        previous = {}
        for row in rows:
            current = {}
            for box in self.row_boxes(row):
                if not box.group:
                    continue
                rect = Rect(box.left, row.top - box.up, box.right, row.top + row.height + box.down)
                pieces.setdefault(box.group, []).append(rect)
                above = previous.get(box.group)
                if above and above.bottom < rect.top:
                    left, right = max(above.left, rect.left), min(above.right, rect.right)
                    if right > left:
                        pieces[box.group].append(Rect(left, above.bottom, right, rect.top))
                current[box.group] = rect
            previous = current
        return [(key, union_outline(rects)) for key, rects in pieces.items()]


class PageLayout:
    def __init__(self, areas):
        self.areas = areas
        self.filled = []

    def add(self, area, rows):
        if rows:
            self.filled.append((area, rows))


def lay_out(sequence, make_areas, continuation):
    """Pages of (placed entries, outlines): every entry as (slot, entry), every group outline as (group key,
    area, polygons). A group that would fall apart into two pieces on consecutive rows starts on a new row."""
    flow = Flow(sequence, continuation)
    forced = set()
    pages = flow.lay_out(make_areas, forced)
    for _ in range(MAX_RELAYOUTS):
        opener = next((item for item in flow.badly_started_openers(pages) if id(item) not in forced), None)
        if opener is None:
            break
        forced.add(id(opener))
        pages = flow.lay_out(make_areas, forced)
    result = []
    for page in pages:
        placed, outlines = [], []
        for area, rows in page.filled:
            for row in rows:
                for column in row.columns:
                    placed += [(area.slot(column.x + x, row.top + y, entry), entry) for x, y, entry in column.placed]
            outlines += [(key, area, polygons) for key, polygons in flow.outlines(rows)]
        result.append((placed, outlines))
    return result


class FlatArea:
    """A rectangle of the sheet, entries upright, y down the page."""

    def __init__(self, left, top, right, bottom):
        self.left, self.top = left, top
        self.width, self.height = right - left, bottom - top

    def slot(self, x, y, entry):
        return Slot(self.left + x + entry.width / 2, self.top + y + entry.height, 90.0)

    def reach(self, entry):
        return entry.height

    def outline_path(self, polygon, page_height):
        return flat_path([(self.left + x, self.top + y) for x, y in polygon], page_height)


class RingArea:
    """A ring unrolled at its inner radius: x runs clockwise around the ring from the top, y outwards.
    Entries stand radially; spacing them at the inner radius keeps them apart, since they only spread
    further apart outwards."""

    def __init__(self, centre, inner_radius, outer_limit):
        self.centre, self.inner_radius = centre, inner_radius
        self.width = 2 * math.pi * inner_radius - 3 * OUTLINE_CLEARANCE_MM
        self.height = outer_limit - inner_radius

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

    def outline_path(self, polygon, page_height):
        return ring_path([(self.angle_at(x), self.inner_radius + y) for x, y in polygon], self.centre, page_height)
