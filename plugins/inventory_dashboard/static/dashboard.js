// Renders the inventory dashboard widgets from the data the plugin computes on the server.

const euro = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });

function escape(text) {
    const element = document.createElement("span");
    element.textContent = String(text ?? "");
    return element.innerHTML;
}

function link(item) {
    return `<a href="${item.url}" style="color: inherit">${escape(item.id)}</a>`;
}

function table(headers, rows, alignRight = []) {
    const cell = (value, index, tag) =>
        `<${tag} style="padding: 2px 6px; text-align: ${alignRight.includes(index) ? "right" : "left"}">${value}</${tag}>`;
    const head = headers.map((header, index) => cell(escape(header), index, "th")).join("");
    const body = rows.map((row) => `<tr>${row.map((value, index) => cell(value, index, "td")).join("")}</tr>`).join("");
    return `<table style="width: 100%; border-collapse: collapse; font-size: 0.85em"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function frame(target, html) {
    if (!target) {
        return;
    }
    target.innerHTML = `<div style="overflow: auto; height: 100%">${html}</div>`;
}

function stat(label, value) {
    return `<div style="display: inline-block; margin: 0 18px 8px 0"><div style="font-size: 1.4em; font-weight: 600">${value}</div><div style="opacity: 0.7; font-size: 0.8em">${escape(label)}</div></div>`;
}

export function renderOverview(target, data) {
    const context = data?.context ?? {};
    const rows = (context.categories ?? []).map((row) => [escape(row.name), row.count, euro.format(row.value)]);
    frame(target, stat("assets", context.count ?? 0) + stat("total value", euro.format(context.value ?? 0)) +
        table(["Category", "Assets", "Value"], rows, [1, 2]));
}

export function renderAttention(target, data) {
    const context = data?.context ?? {};
    const counts = context.counts ?? {};
    const stats = Object.entries(counts).map(([label, count]) => stat(label, count)).join("");
    const faulty = context.faulty ?? [];
    const list = faulty.length
        ? table(["Asset", "Model", "Condition"], faulty.map((item) => [link(item), escape(item.name), escape(item.condition)]))
        : `<p style="opacity: 0.7">Nothing is known to be faulty.</p>`;
    frame(target, stats + list);
}

export function renderMachines(target, data) {
    const context = data?.context ?? {};
    const hosts = (context.hosts ?? []).map((host) => [link(host), escape(host.name), host.parts]);
    const places = (context.locations ?? []).map((place) => [escape(place.name), place.count]);
    frame(target, table(["Asset", "Machine", "Parts"], hosts, [2]) + "<br>" + table(["Location", "Items"], places, [1]));
}

export function renderRecent(target, data) {
    const items = data?.context?.items ?? [];
    frame(target, table(["Asset", "Model", "Added"], items.map((item) => [link(item), escape(item.name), escape(item.created)])));
}

export function renderLabels(target, data) {
    const context = data?.context ?? {};
    const counts = context.counts ?? {};
    const printed = (counts.large ?? 0) + (counts.standard ?? 0) + (counts.small ?? 0);
    const untagged = context.untagged ? stat("without a size", context.untagged) : "";
    frame(target, stat("stickers", printed) + stat("large", counts.large ?? 0) + stat("standard", counts.standard ?? 0) +
        stat("small", counts.small ?? 0) + stat("no sticker", counts.none ?? 0) + untagged +
        stat("stuck on", context.stuck ?? 0));
}

function watts(value) {
    return value === null || value === undefined ? "-" : `${Number(value).toLocaleString("de-DE", { maximumFractionDigits: 1 })} W`;
}

function score(value) {
    return value === null || value === undefined ? "-" : `<b>${points(value)}</b>`;
}

const RESOURCES = {
    cpu: ["CPU", "CPU Mark"], ram_size: ["RAM", "GB"], ram_speed: ["RAM speed", "MT/s"],
    storage_tb: ["Storage", "TB"], storage_speed: ["Storage speed", "MB/s"], gpu: ["GPU", "G3D Mark"], vram: ["VRAM", "GB"],
};
const GROUPS = [["CPU", ["cpu"]], ["RAM", ["ram_size", "ram_speed"]], ["Storage", ["storage_tb", "storage_speed"]], ["GPU", ["gpu", "vram"]]];

function amount(value) {
    return Number(value).toLocaleString("de-DE", { maximumFractionDigits: 2 });
}

function points(value) {
    if (value === null || value === undefined) {
        return "-";
    }
    return Number(value).toLocaleString("de-DE", { maximumFractionDigits: value < 10 ? 1 : 0 });
}

function resourceName(resource) {
    return (RESOURCES[resource] ?? [resource])[0];
}

function figureText(resource, value) {
    return `${amount(value)} ${(RESOURCES[resource] ?? [resource, ""])[1]}`;
}

function scoresOf(row) {
    return Object.fromEntries((row.resources ?? []).map((resource) => [resource.resource, resource.score]));
}

function groupCell(row, keys) {
    const figures = row.figures ?? {};
    const scores = scoresOf(row);
    const present = keys.filter((key) => figures[key]);
    if (!present.length) {
        return cell("-", -1);
    }
    const scored = present.filter((key) => scores[key] !== undefined && scores[key] !== null);
    const scoreLine = scored.length ? `<div style="opacity: 0.6; font-size: 0.85em">${scored.map((key) => points(scores[key])).join(" &middot; ")}</div>` : "";
    return cell(`<div>${escape(present.map((key) => figureText(key, figures[key])).join(" · "))}</div>${scoreLine}`, figures[present[0]]);
}

function work(row) {
    const figures = row.figures ?? {};
    const found = Object.keys(RESOURCES).filter((resource) => figures[resource]);
    return found.length ? found.map((resource) => figureText(resource, figures[resource])).join(", ") : "-";
}

function measured(row) {
    const reading = row.measured;
    return reading ? `${watts(reading.idle_w)} / ${watts(reading.load_w)}` : "-";
}

function powerRow(row, first) {
    return [first, cell(watts(row.average_w), row.average_w), ...GROUPS.map(([, keys]) => groupCell(row, keys)),
        cell(score(row.score), row.score ?? -1)];
}

const POWER_HEADERS = ["Average", ...GROUPS.map(([name]) => name), "Score"];

export function renderPower(target, data) {
    const context = data?.context ?? {};
    const machines = sortableTable(["Machine", ...POWER_HEADERS], (context.machines ?? []).map((row) =>
        powerRow(row, cell(escape(row.name), row.name))), [1, 6]);
    const locations = sortableTable(["Location", ...POWER_HEADERS], (context.locations ?? []).map((row) =>
        powerRow(row, cell(escape(row.name), row.name))), [1, 6]);
    frame(target, `${machines}<br>${locations}<p style="opacity: 0.7; font-size: 0.8em">Figures, and under them each resource's ` +
        `score in percent of the best part of its kind. The Efficiency menu shows how.</p>`);
    enableSorting(target);
}

