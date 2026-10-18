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

const SCORE_LABELS = { cpu: "score", ram_size: "size", ram_speed: "speed", storage_tb: "capacity", storage_speed: "speed", gpu: "speed", vram: "VRAM" };

function groupCell(row, keys) {
    const figures = row.figures ?? {};
    const scores = scoresOf(row);
    const present = keys.filter((key) => figures[key]);
    if (!present.length) {
        return cell("-", -1);
    }
    const scored = present.filter((key) => scores[key] !== undefined && scores[key] !== null);
    const scoreLine = scored.length ? `<div style="opacity: 0.6; font-size: 0.85em">${scored.map((key) =>
        `${SCORE_LABELS[key]} ${points(scores[key])}`).join(" &middot; ")}</div>` : "";
    return cell(`<div>${escape(present.map((key) => figureText(key, figures[key])).join(" · "))}</div>${scoreLine}`, figures[present[0]]);
}

function overheadCell(row) {
    const overhead = (row.resources ?? []).find((resource) => resource.resource === "overhead");
    if (!overhead || overhead.score === null || overhead.score === undefined) {
        return cell("-", -1);
    }
    return cell(`<div>${watts(overhead.overhead_w)}</div><div style="opacity: 0.6; font-size: 0.85em">${points(overhead.score)}% to working parts</div>`,
        overhead.score);
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
    return [first, cell(watts(row.average_w), row.average_w), ...GROUPS.map(([, keys]) => groupCell(row, keys)), overheadCell(row),
        cell(score(row.score), row.score ?? -1)];
}

const POWER_HEADERS = ["Average", ...GROUPS.map(([name]) => name), "Overhead", "Score"];

export function renderPower(target, data) {
    const context = data?.context ?? {};
    const machines = sortableTable(["Machine", ...POWER_HEADERS], (context.machines ?? []).map((row) =>
        powerRow(row, cell(escape(row.name), row.name))), [1, 7]);
    const locations = sortableTable(["Location", ...POWER_HEADERS], (context.locations ?? []).map((row) =>
        powerRow(row, cell(escape(row.name), row.name))), [1, 7]);
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
    if (resource.resource === "overhead") {
        return `<b>Overhead</b>: ${watts(resource.overhead_w)} besides the working parts, ${points(resource.score)}% of the watts do ` +
            `work, score <b>${points(resource.score)}</b>, weight ${Math.round(resource.weight * 100)}%`;
    }
    const capped = resource.uncapped_figure ? `, could do ${figureText(resource.resource, resource.uncapped_figure)}` : "";
    const uncapped = resource.uncapped_score ? ` (${points(resource.uncapped_score)} without the cap)` : "";
    const figure = resource.figure ? figureText(resource.resource, resource.figure) : "none";
    return `<b>${escape(resourceName(resource.resource))}</b>: ${escape(figure + capped)}, score <b>${points(resource.score)}</b>` +
        `${uncapped}, weight ${Math.round(resource.weight * 100)}%`;
}

const ROLES = { os: "OS drive, not counted", cluster: "cluster storage", data: "data drive", array: "private array" };
const STORAGE = ["storage_tb", "storage_speed"];

function resourceParts(parts, resource) {
    const storage = STORAGE.includes(resource);
    const rows = parts.filter((part) => part.figures?.[resource]).map((part) => {
        const own = part.scores?.[resource];
        const uncapped = part.uncapped_scores?.[resource];
        const ownText = own === undefined ? "no watts of its own" : `${points(own)}${uncapped ? ` (${points(uncapped)} uncapped)` : ""}`;
        const row = [partLink(part), escape(part.part), escape(figureText(resource, part.figures[resource])), watts(part.average_w), ownText];
        const role = escape(ROLES[part.role] ?? "no role");
        return resource === "storage_speed" ? [...row, role, partCap(part)] : storage ? [...row, role] : row;
    });
    const headers = ["Asset", "Part", "Brings", "Average", "Its own score"];
    const withRole = storage ? [...headers, "Role"] : headers;
    return rows.length ? table(resource === "storage_speed" ? [...withRole, "Port"] : withRole, rows, [3, 4])
        : `<p style="opacity: 0.7; font-size: 0.85em; margin: 2px 0">Nothing in this machine has it.</p>`;
}

