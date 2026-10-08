"""Makes InvenTree match catalog.toml. Every difference becomes a Change, so `check` lists exactly what
`sync` would do."""

import json
from dataclasses import dataclass
from typing import Callable

from .taxonomy import CatalogError, label_placement, part_description, part_keywords


UNTESTED_STATE = {"key": 11, "name": "UNTESTED", "label": "Untested", "color": "secondary", "logical_key": 10,
                  "reference_status": "StockStatus"}
# A computer's parts are installed in it without the computer being an assembly with a bill of materials.
GLOBAL_SETTINGS = {"SERIAL_NUMBER_GLOBALLY_UNIQUE": True, "INVENTREE_DEFAULT_CURRENCY": "EUR",
                   "STOCK_ENFORCE_BOM_INSTALLATION": False, "ENABLE_PLUGINS_INTERFACE": True}
PLACEMENT_FIELD = "Label placement"
PLUGINS = ("inventory-dashboard", "cd-label-sheet")
POWER_SETTING = "/api/plugins/inventory-dashboard/settings/POWER/"
SETTING_LIMIT = 2000
LABEL_TEMPLATE = {"name": "CD label sheet", "model_type": "stockitem", "width": 210, "height": 297,
                  "description": "Choose it with the CD label sheet printer; that plugin lays out the page itself"}


@dataclass
class Change:
    summary: str
    apply: Callable[[], None]


def by_name(rows):
    return {row["name"].lower(): row for row in rows}


def tags_by_pk(client, endpoint, tag_names):
    """List endpoints leave tags out and treat `tags=` as a filter, so one filtered query per tag maps them."""
    tags = {}
    for tag in tag_names:
        for row in client.get(endpoint, tags=tag):
            tags.setdefault(row["pk"], set()).add(tag)
    return tags


def stages(taxonomy, client):
    """Each stage is planned only after the previous one ran, since later stages refer to rows earlier
    ones create; `check` plans them all against the current state instead."""
    return [
        lambda: plan_settings(client),
        lambda: plan_untested_state(client),
        lambda: plan_plugins(client),
        lambda: plan_label_template(client),
        lambda: plan_power_setting(taxonomy, client),
        lambda: plan_categories(taxonomy, client),
        lambda: plan_templates(taxonomy, client),
        lambda: plan_category_links(taxonomy, client),
        lambda: plan_locations(taxonomy, client),
        lambda: plan_parts(taxonomy, client),
        lambda: plan_parameters(taxonomy, client),
    ]


def check(taxonomy, client):
    return [change.summary for stage in stages(taxonomy, client) for change in stage()]


def sync(taxonomy, client):
    return [line for stage in stages(taxonomy, client) for line in run(stage())]


def run(changes):
    for change in changes:
        change.apply()
    return [change.summary for change in changes]


def plan_settings(client):
    changes = []
    for key, wanted in GLOBAL_SETTINGS.items():
        current = client.get(f"/api/settings/global/{key}/")["value"]
        if current != wanted:
            changes.append(Change(f"~ setting {key}: {current} -> {wanted}",
                                  lambda key=key, wanted=wanted: client.patch(f"/api/settings/global/{key}/", {"value": wanted})))
    return changes


def plan_untested_state(client):
    existing = client.get("/api/generic/status/custom/")
    if any(state["key"] == UNTESTED_STATE["key"] for state in existing):
        return []
    model = client.get("/api/contenttype/model/stockitem/")["pk"]
    return [Change("+ stock status Untested", lambda: client.post("/api/generic/status/custom/", {**UNTESTED_STATE, "model": model}))]


def plan_plugins(client):
    """The plugins live in plugins/, mounted into the server; an unknown one means the mount is missing."""
    installed = {plugin["key"]: plugin for plugin in client.get("/api/plugins/")}
    changes = []
    for key in PLUGINS:
        if key not in installed:
            raise CatalogError(f"plugin {key} is not installed; is plugins/ mounted into the server?")
        if not installed[key]["active"]:
            changes.append(Change(f"+ plugin {key} active", lambda key=key: client.patch(f"/api/plugins/{key}/activate/", {"active": True})))
    return changes