function partCap(part) {
    if (!part.cap) {
        return part.figures?.storage_speed ? "port speed unknown" : "";
    }
    const limited = part.uncapped?.storage_speed;
    return limited ? `reads ${amount(limited)} MB/s, counts ${amount(part.cap.speed)} on ${escape(part.cap.by)}`
        : `${amount(part.cap.speed)} MB/s port, not limiting (${escape(part.cap.by)})`;
}

function partLink(part) {
    return `<a href="/web/stock/item/${part.pk}" style="color: inherit">${escape(part.serial)}</a>`;
}

function resourceSummary(resource) {
    const capped = resource.uncapped_figure ? `, could do ${figureText(resource.resource, resource.uncapped_figure)}` : "";
    const uncapped = resource.uncapped_score ? ` (${points(resource.uncapped_score)} without the cap)` : "";
    const figure = resource.figure ? figureText(resource.resource, resource.figure) : "none";
    return `<b>${escape(resourceName(resource.resource))}</b>: ${escape(figure + capped)}, score <b>${points(resource.score ?? 1)}</b>` +
        `${uncapped}, weight ${Math.round(resource.weight * 100)}%`;
}

function resourceParts(parts, resource) {
    const rows = parts.filter((part) => part.figures?.[resource]).map((part) => {
        const own = part.scores?.[resource];
        const uncapped = part.uncapped_scores?.[resource];
        const ownText = own === undefined ? "no watts of its own" : `${points(own)}${uncapped ? ` (${points(uncapped)} uncapped)` : ""}`;
        const row = [partLink(part), escape(part.part), escape(figureText(resource, part.figures[resource])), watts(part.average_w), ownText];
        return resource === "storage_speed" ? [...row, partCap(part)] : row;
    });
    const headers = ["Asset", "Part", "Brings", "Average", "Its own score"];
    return rows.length ? table(resource === "storage_speed" ? [...headers, "Port"] : headers, rows, [3, 4])
        : `<p style="opacity: 0.7; font-size: 0.85em; margin: 2px 0">Nothing in this machine has it.</p>`;
}

