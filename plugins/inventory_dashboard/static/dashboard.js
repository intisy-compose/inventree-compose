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
    return value === null || value === undefined ? "-" : `<b>${value}</b>`;
}

const RESOURCES = {
    cpu: ["CPU", "CPU Mark"], ram_size: ["RAM size", "GB"], ram_speed: ["RAM speed", "MT/s"],
    storage_tb: ["Storage capacity", "TB"], storage_speed: ["Storage speed", "MB/s"], gpu: ["GPU", "G3D Mark"], vram: ["VRAM", "GB"],
};
const SPEED_RESOURCES = ["cpu", "ram_speed", "storage_speed", "gpu"];

function amount(value) {
    return Number(value).toLocaleString("de-DE", { maximumFractionDigits: 2 });
}

function resourceName(resource) {
    return (RESOURCES[resource] ?? [resource])[0];
}

function figureText(resource, value) {
    return `${amount(value)} ${(RESOURCES[resource] ?? [resource, ""])[1]}`;
}

function work(row) {
    const figures = row.figures ?? {};
    const found = Object.keys(RESOURCES).filter((resource) => figures[resource]);
    return found.length ? found.map((resource) => `${resourceName(resource)} ${figureText(resource, figures[resource])}`).join(", ") : "-";
}

function scoreText(value, scale) {
    if (value === null || value === undefined) {
        return "-";
    }
    return scale === "above" ? "100+" : scale === "below" && value === 1 ? "<1" : String(value);
}

function measured(row) {
    const reading = row.measured;
    return reading ? `${watts(reading.idle_w)} / ${watts(reading.load_w)}` : "-";
}

function powerRows(rows) {
    return rows.map((row) => [escape(row.name), watts(row.idle_w), watts(row.average_w), watts(row.load_w), escape(work(row)), score(row.score)]);
}

export function renderPower(target, data) {
    const context = data?.context ?? {};
    const headers = ["", "Idle", "Average", "Load", "Resources", "Score"];
    const machines = table(["Machine", ...headers.slice(1)], powerRows(context.machines ?? []), [1, 2, 3, 4, 5]);
    const locations = table(["Location", ...headers.slice(1)], powerRows(context.locations ?? []), [1, 2, 3, 4, 5]);
    frame(target, `${machines}<br>${locations}<p style="opacity: 0.7; font-size: 0.8em">Average at the server utilisation; ` +
        `score 1 to 100, the weighted mean of each resource's score per average watt. The Efficiency menu shows how.</p>`);
}

function resourcesTable(resources) {
    if (!resources?.length) {
        return "";
    }
    return table(["Resource", "Figure", "Per average watt", "Weight", "Score", "Without the cap"], resources.map((row) => {
        const figure = row.figure ? figureText(row.resource, row.figure) : "none";
        const capped = row.uncapped_figure ? `, could do ${figureText(row.resource, row.uncapped_figure)}` : "";
        return [escape(resourceName(row.resource)), escape(figure + capped), row.figure ? amount(row.efficiency) : "-",
            `${Math.round(row.weight * 100)}%`, `<b>${scoreText(row.score, row.scale)}</b>`,
            row.uncapped_score ? String(row.uncapped_score) : ""];
    }), [2, 3, 4, 5]);
}

function partCap(part) {
    if (!part.cap) {
        return part.figures?.storage_speed ? "port speed unknown" : "";
    }
    const limited = part.uncapped?.storage_speed;
    return limited ? `reads ${amount(limited)} MB/s, counts ${amount(part.cap.speed)} (${escape(part.cap.by)})`
        : `port ${amount(part.cap.speed)} MB/s, not limiting (${escape(part.cap.by)})`;
}

function partsTable(parts) {
    const rows = (parts ?? []).map((part) => {
        const resources = Object.keys(RESOURCES).filter((resource) => part.figures?.[resource]);
        const brings = resources.map((resource) => `${resourceName(resource)} ${figureText(resource, part.figures[resource])}`).join(", ");
        const scores = resources.map((resource) => {
            const own = part.scores?.[resource];
            const uncapped = part.uncapped_scores?.[resource];
            return own ? `${resourceName(resource)} ${scoreText(own.score, own.scale)}${uncapped ? ` (${scoreText(uncapped.score, uncapped.scale)} uncapped)` : ""}` : "";
        }).filter(Boolean).join(", ");
        return [`<a href="/web/stock/item/${part.pk}" style="color: inherit">${escape(part.serial)}</a>`, escape(part.part),
            watts(part.average_w), escape(brings || "-"), escape(scores || (resources.length ? "no watts of its own" : "-")), partCap(part)];
    });
    return table(["Asset", "Part", "Average", "Brings", "Its own scores", "Drive port"], rows, [2]);
}