function resourceDetails(row) {
    const parts = row.parts ?? [];
    const others = parts.filter((part) => !Object.keys(part.figures ?? {}).length);
    const order = [...Object.keys(RESOURCES), "overhead"];
    return order.map((key) => (row.resources ?? []).find((resource) => resource.resource === key)).filter(Boolean).map((resource) => {
        const body = resource.resource === "overhead"
            ? (others.length ? table(["Asset", "Part", "Average"], others.map((part) => [partLink(part), escape(part.part), watts(part.average_w)]), [2])
                : "") + (row.loss_w ? `<p style="opacity: 0.7; font-size: 0.85em; margin: 2px 0">Power supply loss: ${watts(row.loss_w)}</p>` : "")
            : resourceParts(parts, resource.resource);
        return `<details style="margin: 2px 0 2px 8px"><summary>${resourceSummary(resource)}</summary>` +
            `<div style="margin-left: 14px">${body}</div></details>`;
    }).join("");
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
        `${resourceName(resource)}: ${reference.best_part}`).join("; ");
    return `<p style="opacity: 0.7; font-size: 0.8em; margin-top: 12px">Every part scores 100 x its efficiency / the efficiency of ` +
        `the best part of its kind you owned on ${escape(scale.set ?? "")}, with no upper limit. Efficiency is the figure per average ` +
        `watt (idle plus ${share}% of the way to load; speeds count at ${share}% use, capacities in full). A machine's resource is the ` +
        `score of the parts that provide it, weighted by how much each brings; its overhead is the share of its watts that go to ` +
        `working parts. A machine scores the weighted geometric mean of these by profile (a resource it lacks is left out), a location ` +
        `the mean of its machines by watts. A drive counts at most at the speed of its port; an OS drive adds no storage. ` +
        `References: ${escape(references)}.</p>`;
}

const MACHINE_COLUMNS = "minmax(180px, 2.2fr) 0.8fr 0.8fr 1.2fr 1.4fr 1.4fr 1.4fr 1fr 0.6fr";

function machineCells(row) {
    const name = `<a href="${row.url}" style="color: inherit">${escape(row.name)}</a>`;
    return [cell(name, row.name), cell(escape(row.profile ?? "-"), row.profile ?? ""), ...powerRow(row, cell("", "")).slice(1)];
}

function machineBlock(row, rows, depth) {
    const cells = machineCells(row).map((value, index) =>
        `<div style="padding: 2px 6px; ${index >= 2 ? "text-align: right" : ""}">${value.html}</div>`).join("");
    const children = rows.filter((child) => child.parent === row.pk).map((child) => machineBlock(child, rows, depth + 1)).join("");
    const detail = resourceDetails(row);
    return `<details style="margin-left: ${depth * 16}px; border-top: 1px solid rgba(128, 128, 128, 0.25)">` +
        `<summary style="display: grid; grid-template-columns: ${MACHINE_COLUMNS}; align-items: start; cursor: pointer; font-size: 0.85em">` +
        `${cells}</summary><div style="margin: 4px 0 8px 12px">${detail}${children}</div></details>`;
}

function machineList(target, rows, sortIndex, ascending) {
    const top = rows.filter((row) => !row.parent || !rows.some((other) => other.pk === row.parent));
    if (sortIndex !== null) {
        top.sort((first, second) => compare(machineCells(first)[sortIndex].sort, machineCells(second)[sortIndex].sort) * (ascending ? 1 : -1));
    }
    const headers = ["Machine", "Profile", ...POWER_HEADERS].map((header, index) =>
        `<div data-column="${index}" title="Sort" style="padding: 2px 6px; font-weight: 600; cursor: pointer; ${index >= 2 ? "text-align: right" : ""}">` +
        `${escape(header)}</div>`).join("");
    target.innerHTML = `<div style="display: grid; grid-template-columns: ${MACHINE_COLUMNS}; font-size: 0.85em; padding-left: 14px">${headers}</div>` +
        top.map((row) => machineBlock(row, rows, 0)).join("");
    target.querySelectorAll("[data-column]").forEach((header) => header.addEventListener("click", () => {
        const index = Number(header.dataset.column);
        machineList(target, rows, index, sortIndex === index ? !ascending : true);
    }));
}