function resourceDetails(row) {
    const parts = row.parts ?? [];
    const scored = new Set((row.resources ?? []).map((resource) => resource.resource));
    const blocks = Object.keys(RESOURCES).filter((resource) => scored.has(resource)).map((resource) => {
        const entry = row.resources.find((candidate) => candidate.resource === resource);
        return `<details style="margin: 2px 0 2px 8px"><summary>${resourceSummary(entry)}</summary>` +
            `<div style="margin-left: 14px">${resourceParts(parts, resource)}</div></details>`;
    });
    const others = parts.filter((part) => !Object.keys(part.figures ?? {}).length);
    if (others.length) {
        blocks.push(`<details style="margin: 2px 0 2px 8px"><summary>Other parts, watts only (${others.length})</summary>` +
            `<div style="margin-left: 14px">${table(["Asset", "Part", "Average"], others.map((part) =>
                [partLink(part), escape(part.part), watts(part.average_w)]), [2])}</div></details>`);
    }
    return blocks.join("");
}

export function renderPowerPanel(target, data) {
    const row = data?.context ?? {};
    const stats = stat("idle", watts(row.idle_w)) + stat(`average at ${Math.round((row.utilisation ?? 0) * 100)}%`, watts(row.average_w)) +
        stat("load", watts(row.load_w)) + stat("supply loss", watts(row.loss_w)) +
        stat("score", points(row.score)) + (row.measured ? stat("measured idle / load", measured(row)) : "");
    const profile = row.profile ? `<p style="opacity: 0.7; font-size: 0.8em">Scored as ${escape(row.profile)}. Open a resource ` +
        `to see the parts behind it; the Efficiency menu explains the score.</p>` : "";
    frame(target, stats + profile + resourceDetails(row));
}

export function renderPartPower(target, data) {
    const context = data?.context ?? {};
    const resources = Object.entries(context.resources ?? {});
    const share = Math.round((context.utilisation ?? 0) * 100);
    const scored = resources.map(([resource, row]) => stat(resourceName(resource), figureText(resource, row.figure)) +
        stat(`score at ${share}%`, points(row.score))).join("");
    const legacy = !resources.length && context.score
        ? stat(context.score.unit, Number(context.score.figure).toLocaleString("de-DE")) + stat(`score (${context.score.class})`, context.score.score) : "";
    const source = context.source ? `<p style="opacity: 0.7; font-size: 0.8em">${escape(context.source)}</p>` : "";
    frame(target, stat("idle", watts(context.idle_w)) + stat("load", watts(context.load_w)) + scored + legacy + source);
}

function cell(html, sort) {
    return { html, sort: sort ?? "" };
}