export function renderPowerPanel(target, data) {
    const row = data?.context ?? {};
    const stats = stat("idle", watts(row.idle_w)) + stat(`average at ${Math.round((row.utilisation ?? 0) * 100)}%`, watts(row.average_w)) +
        stat("load", watts(row.load_w)) + stat("supply loss", watts(row.loss_w)) +
        stat("score", row.score ?? "-") + (row.measured ? stat("measured idle / load", measured(row)) : "");
    const profile = row.profile ? `<p style="opacity: 0.7; font-size: 0.8em">Scored as ${escape(row.profile)}: the weighted mean ` +
        `of each resource's score per average watt. Brings: ${escape(work(row))}.</p>` : "";
    frame(target, stats + profile + resourcesTable(row.resources) + "<br>" + partsTable(row.parts));
}

export function renderPartPower(target, data) {
    const context = data?.context ?? {};
    const scored = context.score;
    const figure = scored ? stat(scored.unit, Number(scored.figure).toLocaleString("de-DE")) + stat(`score (${scored.class})`, scored.score) : "";
    const source = context.source ? `<p style="opacity: 0.7; font-size: 0.8em">${escape(context.source)}</p>` : "";
    frame(target, stat("idle", watts(context.idle_w)) + stat("load", watts(context.load_w)) + figure + source);
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

function explanation(scale) {
    if (!scale) {
        return "";
    }
    const share = Math.round((scale.utilisation ?? 0) * 100);
    const measure = (resource) => `${(RESOURCES[resource] ?? [resource, ""])[1]}${SPEED_RESOURCES.includes(resource) ? ` x ${share}%` : ""} per W`;
    const references = table(["Resource", "Efficiency is", "Score 1 at", "Score 100 at"],
        Object.entries(scale.resources ?? {}).map(([resource, reference]) =>
            [escape(resourceName(resource)), escape(measure(resource)), amount(reference.low), amount(reference.high)]), [2, 3]);
    const profiles = Object.keys(scale.profiles ?? {});
    const weights = table(["Resource", ...profiles], Object.keys(RESOURCES).map((resource) =>
        [escape(resourceName(resource)), ...profiles.map((profile) => `${Math.round((scale.profiles[profile][resource] ?? 0) * 100)}%`)]),
        profiles.map((_, index) => index + 1));
    return heading("How the score is calculated") +
        `<p style="font-size: 0.85em">Each resource of a machine has an <b>efficiency</b>: its figure per average watt, where the ` +
        `average is idle plus ${share}% of the way to load. Speeds (CPU, RAM speed, storage speed, GPU) count at that ${share}% use, ` +
        `capacities (RAM, storage, VRAM) in full. Its <b>score</b> is 1 + 99 x log(efficiency / low) / log(high / low): every ` +
        `doubling of efficiency adds the same number of points. Low and high are fixed points, not the best thing you own, so a ` +
        `score never moves because something new was bought. Scores are kept between 1 and 100: <b>100+</b> means the efficiency is ` +
        `above the high point, <b>&lt;1</b> below the low one, so a score cannot exceed 100. A resource a machine lacks scores 1.</p>` +
        `<p style="font-size: 0.85em">A <b>machine's score</b> is the mean of its resources' scores, weighted by its profile; a ` +
        `<b>location's</b> is the mean of its machines' scores, weighted by their average watts. A part's own scores use its own ` +
        `watts. A drive counts at most at the speed of the port it sits on (an enclosure's or dock's link, a board's or ` +
        `controller's SATA or NVMe ports).</p>` + references + "<br>" + weights;
}

export function renderEfficiencyMenu(target, data) {
    const context = data?.context ?? {};
    if (context.missing) {
        frame(target, `<p style="opacity: 0.7">No power settings yet: run the catalog tool's sync.</p>`);
        return;
    }
    const powerRow = (row, first) => [first, cell(watts(row.idle_w), row.idle_w), cell(watts(row.average_w), row.average_w),
        cell(watts(row.load_w), row.load_w), cell(escape(work(row)), row.cpu_mark || row.terabytes), cell(score(row.score), row.score ?? -1)];
    const headers = ["Idle", "Average", "Load", "Resources", "Score"];
    const machines = sortableTable(["Machine", "Profile", ...headers], (context.machines ?? []).map((row) => {
        const [first, ...rest] = powerRow(row, cell(`<a href="${row.url}" style="color: inherit">${escape(row.name)}</a>`, row.name));
        return [first, cell(escape(row.profile ?? "-"), row.profile ?? ""), ...rest];
    }), [2, 3, 4, 5, 6]);
    const locations = sortableTable(["Location", ...headers], (context.locations ?? []).map((row) =>
        powerRow(row, cell(escape(row.name), row.name))), [1, 2, 3, 4, 5]);
    const parts = (context.machines ?? []).map((row) =>
        `<details><summary>${escape(row.name)}${row.score ? `, score ${row.score}` : ""}${row.capped ? ", storage capped by its ports" : ""}` +
        `</summary>${resourcesTable(row.resources)}<br>${partsTable(row.parts)}</details>`).join("");
    frame(target, heading("Machines") + machines + heading("Locations") + locations + heading("Each machine: its resources and parts") +
        parts + explanation(context.scale));
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