export function renderEfficiencyMenu(target, data) {
    const context = data?.context ?? {};
    if (context.missing) {
        frame(target, `<p style="opacity: 0.7">No power settings yet: run the catalog tool's sync.</p>`);
        return;
    }
    const locations = sortableTable(["Location", ...POWER_HEADERS, "Cluster storage"], (context.locations ?? []).map((row) =>
        [...powerRow(row, cell(escape(row.name), row.name)), cell(row.cluster_tb ? `${amount(row.cluster_tb)} TB` : "-", row.cluster_tb ?? 0)]),
        [1, 7, 8]);
    frame(target, heading("Machines") + `<div data-machines></div>` + heading("Locations") + locations + scoreNote(context.scale));
    if (!target) {
        return;
    }
    machineList(target.querySelector("[data-machines]"), context.machines ?? [], null, true);
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
    const facts = [node.role ? ROLES[node.role] ?? node.role : "", money(node.value), node.average_w ? watts(node.average_w) : "",
        node.score ? `score ${points(node.score)}` : ""]
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

const LABEL_TEMPLATE = "Asset labels";
const LABEL_PRINTER = "asset-labels";
const PRINT_POLL_MS = 1500;
const PRINT_POLL_LIMIT = 120;

function apiRequest(data, method, url, body) {
    if (data?.api) {
        const call = method === "GET" ? data.api.get(url) : data.api[method.toLowerCase()](url, body);
        return call.then((response) => response.data);
    }
    const token = document.cookie.split("; ").find((entry) => entry.startsWith("csrftoken="))?.split("=")[1] ?? "";
    return fetch(url, {
        method, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body),
        headers: { "Content-Type": "application/json", "X-CSRFToken": token },
    }).then((response) => {
        if (!response.ok) {
            throw new Error(response.statusText);
        }
        return response.status === 204 ? null : response.json();
    });
}

function saveSticker(data, pk, stuck) {
    return apiRequest(data, "PATCH", `/api/metadata/stockitem/${pk}/`, { metadata: { sticker: stuck } });
}

const PRINT_ENDPOINT = "/api/label/print/";
const FIELDS_OF_EVERY_PRINTER = ["template", "plugin", "items"];

function listOf(response) {
    return response?.results ?? response ?? [];
}

/** @implNote InvenTree's own print dialog builds its form the same way: the endpoint's OPTIONS, asked per printer, list that printer's fields. */
async function printerFields(data, printer) {
    const options = await apiRequest(data, "OPTIONS", `${PRINT_ENDPOINT}?plugin=${encodeURIComponent(printer)}`);
    return Object.entries(options?.actions?.POST ?? {})
        .filter(([name, field]) => !FIELDS_OF_EVERY_PRINTER.includes(name) && !field.read_only);
}

async function relatedChoices(data, field) {
    const query = new URLSearchParams(field.filters ?? {}).toString();
    const rows = listOf(await apiRequest(data, "GET", `${field.api_url}${query ? `?${query}` : ""}`));
    return rows.map((row) => ({ value: row.pk, display_name: row.name ?? String(row.pk) }));
}

function choiceSelect(name, choices, chosen) {
    const options = choices.map((choice) =>
        `<option value="${escape(choice.value)}"${String(choice.value) === String(chosen) ? " selected" : ""}>${escape(choice.display_name)}</option>`);
    return `<select data-option="${escape(name)}">${options.join("")}</select>`;
}

async function fieldInput(data, name, field) {
    if (field.type === "boolean") {
        return `<input type="checkbox" data-option="${escape(name)}"${field.default ? " checked" : ""}>`;
    }
    if (field.type === "choice") {
        return choiceSelect(name, field.choices ?? [], field.default);
    }
    if (field.type === "related field") {
        return choiceSelect(name, await relatedChoices(data, field), field.default);
    }
    const kind = ["integer", "float", "decimal"].includes(field.type) ? "number" : "text";
    return `<input type="${kind}" data-option="${escape(name)}" value="${escape(field.default ?? "")}">`;
}

