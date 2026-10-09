"""Power draw and efficiency of parts, machines and locations, from part parameters alone.

Pure Python without Django, so it can be checked outside the server. The definitions are in
`docs/specs/2026-10-08-power-efficiency.md` and `docs/specs/2026-10-09-resource-efficiency.md` of the
compose org; the numbers (utilisation, reference points, profile weights, which locations are groups)
come from the `[power]` table of the catalog, never from here.
"""

import math
from dataclasses import dataclass, field

IDLE = "Idle power (W)"
LOAD = "Load power (W)"
WATTAGE = "Wattage (W)"
NO_LOAD = "No-load power (W)"
EFFICIENCY_POINTS = ((0.1, "Efficiency at 10% (%)"), (0.2, "Efficiency at 20% (%)"),
                     (0.5, "Efficiency at 50% (%)"), (1.0, "Efficiency at 100% (%)"))
CPU_MARK = "CPU Mark"
G3D_MARK = "G3D Mark"
VRAM = "VRAM (GB)"
CAPACITY = "Capacity (GB)"
RAM = "RAM (GB)"
RAM_SPEED = "Speed (MT/s)"
SEQUENTIAL_READ = "Sequential read (MB/s)"
LINK_SPEED = "Link speed (MB/s)"
ENCLOSURE_CATEGORY = "Drive enclosures"
ENCLOSURE_PROFILE = "enclosure"
SUPPLY_CATEGORY = "Power supplies"
DRIVE_CATEGORY = "Storage drives"
MEMORY_CATEGORY = "Memory"
COMPUTER_CATEGORY = "Computers"
SPEED_RESOURCES = ("cpu", "ram_speed", "storage_speed", "gpu")
HARD_DRIVE = ("Storage medium", "HDD")
TERABYTES = "TB"


@dataclass
class Asset:
    serial: str
    pk: int
    part: str
    category: str
    location: int | None
    belongs_to: int | None


@dataclass
class Totals:
    """Watts drawn at the wall: parts plus the conversion loss of the supplies that feed them."""
    idle_w: float = 0.0
    load_w: float = 0.0
    loss_idle_w: float = 0.0
    loss_load_w: float = 0.0
    cpu_mark: float = 0.0
    terabytes: float = 0.0
    ram_gb: float = 0.0
    ram_speed: float | None = None
    storage_speed: float = 0.0
    gpu: float = 0.0
    vram: float = 0.0
    parts: list = field(default_factory=list)

    def resource(self, name):
        """A machine's figure per resource: sums for what adds up, the best part for speeds, the slowest
        module for RAM speed because the bus runs at it."""
        return {"cpu": self.cpu_mark, "ram_size": self.ram_gb, "ram_speed": self.ram_speed or 0.0,
                "storage_tb": self.terabytes, "storage_speed": self.storage_speed, "gpu": self.gpu, "vram": self.vram}[name]

    def add_figures(self, asset, parameters, link_speed=None):
        """`link_speed` is what the enclosure the part sits in can carry: a drive reads no faster than that."""
        if asset.category == MEMORY_CATEGORY:
            self.ram_gb += number(parameters, CAPACITY) or 0.0
        self.ram_gb += number(parameters, RAM) or 0.0
        speed = number(parameters, RAM_SPEED)
        if speed and asset.category in (MEMORY_CATEGORY, COMPUTER_CATEGORY):
            self.ram_speed = min(self.ram_speed or speed, speed)
        read = number(parameters, SEQUENTIAL_READ) or 0.0
        self.storage_speed = max(self.storage_speed, min(read, link_speed) if link_speed else read)
        self.gpu = max(self.gpu, number(parameters, G3D_MARK) or 0.0)
        self.vram = max(self.vram, number(parameters, VRAM) or 0.0)
        self.cpu_mark += number(parameters, CPU_MARK) or 0.0
        if asset.category == DRIVE_CATEGORY:
            self.terabytes += (number(parameters, CAPACITY) or 0.0) / 1000

    @property
    def wall_idle_w(self):
        return self.idle_w + self.loss_idle_w

    @property
    def wall_load_w(self):
        return self.load_w + self.loss_load_w

    def average_w(self, utilisation):
        return average_power(self.wall_idle_w, self.wall_load_w, utilisation)


def average_power(idle_w, load_w, utilisation):
    return idle_w + utilisation * (load_w - idle_w)


def log_score(efficiency, reference):
    """1 to 100 on a log scale between two fixed reference efficiencies: every doubling of efficiency is
    the same step, and nothing bought later moves an existing score."""
    if efficiency <= 0:
        return 1
    low, high = reference["low"], reference["high"]
    position = math.log(efficiency / low) / math.log(high / low)
    return round(min(100, max(1, 1 + 99 * position)))


def number(parameters, name):
    try:
        return float(parameters.get(name))
    except (TypeError, ValueError):
        return None