function sortableTable(headers, rows, alignRight = []) {
    const align = (index) => `text-align: ${alignRight.includes(index) ? "right" : "left"}`;
    const head = headers.map((header, index) =>
        `<th style="padding: 2px 6px; cursor: pointer; ${align(index)}" title="Sort">${escape(header)}</th>`).join("");
    const body = rows.map((row) => `<tr>${row.map((value, index) =>
        `<td data-sort="${escape(value.sort)}" style="padding: 2px 6px; ${align(index)}">${value.html}</td>`).join("")}</tr>`).join("");
    return `<table data-sortable style="width: 100%; border-collapse: collapse; font-size: 0.85em"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function compare(first, second) {
    const numbers = [Number(first), Number(second)];
    if (first !== "" && second !== "" && !numbers.some(Number.isNaN)) {
        return numbers[0] - numbers[1];
    }
    return String(first).localeCompare(String(second), "de", { numeric: true });
}

function enableSorting(target) {
    target?.querySelectorAll("table[data-sortable]").forEach((element) => {
        element.querySelectorAll("th").forEach((header, index) => {
            header.addEventListener("click", () => {
                const ascending = header.dataset.order !== "ascending";
                header.dataset.order = ascending ? "ascending" : "descending";
                const body = element.tBodies[0];
                [...body.rows]
                    .sort((first, second) => compare(first.cells[index].dataset.sort, second.cells[index].dataset.sort) * (ascending ? 1 : -1))
                    .forEach((row) => body.appendChild(row));
            });
        });
    });
}

function heading(text) {
    return `<h4 style="margin: 14px 0 4px">${escape(text)}</h4>`;
}

function money(value) {
    return value === null || value === undefined ? "-" : euro.format(value);
}

function assetCell(item) {
    return cell(link(item), item.id);
}

export function renderValueMenu(target, data) {
    const context = data?.context ?? {};
    const stats = stat("assets", context.count ?? 0) + stat("total value", money(context.value ?? 0)) +
        (context.unpriced ? stat("without a price", context.unpriced) : "");
    const categories = sortableTable(["Category", "Assets", "Value"], (context.categories ?? []).map((row) =>
        [cell(escape(row.name), row.name), cell(row.count, row.count), cell(money(row.value), row.value)]), [1, 2]);
    const locations = sortableTable(["Location", "Assets", "Value"], (context.locations ?? []).map((row) =>
        [cell(escape(row.name), row.name), cell(row.count, row.count), cell(money(row.value), row.value)]), [1, 2]);
    const machines = sortableTable(["Machine", "Model", "Items", "Value"], (context.machines ?? []).map((row) =>
        [assetCell(row), cell(escape(row.name), row.name), cell(row.count, row.count), cell(money(row.value), row.value)]), [2, 3]);
    const assets = sortableTable(["Asset", "Model", "Category", "Where", "Price"], (context.assets ?? []).map((row) =>
        [assetCell(row), cell(escape(row.name), row.name), cell(escape(row.category), row.category), cell(escape(row.where), row.where),
            cell(money(row.price), row.price ?? -1)]), [4]);
    frame(target, stats + heading("By category") + categories + heading("By location") + locations +
        heading("By machine, everything installed included") + machines + heading("Every asset") + assets);
    enableSorting(target);
}

function scoreNote(scale) {
    if (!scale) {
        return "";
    }
    const share = Math.round((scale.utilisation ?? 0) * 100);
    const references = Object.entries(scale.resources ?? {}).map(([resource, reference]) =>
        `${resourceName(resource)}: ${reference.best_part} / ${reference.best_machine}`).join("; ");
    return `<p style="opacity: 0.7; font-size: 0.8em; margin-top: 12px">Each resource scores 100 x its efficiency / the efficiency ` +
        `of the best of its kind you owned on ${escape(scale.set ?? "")}: the best part for a part, the best machine for a machine. ` +
        `100 is that one and there is no upper limit. Efficiency is the figure per average ` +
        `watt (idle plus ${share}% of the way to load; speeds count at ${share}% use, capacities in full). A machine scores the ` +
        `weighted geometric mean of its resources by profile (a resource it lacks counts as 1), a location the mean of its machines ` +
        `by watts. A drive counts at most at the speed of its port. References: ${escape(references)}.</p>`;
}

export function renderEfficiencyMenu(target, data) {
    const context = data?.context ?? {};
    if (context.missing) {
        frame(target, `<p style="opacity: 0.7">No power settings yet: run the catalog tool's sync.</p>`);
        return;
    }
    const machines = sortableTable(["Machine", "Profile", ...POWER_HEADERS], (context.machines ?? []).map((row) => {
        const [first, ...rest] = powerRow(row, cell(`<a href="${row.url}" style="color: inherit">${escape(row.name)}</a>`, row.name));
        return [first, cell(escape(row.profile ?? "-"), row.profile ?? ""), ...rest];
    }), [2, 7]);
    const locations = sortableTable(["Location", ...POWER_HEADERS], (context.locations ?? []).map((row) =>
        powerRow(row, cell(escape(row.name), row.name))), [1, 6]);
    const details = (context.machines ?? []).filter((row) => row.resources?.length).map((row) =>
        `<details style="margin: 4px 0"><summary><b>${escape(row.name)}</b>, score ${points(row.score)}, ${watts(row.average_w)} average` +
        `${row.capped ? ", storage capped by its ports" : ""}</summary>${resourceDetails(row)}</details>`).join("");
    frame(target, heading("Machines") + machines + heading("Locations") + locations + heading("Each machine, resource by resource") +
        details + scoreNote(context.scale));
    enableSorting(target);
}