function fieldRow(label, input, help) {
    const hint = help ? `<div style="opacity: 0.6; font-size: 0.8em">${escape(help)}</div>` : "";
    return `<label style="display: block; margin: 4px 0"><div>${escape(label)} ${input}</div>${hint}</label>`;
}

async function printerFieldRows(data, printer) {
    const rows = await Promise.all((await printerFields(data, printer)).map(async ([name, field]) =>
        fieldRow(field.label ?? name, await fieldInput(data, name, field), field.help_text)));
    return rows.join("");
}

function optionValue(input) {
    if (input.type === "checkbox") {
        return input.checked;
    }
    return input.type === "number" && input.value !== "" ? Number(input.value) : input.value;
}

function chosenOptions(form) {
    return Object.fromEntries([...form.querySelectorAll("[data-option]")].map((input) => [input.dataset.option, optionValue(input)]));
}

async function printDialog(data, count) {
    const [templates, printers] = await Promise.all([
        apiRequest(data, "GET", "/api/label/template/?model_type=stockitem&enabled=true"),
        apiRequest(data, "GET", "/api/plugins/?mixin=labels&active=true"),
    ]);
    const templateChoices = listOf(templates).map((entry) => ({ value: entry.pk, display_name: entry.name }));
    const printerChoices = listOf(printers).map((entry) => ({ value: entry.key, display_name: entry.meta?.human_name ?? entry.name }));
    const defaultTemplate = templateChoices.find((choice) => choice.display_name === LABEL_TEMPLATE)?.value;
    return `<div data-print-dialog style="border: 1px solid rgba(128, 128, 128, 0.5); border-radius: 4px; padding: 8px; margin-bottom: 8px">` +
        `<b>Print ${count} labels</b>` +
        fieldRow("Template", choiceSelect("template", templateChoices, defaultTemplate)) +
        fieldRow("Printing plugin", choiceSelect("plugin", printerChoices, LABEL_PRINTER)) +
        `<div data-printer-fields>${await printerFieldRows(data, LABEL_PRINTER)}</div>` +
        `<button type="button" data-dialog="print">Print</button> <button type="button" data-dialog="cancel">Cancel</button></div>`;
}

/** @implNote Printing runs in InvenTree's background worker: the request returns a job, which is polled until it holds the PDF. */
async function printLabels(data, pks, options) {
    let job = await apiRequest(data, "POST", PRINT_ENDPOINT, { ...options, items: pks });
    for (let attempt = 0; !job.complete && attempt < PRINT_POLL_LIMIT; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, PRINT_POLL_MS));
        job = await apiRequest(data, "GET", `/api/data-output/${job.pk}/`);
    }
    if (!job.complete || !job.output) {
        throw new Error(job.errors ? JSON.stringify(job.errors) : "printing did not finish");
    }
    return job.output;
}

function stickerNote(size, stuck) {
    return stuck ? `${size}, stuck on ${stuck}` : size;
}

function doneToggleText(stuck) {
    return stuck ? "✓ done" : "mark done";
}

function stickerRow(row) {
    const indent = `padding-left: ${row.depth * 16}px`;
    if (row.kind === "group") {
        return `<div data-group data-depth="${row.depth}" style="${indent}; margin-top: 6px; font-weight: 600">${escape(row.name)}</div>`;
    }
    return `<div data-sticker data-depth="${row.depth}" data-pk="${row.pk}" data-size="${escape(row.size)}" data-stuck="${escape(row.stuck ?? "")}" ` +
        `data-search="${escape(`${row.id} ${row.name}`.toLowerCase())}" data-category="${escape(row.category ?? "")}" ` +
        `data-places="${escape((row.places ?? []).join(" "))}" style="${indent}; display: flex; align-items: center; gap: 6px">` +
        `<input type="checkbox" data-select title="Select for printing or marking"> ${link(row)} ${escape(row.name)} ` +
        `<button type="button" data-toggle style="font-size: 0.8em; padding: 0 6px; cursor: pointer">${doneToggleText(row.stuck)}</button>` +
        `<span data-note style="opacity: 0.6">${escape(stickerNote(row.size, row.stuck))}</span></div>`;
}

