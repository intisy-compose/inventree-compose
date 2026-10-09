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
SATA_LINK = "SATA link (MB/s)"
NVME_LINK = "NVMe link (MB/s)"
DRIVE_TYPE = "Drive type"
NVME_DRIVE_TYPES = ("M.2 NVMe", "Apple blade")
ENCLOSURE_CATEGORY = "Drive enclosures"
ENCLOSURE_PROFILE = "enclosure"
SUPPLY_CATEGORY = "Power supplies"
DRIVE_CATEGORY = "Storage drives"
MEMORY_CATEGORY = "Memory"
COMPUTER_CATEGORY = "Computers"
SPEED_RESOURCES = ("cpu", "ram_speed", "storage_speed", "gpu")
RESOURCES = ("cpu", "ram_size", "ram_speed", "storage_tb", "storage_speed", "gpu", "vram")
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


def part_figures(asset, parameters):
    """What one part brings, per resource; RAM speed only from memory and one-asset computers."""
    figures = {"cpu": number(parameters, CPU_MARK), "gpu": number(parameters, G3D_MARK), "vram": number(parameters, VRAM),
               "ram_size": (number(parameters, CAPACITY) if asset.category == MEMORY_CATEGORY else None) or number(parameters, RAM),
               "ram_speed": number(parameters, RAM_SPEED) if asset.category in (MEMORY_CATEGORY, COMPUTER_CATEGORY) else None,
               "storage_speed": number(parameters, SEQUENTIAL_READ),
               "storage_tb": (number(parameters, CAPACITY) or 0.0) / 1000 if asset.category == DRIVE_CATEGORY else None}
    return {resource: value for resource, value in figures.items() if value}


def port_speed(drive_parameters, port_parameters):
    """What a port part carries for this drive: an enclosure or dock carries any drive at its link speed, a
    board or controller carries SATA and SAS drives on its SATA ports and NVMe drives on its NVMe slots."""
    nvme = drive_parameters.get(DRIVE_TYPE) in NVME_DRIVE_TYPES
    return number(port_parameters, LINK_SPEED) or number(port_parameters, NVME_LINK if nvme else SATA_LINK)


def drive_cap(drive, assets, by_pk, parameters_of):
    """The best port a drive can sit on: its host and what is installed beside it. None when no port speed is
    known, so the drive counts at its own speed."""
    candidates = [by_pk[drive.belongs_to]] if drive.belongs_to in by_pk else []
    candidates += [asset for asset in assets if asset.belongs_to == drive.belongs_to and asset.pk != drive.pk]
    speeds = [(port_speed(parameters_of(drive.part), parameters_of(port.part)), port) for port in candidates]
    speeds = [(speed, port) for speed, port in speeds if speed]
    if not speeds:
        return None
    speed, port = max(speeds, key=lambda pair: pair[0])
    return {"speed": speed, "by": f"{port.serial} {port.part}"}


@dataclass
class Totals:
    """Watts drawn at the wall: parts plus the conversion loss of the supplies that feed them, and each part's
    figures, from which the machine's figures follow."""
    idle_w: float = 0.0
    load_w: float = 0.0
    loss_idle_w: float = 0.0
    loss_load_w: float = 0.0
    parts: list = field(default_factory=list)

    def values(self, resource, uncapped=False):
        key = "uncapped" if uncapped else "figures"
        return [part[key].get(resource, part["figures"].get(resource)) for part in self.parts
                if resource in part["figures"]]

    def resource(self, name, uncapped=False):
        """A machine's figure per resource: sums for what adds up, the best part for speeds, the slowest
        module for RAM speed because the bus runs at it."""
        found = self.values(name, uncapped)
        if not found:
            return 0.0
        if name == "ram_speed":
            return min(found)
        return max(found) if name in ("storage_speed", "gpu", "vram") else sum(found)

    @property
    def cpu_mark(self):
        return self.resource("cpu")

    @property
    def terabytes(self):
        return self.resource("storage_tb")

    @property
    def capped(self):
        return self.resource("storage_speed") < self.resource("storage_speed", uncapped=True)

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


MISSING_SCORE = 1.0


PART_LEVEL = "part"
MACHINE_LEVEL = "machine"