def is_hard_drive(asset, parameters):
    return asset.category == DRIVE_CATEGORY and parameters.get(HARD_DRIVE[0]) == HARD_DRIVE[1]


def figure_of(asset, parameters, power_class):
    if power_class["figure"] == TERABYTES:
        capacity = number(parameters, CAPACITY)
        return capacity / 1000 if capacity and is_hard_drive(asset, parameters) else None
    return number(parameters, power_class["figure"])


def class_of(asset, parameters, config):
    """The first class whose figure the part has, so a part is scored by what it is for."""
    for power_class in config["classes"]:
        figure = figure_of(asset, parameters, power_class)
        if figure:
            return power_class, figure
    return None, None


def part_score(asset, parameters, config):
    """A single part is scored at full use: its figure over its load watts."""
    load = number(parameters, LOAD)
    power_class, figure = class_of(asset, parameters, config)
    if power_class is None or not load:
        return None
    efficiency = figure / load
    return {"class": power_class["name"], "figure": figure, "unit": power_class["figure"],
            "efficiency": efficiency, "score": log_score(efficiency, power_class)}


def supply_efficiency(parameters, fraction):
    """Interpolated between the published points; below the first point the first one holds."""
    points = [(at, number(parameters, name)) for at, name in EFFICIENCY_POINTS]
    points = [(at, value / 100) for at, value in points if value]
    if not points:
        return None
    if fraction <= points[0][0]:
        return points[0][1]
    for (low_at, low_value), (high_at, high_value) in zip(points, points[1:]):
        if fraction <= high_at:
            return low_value + (high_value - low_value) * (fraction - low_at) / (high_at - low_at)
    return points[-1][1]


def supply_loss(parameters, dc_watts):
    wattage = number(parameters, WATTAGE)
    efficiency = supply_efficiency(parameters, dc_watts / wattage) if wattage else None
    no_load = number(parameters, NO_LOAD) or 0.0
    if not efficiency or dc_watts <= 0:
        return no_load
    return max(no_load, dc_watts / efficiency - dc_watts)


def totals(assets, parameters_of):
    """Sums the parts' watts and figures; the supplies among them share the load by rated wattage."""
    result = Totals()
    supplies = []
    links = {asset.pk: number(parameters_of(asset.part), LINK_SPEED) for asset in assets}
    for asset in assets:
        parameters = parameters_of(asset.part)
        if asset.category == SUPPLY_CATEGORY:
            supplies.append(parameters)
            continue
        result.add_figures(asset, parameters, links.get(asset.belongs_to))
        idle, load = number(parameters, IDLE), number(parameters, LOAD)
        if idle is None and load is None:
            continue
        result.idle_w += idle or 0.0
        result.load_w += load if load is not None else idle
        result.parts.append({"serial": asset.serial, "pk": asset.pk, "part": asset.part, "idle_w": idle, "load_w": load})
    rated = sum(number(supply, WATTAGE) or 0.0 for supply in supplies)
    for supply in supplies:
        share = (number(supply, WATTAGE) or 0.0) / rated if rated else 1 / len(supplies)
        result.loss_idle_w += supply_loss(supply, result.idle_w * share)
        result.loss_load_w += supply_loss(supply, result.load_w * share)
    return result


def job_of(found):
    return "compute" if found.cpu_mark else "storage" if found.terabytes else None


def resource_scores(found, config, profile, utilisation, average):
    """Each weighted resource scored on its own fixed log scale, as figure per average watt; speeds count at
    the utilisation, capacities in full. A resource the machine lacks scores 1: it cannot do that part."""
    rows = []
    for resource, weight in config["profiles"][profile].items():
        if not weight:
            continue
        figure = found.resource(resource)
        used = figure * utilisation if resource in SPEED_RESOURCES else figure
        rows.append({"resource": resource, "weight": weight, "figure": round(figure, 2),
                     "score": log_score(used / average, config["resources"][resource]) if figure else 1})
    return rows


def weighted_score(rows):
    total = sum(row["weight"] for row in rows)
    return round(sum(row["score"] * row["weight"] for row in rows) / total) if total else None


def summary(name, found, config, utilisation, measured=None, on_share=1.0, profile=None):
    """Watts and score of a machine or location. The score is the weighted mean of its resources' scores,
    weights by the machine's profile (its role). A machine switched off part of the time (`on_share`) draws
    that much less on average; its score is taken while it is on, so switching it off does not make it look
    more efficient."""
    average = found.average_w(utilisation)
    job = job_of(found)
    profile = profile or job
    resources = resource_scores(found, config, profile, utilisation, average) if profile and average > 0 else []
    score = weighted_score(resources)
    return {"name": name, "job": job, "profile": profile, "resources": resources, "utilisation": utilisation, "idle_w": round(found.wall_idle_w, 1),
            "average_w": round(average * on_share, 1), "on_share": on_share, "load_w": round(found.wall_load_w, 1),
            "loss_w": round(found.loss_idle_w + utilisation * (found.loss_load_w - found.loss_idle_w), 1),
            "cpu_mark": round(found.cpu_mark), "terabytes": round(found.terabytes, 1), "score": score,
            "measured": measured, "parts": found.parts}