def plan_label_template(client):
    existing = client.get("/api/label/template/", model_type=LABEL_TEMPLATE["model_type"])
    if any(template["name"] == LABEL_TEMPLATE["name"] for template in existing):
        return []
    body = b"<div>{{ item.serial }}</div>\n"
    return [Change(f"+ label template {LABEL_TEMPLATE['name']}", lambda: client.upload(
        "/api/label/template/", "template", "cd-label-sheet.html", body, method="POST", fields=LABEL_TEMPLATE))]


def plan_power_setting(taxonomy, client):
    """The dashboard plugin scores with the [power] table; it cannot read the private data repo itself."""
    if taxonomy.get("power") is None:
        return []
    wanted = json.dumps(taxonomy["power"], separators=(",", ":"), sort_keys=True)
    if len(wanted) > SETTING_LIMIT:
        raise CatalogError(f"[power] is {len(wanted)} characters as JSON; a plugin setting holds {SETTING_LIMIT}")
    if client.get(POWER_SETTING).get("value") == wanted:
        return []
    return [Change("~ plugin setting POWER", lambda: client.patch(POWER_SETTING, {"value": wanted}))]


def plan_categories(taxonomy, client):
    categories = by_name(client.get("/api/part/category/"))
    changes = []
    for key, category in taxonomy["categories"].items():
        body = {"name": category["name"], "description": category.get("description", "")}
        current = categories.get(key)
        if current is None:
            changes.append(Change(f"+ category {category['name']}", lambda body=body: client.post("/api/part/category/", body)))
        elif current["description"] != body["description"]:
            changes.append(Change(f"~ category {category['name']}: description",
                                  lambda pk=current["pk"], body=body: client.patch(f"/api/part/category/{pk}/", body)))
    return changes


def template_body(field):
    kind = field.get("type", "TEXT")
    return {"name": field["name"], "description": field.get("help", ""), "units": "",
            "checkbox": kind == "BOOLEAN", "choices": ",".join(field.get("options", [])) if kind == "OPTION" else ""}


def plan_templates(taxonomy, client):
    templates = by_name(client.get("/api/parameter/template/"))
    changes = []
    for key, field in taxonomy["fields"].items():
        body = template_body(field)
        current = templates.get(key)
        if current is None:
            changes.append(Change(f"+ field {field['name']}", lambda body=body: client.post("/api/parameter/template/", body)))
            continue
        differing = [name for name in ("description", "checkbox", "choices") if current.get(name) != body[name]]
        if differing:
            changes.append(Change(f"~ field {field['name']}: {', '.join(differing)}",
                                  lambda pk=current["pk"], body=body: client.patch(f"/api/parameter/template/{pk}/", body)))
    return changes


def plan_category_links(taxonomy, client):
    categories = by_name(client.get("/api/part/category/"))
    templates = by_name(client.get("/api/parameter/template/"))
    linked = {(row["category"], row["template"]) for row in client.get("/api/part/category/parameters/")}
    changes = []
    for field in taxonomy["fields"].values():
        template = templates.get(field["name"].lower())
        for category_name in field.get("categories", []):
            category = categories.get(category_name.lower())
            if template and category and (category["pk"], template["pk"]) not in linked:
                body = {"category": category["pk"], "template": template["pk"]}
                changes.append(Change(f"+ field {field['name']} on {category_name}",
                                      lambda body=body: client.post("/api/part/category/parameters/", body)))
    return changes


def parents_first(locations):
    ordered, placed = [], set()
    pending = list(locations.values())
    while pending:
        ready = [entry for entry in pending if not entry.get("parent") or entry["parent"].lower() in placed]
        if not ready:
            raise CatalogError("location parents form a cycle")
        for entry in ready:
            ordered.append(entry)
            placed.add(entry["name"].lower())
            pending.remove(entry)
    return ordered