def percent_score(efficiency, reference, level):
    """Percent of the reference: 100 is as efficient as the best part (or machine) of its kind owned when the
    reference was set, 200 twice as efficient. No upper limit, so better hardware later simply scores higher.
    Parts and machines have their own reference, since a machine pays for its board, fans and supply too."""
    return round(100 * efficiency / reference[level], 1)


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
    by_pk = {asset.pk: asset for asset in assets}
    for asset in assets:
        parameters = parameters_of(asset.part)
        if asset.category == SUPPLY_CATEGORY:
            supplies.append(parameters)
            continue
        figures = part_figures(asset, parameters)
        uncapped, cap = {}, None
        if "storage_speed" in figures:
            cap = drive_cap(asset, assets, by_pk, parameters_of)
            if cap and cap["speed"] < figures["storage_speed"]:
                uncapped["storage_speed"] = figures["storage_speed"]
                figures["storage_speed"] = cap["speed"]
        idle, load = number(parameters, IDLE), number(parameters, LOAD)
        if idle is None and load is None and not figures:
            continue
        result.idle_w += idle or 0.0
        result.load_w += (load if load is not None else idle) or 0.0
        result.parts.append({"serial": asset.serial, "pk": asset.pk, "part": asset.part, "category": asset.category,
                             "idle_w": idle, "load_w": load, "figures": figures, "uncapped": uncapped, "cap": cap})
    rated = sum(number(supply, WATTAGE) or 0.0 for supply in supplies)
    for supply in supplies:
        share = (number(supply, WATTAGE) or 0.0) / rated if rated else 1 / len(supplies)
        result.loss_idle_w += supply_loss(supply, result.idle_w * share)
        result.loss_load_w += supply_loss(supply, result.load_w * share)
    return result


def job_of(found):
    return "compute" if found.cpu_mark else "storage" if found.terabytes else None


def efficiency_of(resource, figure, utilisation, average):
    """A resource's efficiency: its figure per average watt, speeds at the utilisation, capacities in full."""
    used = figure * utilisation if resource in SPEED_RESOURCES else figure
    return used / average if average > 0 else 0.0


def resource_row(resource, figure, reference, utilisation, average, level=MACHINE_LEVEL):
    efficiency = efficiency_of(resource, figure, utilisation, average)
    return {"figure": round(figure, 2), "efficiency": round(efficiency, 4),
            "score": percent_score(efficiency, reference, level) if figure else None}


def resource_scores(found, config, profile, utilisation, average):
    """Each weighted resource as percent of its reference, from its figure per average watt. A capped storage
    speed also shows what it would score uncapped."""
    rows = []
    for resource, weight in config["profiles"][profile].items():
        if not weight:
            continue
        reference = config["resources"][resource]
        row = {"resource": resource, "weight": weight, **resource_row(resource, found.resource(resource), reference, utilisation, average)}
        uncapped = found.resource(resource, uncapped=True)
        if uncapped > found.resource(resource):
            uncapped_row = resource_row(resource, uncapped, reference, utilisation, average)
            row.update({"uncapped_figure": uncapped_row["figure"], "uncapped_score": uncapped_row["score"]})
        rows.append(row)
    return rows


def scored(figures, config, utilisation, average):
    if average <= 0:
        return {}
    return {resource: resource_row(resource, figure, config["resources"][resource], utilisation, average, PART_LEVEL)["score"]
            for resource, figure in figures.items()}


def part_scores(parts, config, utilisation):
    """Each part on its own: every figure it brings over its own average watts, on the same scales as the
    machine. A part without watts of its own adds its figures to the machine but has no score."""
    for part in parts:
        idle, load = part["idle_w"], part["load_w"] if part["load_w"] is not None else part["idle_w"]
        average = average_power(idle or 0.0, load or 0.0, utilisation) if idle is not None or load is not None else 0.0
        part["average_w"] = round(average, 2)
        part["scores"] = scored(part["figures"], config, utilisation, average)
        part["uncapped_scores"] = scored(part["uncapped"], config, utilisation, average)
    return parts


def weighted_score(rows):
    """The weighted geometric mean, so one resource far ahead of the rest (an NVMe drive per watt against a hard
    drive) cannot swamp them. A resource the machine lacks counts as 1: it cannot do that part of the job."""
    total = sum(row["weight"] for row in rows)
    if not total:
        return None
    logs = sum(row["weight"] * math.log(max(row["score"] or MISSING_SCORE, MISSING_SCORE)) for row in rows)
    return round(math.exp(logs / total), 1)


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
    figures = {resource: round(found.resource(resource), 2) for resource in RESOURCES if found.resource(resource)}
    return {"name": name, "job": job, "profile": profile, "resources": resources, "figures": figures,
            "capped": found.capped, "utilisation": utilisation, "idle_w": round(found.wall_idle_w, 1),
            "average_w": round(average * on_share, 1), "on_share": on_share, "load_w": round(found.wall_load_w, 1),
            "loss_w": round(found.loss_idle_w + utilisation * (found.loss_load_w - found.loss_idle_w), 1),
            "cpu_mark": round(found.cpu_mark), "terabytes": round(found.terabytes, 1), "score": score,
            "measured": measured, "parts": part_scores(found.parts, config, utilisation)}


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
    return round(sum(machine["score"] * machine["average_w"] for machine in scored) / watts, 1) if watts else None


def part_resource_scores(asset, parameters, config):
    """A single part on the machine scales: each figure it brings over its own average watts."""
    idle, load = number(parameters, IDLE), number(parameters, LOAD)
    if idle is None and load is None:
        return {}
    average = average_power(idle or 0.0, load if load is not None else idle, config["utilisation"])
    return {resource: resource_row(resource, figure, config["resources"][resource], config["utilisation"], average, PART_LEVEL)
            for resource, figure in part_figures(asset, parameters).items()}