class Inventory:
    """The assets and locations a computation walks, indexed once."""

    def __init__(self, assets, locations, parameters_by_part):
        self.assets = assets
        self.locations = locations
        self.parameters_by_part = parameters_by_part
        self.by_pk = {asset.pk: asset for asset in assets}

    def parameters_of(self, part):
        return self.parameters_by_part.get(part, {})

    def installed_in(self, host):
        found, pending = [], [host.pk]
        while pending:
            pk = pending.pop()
            children = [asset for asset in self.assets if asset.belongs_to == pk]
            found.extend(children)
            pending.extend(child.pk for child in children)
        return found

    def locations_below(self, location_pk):
        """The location and every location inside it, as pks."""
        wanted, pending = set(), [location_pk]
        while pending:
            pk = pending.pop()
            wanted.add(pk)
            pending.extend(child for child, row in self.locations.items() if row["parent"] == pk)
        return wanted

    def location_and_below(self, location_pk):
        wanted = self.locations_below(location_pk)
        placed = [asset for asset in self.assets if asset.location in wanted and asset.belongs_to is None]
        return placed + [part for asset in placed for part in self.installed_in(asset)]

    def location_named(self, name):
        return next((pk for pk, row in self.locations.items() if row["name"].lower() == name.lower()), None)


def utilisation_of(name, config):
    machine = config.get("machines", {}).get(name, {})
    return machine.get("utilisation", config["utilisation"])


def default_profile(host):
    """An enclosure only holds and connects drives, so its CPU and RAM do not count; other machines get their
    profile from their main job."""
    return ENCLOSURE_PROFILE if host.category == ENCLOSURE_CATEGORY else None


def profile_of(name, config):
    return config.get("machines", {}).get(name, {}).get("profile")


def on_share_of(name, config):
    return config.get("machines", {}).get(name, {}).get("on_share", 1.0)


def measured_of(name, config):
    return config.get("machines", {}).get(name, {}).get("measured")


def host_machines(inventory):
    """Every machine is one item with its parts installed in it: a computer, a case or an enclosure."""
    return [asset for asset in inventory.assets if any(other.belongs_to == asset.pk for other in inventory.assets)]


def machine_summaries(inventory, config, within=None):
    """Every powered machine, or only those whose pk is in `within`."""
    rows = []
    for host in host_machines(inventory):
        if within is not None and host.pk not in within:
            continue
        name = f"{host.serial} {host.part}"
        rows.append({**summary(name, totals([host, *inventory.installed_in(host)], inventory.parameters_of), config,
                               utilisation_of(host.serial, config), measured_of(host.serial, config),
                               on_share_of(host.serial, config), profile_of(host.serial, config) or default_profile(host)),
                     "pk": host.pk})
    return [row for row in rows if row["average_w"] > 0]


def powered_assets(inventory, config):
    """What actually draws power: machines with their parts, and everything in a group location (the Pi
    cluster with its shared switch and supplies). Loose spares draw nothing."""
    powered = set()
    for host in host_machines(inventory):
        powered.update(asset.pk for asset in [host, *inventory.installed_in(host)])
    for name in config.get("group_locations", []):
        pk = inventory.location_named(name)
        if pk is not None:
            powered.update(asset.pk for asset in inventory.location_and_below(pk))
    return powered


def location_summaries(inventory, config, within=None):
    """Every location with powered parts below it, or only those whose pk is in `within`: total work over
    total average power, so a 300 W server weighs more than a 5 W Pi."""
    powered = powered_assets(inventory, config)
    machines = machine_summaries(inventory, config)
    rows = []
    for pk, row in sorted(inventory.locations.items(), key=lambda entry: entry[1]["pathstring"]):
        if within is not None and pk not in within:
            continue
        below = [asset for asset in inventory.location_and_below(pk) if asset.pk in powered]
        found = totals(below, inventory.parameters_of)
        if found.idle_w or found.load_w:
            inside = {asset.pk for asset in below}
            location = summary(row["pathstring"], found, config, config["utilisation"])
            location["score"] = power_weighted_score([machine for machine in machines if machine["pk"] in inside])
            rows.append({**location, "resources": [], "parts": []})
    return rows


def power_weighted_score(machines):
    """A location's score: its machines' scores weighted by their average watts, so a 300 W server counts
    more than a 5 W Pi."""
    scored = [machine for machine in machines if machine["score"] is not None and machine["average_w"] > 0]
    watts = sum(machine["average_w"] for machine in scored)
    return round(sum(machine["score"] * machine["average_w"] for machine in scored) / watts) if watts else None
