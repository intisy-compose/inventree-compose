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
        stat("small", counts.small ?? 0) + stat("no sticker", counts.none ?? 0) + untagged);
}

function watts(value) {
    return value === null || value === undefined ? "-" : `${Number(value).toLocaleString("de-DE", { maximumFractionDigits: 1 })} W`;
}

function score(value) {
    return value === null || value === undefined ? "-" : `<b>${value}</b>`;
}

function work(row) {
    if (row.job === "compute") {
        return `${row.cpu_mark.toLocaleString("de-DE")} CPU Mark`;
    }
    return row.job === "storage" ? `${row.terabytes} TB` : "-";
}

function measured(row) {
    const reading = row.measured;
    return reading ? `${watts(reading.idle_w)} / ${watts(reading.load_w)}` : "-";
}

function powerRows(rows) {
    return rows.map((row) => [escape(row.name), watts(row.idle_w), watts(row.average_w), watts(row.load_w), work(row), score(row.score)]);
}

export function renderPower(target, data) {
    const context = data?.context ?? {};
    const headers = ["", "Idle", "Average", "Load", "Work", "Score"];
    const machines = table(["Machine", ...headers.slice(1)], powerRows(context.machines ?? []), [1, 2, 3, 4, 5]);
    const locations = table(["Location", ...headers.slice(1)], powerRows(context.locations ?? []), [1, 2, 3, 4, 5]);
    frame(target, `${machines}<br>${locations}<p style="opacity: 0.7; font-size: 0.8em">Average at the server utilisation; ` +
        `score 1 to 100 on a log scale of work per average watt, with fixed references.</p>`);
}

export function renderPowerPanel(target, data) {
    const row = data?.context ?? {};
    const stats = stat("idle", watts(row.idle_w)) + stat(`average at ${Math.round((row.utilisation ?? 0) * 100)}%`, watts(row.average_w)) +
        stat("load", watts(row.load_w)) + stat("supply loss", watts(row.loss_w)) + stat("work", work(row)) +
        stat("score", row.score ?? "-") + (row.measured ? stat("measured idle / load", measured(row)) : "");
    const parts = (row.parts ?? []).map((part) => [`<a href="/web/stock/item/${part.pk}" style="color: inherit">${escape(part.serial)}</a>`,
        escape(part.part), watts(part.idle_w), watts(part.load_w)]);
    frame(target, stats + (parts.length ? table(["Asset", "Part", "Idle", "Load"], parts, [2, 3]) : ""));
}

export function renderPartPower(target, data) {
    const context = data?.context ?? {};
    const scored = context.score;
    const figure = scored ? stat(scored.unit, Number(scored.figure).toLocaleString("de-DE")) + stat(`score (${scored.class})`, scored.score) : "";
    const source = context.source ? `<p style="opacity: 0.7; font-size: 0.8em">${escape(context.source)}</p>` : "";
    frame(target, stat("idle", watts(context.idle_w)) + stat("load", watts(context.load_w)) + figure + source);
}