function filterSelect(name, everything, choices, chosen = "") {
    const options = [["", everything], ...choices].map(([value, label]) =>
        `<option value="${escape(value)}"${value === chosen ? " selected" : ""}>${escape(label)}</option>`);
    return `<select data-filter="${name}">${options.join("")}</select>`;
}

function placeSelect(places) {
    const group = (kind, label) => {
        const options = places.filter((place) => place.kind === kind)
            .map((place) => `<option value="${escape(place.key)}">${escape(place.name)}</option>`).join("");
        return options ? `<optgroup label="${label}">${options}</optgroup>` : "";
    };
    return `<select data-filter="place"><option value="">every location</option>${group("location", "Locations")}` +
        `${group("machine", "Machines")}</select>`;
}

const DONE_CHOICES = [["missing", "not done"], ["done", "done"], ["all", "done and not done"]];

function stickerToolbar(context) {
    const done = DONE_CHOICES.map(([value, label]) =>
        `<option value="${value}"${value === "missing" ? " selected" : ""}>${label}</option>`).join("");
    const pairs = (values) => values.map((value) => [value, value]);
    return `<div style="margin-bottom: 6px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px">` +
        `<input type="search" data-filter="search" placeholder="Asset ID or name">` +
        placeSelect(context.places ?? []) +
        filterSelect("category", "every category", pairs(context.categories ?? [])) +
        filterSelect("size", "every size", pairs(context.sizes ?? [])) +
        `<select data-filter="done">${done}</select></div>` +
        `<div style="margin-bottom: 8px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px">` +
        `<b data-progress></b>` +
        `<button type="button" data-action="select-all">Select all shown</button>` +
        `<button type="button" data-action="unselect-all">Unselect all shown</button>` +
        `<button type="button" data-action="print">Print selected</button>` +
        `<button type="button" data-action="done">Mark selected done</button>` +
        `<button type="button" data-action="not-done">Mark selected not done</button>` +
        `<span data-status style="opacity: 0.7"></span></div>`;
}

function stickerFilters(target) {
    const value = (name) => target.querySelector(`[data-filter=${name}]`).value;
    return { search: value("search").trim().toLowerCase(), place: value("place"), category: value("category"),
        size: value("size"), done: value("done") };
}

function stickerMatches(row, filters) {
    const { search, places, category, size, stuck } = row.dataset;
    return (!filters.search || search.includes(filters.search))
        && (!filters.place || places.split(" ").includes(filters.place))
        && (!filters.category || category === filters.category)
        && (!filters.size || size === filters.size)
        && (filters.done === "all" || Boolean(stuck) === (filters.done === "done"));
}

function hasShownSticker(lines, groupIndex) {
    const depth = Number(lines[groupIndex].dataset.depth);
    for (let index = groupIndex + 1; index < lines.length && Number(lines[index].dataset.depth) > depth; index++) {
        if (lines[index].matches("[data-sticker]") && lines[index].style.display !== "none") {
            return true;
        }
    }
    return false;
}

function showWhen(element, visible) {
    element.style.display = visible ? "" : "none";
}

