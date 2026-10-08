"""Bills of materials derived from what is actually installed, so InvenTree's "Used In" finds every part.

Parts are installed in their machine without a BOM (installing does not require one); the BOM only
describes it. A model's BOM lists every model installed in any of its assets, at the highest count one
asset holds, so it shows the configuration of the assets owned, not the product in general.
"""

from collections import Counter

from .sync import Change, by_name


def installed_counts(client):
    """Per host model: the most of each part model that any one asset of it holds directly."""
    items = client.get("/api/stock/")
    host_part = {item["pk"]: item["part"] for item in items}
    per_host = {}
    for item in items:
        if item.get("belongs_to") in host_part:
            per_host.setdefault(item["belongs_to"], Counter())[item["part"]] += float(item["quantity"])
    wanted = {}
    for host, counts in per_host.items():
        model = wanted.setdefault(host_part[host], {})
        for part, quantity in counts.items():
            model[part] = max(model.get(part, 0), quantity)
    return wanted


def plan_boms(taxonomy, client):
    """A BOM row needs its part to be an assembly already, and the flag may only drop once the rows are gone."""
    declared = {part["pk"]: part for key, part in by_name(client.get("/api/part/")).items() if key in taxonomy["models"]}
    wanted = {host: rows for host, rows in installed_counts(client).items() if host in declared}
    current = {}
    for row in client.get("/api/bom/"):
        if row["part"] in declared:
            current.setdefault(row["part"], {})[row["sub_part"]] = row
    raising, changes, dropping = [], [], []
    for pk, part in declared.items():
        rows, existing = wanted.get(pk, {}), current.get(pk, {})
        if part.get("assembly") != bool(rows):
            change = Change(f"~ model {part['name']}: assembly {bool(rows)}",
                            lambda pk=pk, value=bool(rows): client.patch(f"/api/part/{pk}/", {"assembly": value}))
            (raising if rows else dropping).append(change)
        for sub_part, quantity in rows.items():
            row = existing.get(sub_part)
            name = declared.get(sub_part, {}).get("name", sub_part)
            if row is None:
                body = {"part": pk, "sub_part": sub_part, "quantity": quantity}
                changes.append(Change(f"+ bom {part['name']}: {quantity:g} x {name}", lambda body=body: client.post("/api/bom/", body)))
            elif float(row["quantity"]) != quantity:
                changes.append(Change(f"~ bom {part['name']}: {quantity:g} x {name}",
                                      lambda row_pk=row["pk"], quantity=quantity: client.patch(f"/api/bom/{row_pk}/", {"quantity": quantity})))
        for sub_part, row in existing.items():
            if sub_part not in rows:
                name = declared.get(sub_part, {}).get("name", sub_part)
                changes.append(Change(f"- bom {part['name']}: {name}", lambda row_pk=row["pk"]: client.delete(f"/api/bom/{row_pk}/")))
    return raising + changes + dropping