def plan_locations(taxonomy, client):
    existing = by_name(client.get("/api/stock/location/"))
    changes = []
    for location in parents_first(taxonomy["locations"]):
        current = existing.get(location["name"].lower()) or existing.get(str(location.get("renamed_from", "")).lower())
        parent = existing.get(str(location.get("parent", "")).lower())
        wanted = (location["name"], location.get("description", ""), parent["pk"] if parent else None)
        if current is None:
            changes.append(Change(f"+ location {location['name']}", lambda location=location: create_location(client, existing, location)))
        elif (current["name"], current["description"], current["parent"]) != wanted:
            body = dict(zip(("name", "description", "parent"), wanted))
            changes.append(Change(f"~ location {location['name']}",
                                  lambda pk=current["pk"], body=body: client.patch(f"/api/stock/location/{pk}/", body)))
    return changes


def create_location(client, existing, location):
    """Runs parents first, so a new child finds the parent this same pass just created."""
    parent = existing.get(str(location.get("parent", "")).lower())
    body = {"name": location["name"], "description": location.get("description", ""), "parent": parent["pk"] if parent else None}
    created = client.post("/api/stock/location/", body)
    existing[created["name"].lower()] = created


def part_body(taxonomy, model, categories):
    category = categories.get(model["category"].lower())
    return {"name": model["name"], "description": part_description(taxonomy, model)[:250],
            "keywords": part_keywords(taxonomy, model), "category": category["pk"] if category else None,
            "trackable": model.get("serialized", True), "component": True, "purchaseable": False, "active": True}


def plan_parts(taxonomy, client):
    categories = by_name(client.get("/api/part/category/"))
    parts = by_name(client.get("/api/part/"))
    part_tags = tags_by_pk(client, "/api/part/", [tag["name"] for tag in taxonomy["tags"].values()])
    changes = []
    for key, model in taxonomy["models"].items():
        body = part_body(taxonomy, model, categories)
        tags = sorted(model.get("tags", []))
        current = parts.get(key)
        if current is None:
            changes.append(Change(f"+ model {model['name']}", lambda body=body, tags=tags: client.post("/api/part/", {**body, "tags": tags})))
            continue
        differing = [name for name in ("description", "keywords", "category", "trackable") if (current.get(name) or "") != (body[name] or "")]
        if sorted(part_tags.get(current["pk"], set())) != tags:
            differing.append("tags")
        if differing:
            changes.append(Change(f"~ model {model['name']}: {', '.join(differing)}",
                                  lambda pk=current["pk"], body=body, tags=tags: client.patch(f"/api/part/{pk}/", {**body, "tags": tags})))
    return changes


def parameter_text(value):
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def model_parameters(taxonomy, model):
    """The model's fields plus the ones the tool generates for every model."""
    return {**model.get("fields", {}), PLACEMENT_FIELD: label_placement(taxonomy, model)}


def plan_parameters(taxonomy, client):
    parts = by_name(client.get("/api/part/"))
    templates = by_name(client.get("/api/parameter/template/"))
    existing = {}
    for row in client.get("/api/parameter/", model_type="part.part"):
        existing[(row["model_id"], row["template"])] = row
    changes = []
    for key, model in taxonomy["models"].items():
        part = parts.get(key)
        if part is None:
            continue
        for name, value in model_parameters(taxonomy, model).items():
            template = templates.get(name.lower())
            if template is None:
                continue
            text = parameter_text(value)
            current = existing.pop((part["pk"], template["pk"]), None)
            body = {"template": template["pk"], "model_type": "part.part", "model_id": part["pk"], "data": text}
            if current is None:
                changes.append(Change(f"+ {model['name']}: {name} = {text}", lambda body=body: client.post("/api/parameter/", body)))
            elif current["data"] != text:
                changes.append(Change(f"~ {model['name']}: {name} = {text}",
                                      lambda pk=current["pk"], body=body: client.patch(f"/api/parameter/{pk}/", body)))
    declared = {parts[key]["pk"] for key in taxonomy["models"] if key in parts}
    for (part_pk, _), row in existing.items():
        if part_pk in declared:
            changes.append(Change(f"- parameter {row['pk']} on part {part_pk}", lambda pk=row["pk"]: client.delete(f"/api/parameter/{pk}/")))
    return changes