export function renderStickersMenu(target, data) {
    const context = data?.context ?? {};
    const total = context.total ?? 0;
    let stuck = context.stuck ?? 0;
    frame(target, stickerToolbar(context) + (context.rows ?? []).map(stickerRow).join(""));
    if (!target) {
        return;
    }
    const rows = () => [...target.querySelectorAll("div[data-sticker]")];
    const shown = () => rows().filter((row) => row.style.display !== "none");
    const tick = (row) => row.querySelector("input[data-select]");
    const selected = () => shown().filter((row) => tick(row).checked);
    const action = (name) => target.querySelector(`[data-action=${name}]`);
    const status = (text) => { target.querySelector("[data-status]").textContent = text; };

    const update = () => {
        const visible = shown().length;
        const chosen = selected().length;
        target.querySelector("[data-progress]").textContent =
            `${stuck} of ${total} stuck on · ${visible} shown${chosen ? ` · ${chosen} selected` : ""}`;
        showWhen(action("select-all"), chosen < visible);
        showWhen(action("unselect-all"), chosen > 0);
        ["print", "done", "not-done"].forEach((name) => showWhen(action(name), chosen > 0));
    };
    /** @implNote A row the filters hide is unticked too, so the selection is always what is on screen. */
    const filter = () => {
        const filters = stickerFilters(target);
        rows().forEach((row) => {
            const match = stickerMatches(row, filters);
            row.style.display = match ? "flex" : "none";
            if (!match) {
                tick(row).checked = false;
            }
        });
        const lines = [...target.querySelectorAll("div[data-sticker], div[data-group]")];
        lines.forEach((line, index) => {
            if (line.matches("[data-group]")) {
                showWhen(line, hasShownSticker(lines, index));
            }
        });
        update();
    };

    const setDone = (row, done) => {
        const today = new Date().toISOString().slice(0, 10);
        const value = done ? today : null;
        if (Boolean(row.dataset.stuck) === done) {
            return Promise.resolve();
        }
        return saveSticker(data, row.dataset.pk, value).then(() => {
            stuck += done ? 1 : -1;
            row.dataset.stuck = value ?? "";
            row.querySelector("[data-toggle]").textContent = doneToggleText(value);
            row.querySelector("[data-note]").textContent = stickerNote(row.dataset.size, value);
        });
    };
    const markSelected = (done) => {
        const chosen = selected();
        status("saving...");
        Promise.all(chosen.map((row) => setDone(row, done)))
            .then(() => status(`${chosen.length} marked ${done ? "done" : "not done"}`))
            .catch(() => status("saving failed, try again"))
            .finally(filter);
    };
    const tickShown = (checked) => {
        shown().forEach((row) => { tick(row).checked = checked; });
        update();
    };

    target.querySelectorAll("[data-filter]").forEach((input) =>
        input.addEventListener(input.dataset.filter === "search" ? "input" : "change", filter));
    rows().forEach((row) => {
        tick(row).addEventListener("change", update);
        row.querySelector("[data-toggle]").addEventListener("click", () => {
            setDone(row, !row.dataset.stuck)
                .catch(() => status("saving failed, try again"))
                .finally(filter);
        });
    });
    action("select-all").addEventListener("click", () => tickShown(true));
    action("unselect-all").addEventListener("click", () => tickShown(false));
    action("done").addEventListener("click", () => markSelected(true));
    action("not-done").addEventListener("click", () => markSelected(false));
    action("print").addEventListener("click", () => openPrintDialog(target, data, selected().map((row) => Number(row.dataset.pk)), status));
    filter();
}

function openPrintDialog(target, data, pks, status) {
    target.querySelector("[data-print-dialog]")?.remove();
    status("loading print options...");
    printDialog(data, pks.length).then((html) => {
        status("");
        const toolbar = target.querySelector("[data-progress]").parentElement;
        toolbar.insertAdjacentHTML("afterend", html);
        const dialog = target.querySelector("[data-print-dialog]");
        const printerFieldsBox = dialog.querySelector("[data-printer-fields]");
        dialog.querySelector("[data-option=plugin]").addEventListener("change", (event) => {
            printerFieldsBox.innerHTML = "";
            printerFieldRows(data, event.target.value)
                .then((rows) => { printerFieldsBox.innerHTML = rows; })
                .catch((error) => status(`loading options failed: ${error.message}`));
        });
        dialog.querySelector("[data-dialog=cancel]").addEventListener("click", () => dialog.remove());
        dialog.querySelector("[data-dialog=print]").addEventListener("click", () => {
            const options = chosenOptions(dialog);
            dialog.remove();
            status(`printing ${pks.length}...`);
            printLabels(data, pks, options)
                .then((output) => { status(`printed ${pks.length}`); window.open(output, "_blank"); })
                .catch((error) => status(`printing failed: ${error.message}`));
        });
    }).catch((error) => status(`loading print options failed: ${error.message}`));
}