export function renderAttentionMenu(target, data) {
    const context = data?.context ?? {};
    const stats = Object.entries(context.counts ?? {}).map(([label, count]) => stat(label, count)).join("");
    const items = context.items ?? [];
    const list = items.length
        ? sortableTable(["Asset", "Model", "Condition", "Where", "Notes"], items.map((item) => [assetCell(item),
            cell(escape(item.name), item.name), cell(escape(item.condition), item.condition), cell(escape(item.where), item.where),
            cell(escape(item.notes), item.notes)]))
        : `<p style="opacity: 0.7">Nothing here needs attention.</p>`;
    frame(target, stats + list);
    enableSorting(target);
}

function machineNode(node) {
    const facts = [money(node.value), node.average_w ? watts(node.average_w) : "", node.score ? `score ${node.score}` : ""]
        .filter(Boolean).join(" &middot; ");
    const line = `${link(node)} ${escape(node.name)} <span style="opacity: 0.7">${facts}</span>`;
    if (!node.children?.length) {
        return `<div style="padding: 1px 0 1px 18px">${line}</div>`;
    }
    return `<details open style="padding-left: 4px"><summary>${line}</summary>` +
        `<div style="padding-left: 14px">${node.children.map(machineNode).join("")}</div></details>`;
}

export function renderMachinesMenu(target, data) {
    const machines = data?.context?.machines ?? [];
    frame(target, machines.length ? machines.map(machineNode).join("") : `<p style="opacity: 0.7">No machines here.</p>`);
}

function saveSticker(data, pk, stuck) {
    const body = { metadata: { sticker: stuck } };
    const url = `/api/metadata/stockitem/${pk}/`;
    if (data?.api) {
        return data.api.patch(url, body);
    }
    const token = document.cookie.split("; ").find((entry) => entry.startsWith("csrftoken="))?.split("=")[1] ?? "";
    return fetch(url, {
        method: "PATCH", credentials: "same-origin", body: JSON.stringify(body),
        headers: { "Content-Type": "application/json", "X-CSRFToken": token },
    }).then((response) => {
        if (!response.ok) {
            throw new Error(response.statusText);
        }
    });
}

function stickerNote(size, stuck) {
    return stuck ? `${size}, stuck on ${stuck}` : size;
}

function stickerRow(row) {
    const indent = `padding-left: ${row.depth * 16}px`;
    if (row.kind === "group") {
        return `<div style="${indent}; margin-top: 6px; font-weight: 600">${escape(row.name)}</div>`;
    }
    return `<label data-sticker data-size="${escape(row.size)}" style="display: block; ${indent}; cursor: pointer">` +
        `<input type="checkbox" data-pk="${row.pk}" ${row.stuck ? "checked" : ""}> ${link(row)} ${escape(row.name)} ` +
        `<span style="opacity: 0.6">${escape(stickerNote(row.size, row.stuck))}</span></label>`;
}

export function renderStickersMenu(target, data) {
    const context = data?.context ?? {};
    const total = context.total ?? 0;
    let stuck = context.stuck ?? 0;
    const progress = () => `${stuck} of ${total} stuck on`;
    frame(target, `<div style="margin-bottom: 8px"><b data-progress>${progress()}</b>` +
        `<label style="margin-left: 18px; cursor: pointer"><input type="checkbox" data-missing> only missing</label></div>` +
        (context.rows ?? []).map(stickerRow).join(""));
    if (!target) {
        return;
    }
    const onlyMissing = target.querySelector("input[data-missing]");
    const filter = () => target.querySelectorAll("label[data-sticker]").forEach((label) => {
        label.style.display = onlyMissing.checked && label.querySelector("input").checked ? "none" : "block";
    });
    onlyMissing.addEventListener("change", filter);
    target.querySelectorAll("input[data-pk]").forEach((box) => box.addEventListener("change", () => {
        const today = new Date().toISOString().slice(0, 10);
        const label = box.closest("label");
        box.disabled = true;
        saveSticker(data, box.dataset.pk, box.checked ? today : null).then(() => {
            stuck += box.checked ? 1 : -1;
            target.querySelector("[data-progress]").textContent = progress();
            label.querySelector("span").textContent = stickerNote(label.dataset.size, box.checked ? today : null);
            filter();
        }).catch(() => {
            box.checked = !box.checked;
            target.querySelector("[data-progress]").textContent = `${progress()} (saving failed, try again)`;
        }).finally(() => {
            box.disabled = false;
        });
    }));
}
