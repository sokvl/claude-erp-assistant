import { authFetch, responseProblem } from "../api.js";
import { clearPager, daysBetween, formatDay, formatMoney, localToday, renderPager, renderTable } from "../table.js";

const section = document.querySelector('[data-view="invoices"]');
const form = document.getElementById("invoice-filters");
const statusButtons = form.querySelectorAll("[data-status]");
const clearButtons = section.querySelectorAll(".clear");
const toolbarClear = form.querySelector(".clear");
const problem = section.querySelector(".problem");
const results = section.querySelector(".results");
const table = section.querySelector(".ledger");
const tbody = table.querySelector("tbody");
const empty = section.querySelector(".empty");
const pager = section.querySelector(".pager");
const sortHeaders = section.querySelectorAll("th[data-sort]");
const moreToggle = form.querySelector(".more-toggle");
const morePanel = document.getElementById(moreToggle.getAttribute("aria-controls"));

const DEFAULT_SORT = { by: "posting_date", order: "desc" };
const TYPING_DELAY_MS = 300;

let sort = { ...DEFAULT_SORT };
let page = 1;
let loaded = false;
let request = 0;
let typingTimer = null;

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function twoLines(main, sub, subClass = "sub") {
  const cell = document.createDocumentFragment();
  const top = document.createElement("span");
  top.className = "main";
  top.textContent = main;
  const bottom = document.createElement("span");
  bottom.className = subClass;
  bottom.textContent = sub;
  cell.append(top, bottom);
  return cell;
}

function dueState(invoice, asOf) {
  if (!invoice.isOpen) {
    const cleared = invoice.dates.clearDate;
    return { kind: "cleared", text: cleared ? `Cleared ${formatDay(cleared)}` : "Cleared" };
  }
  const days = daysBetween(asOf, invoice.dates.dueInDate);
  if (days < 0) return { kind: "overdue", text: `${plural(-days, "day")} overdue` };
  if (days === 0) return { kind: "open", text: "Due today" };
  return { kind: "open", text: `Due in ${plural(days, "day")}` };
}

function columns(asOf) {
  return [
    { className: "id", value: (i) => i.invoiceId },
    { className: "wrap", value: (i) => twoLines(i.customer.name, i.customer.number) },
    { className: "hide-sm", value: (i) => formatDay(i.dates.postingDate) },
    {
      value: (i) => {
        const state = dueState(i, asOf);
        return twoLines(formatDay(i.dates.dueInDate), state.text, `state ${state.kind}`);
      },
    },
    {
      className: "num",
      value: (i) => {
        const amount = document.createElement("span");
        amount.className = i.amounts.totalOpen ? "amount" : "amount settled";
        amount.textContent = formatMoney(i.amounts.totalOpen, i.currency);
        return amount;
      },
    },
  ];
}

function filters() {
  const params = new URLSearchParams();
  for (const [name, value] of new FormData(form)) {
    const trimmed = value.trim();
    if (trimmed) params.set(name, name === "currency" ? trimmed.toUpperCase() : trimmed);
  }
  return params;
}

function renderControls(params) {
  const status = params.get("status") ?? "";
  statusButtons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.status === status)));
  toolbarClear.hidden = [...params.keys()].length === 0;
  sortHeaders.forEach((th) => {
    const active = th.dataset.sort === sort.by;
    th.setAttribute("aria-sort", active ? (sort.order === "asc" ? "ascending" : "descending") : "none");
    th.querySelector("button").dataset.arrow = active ? (sort.order === "asc" ? "↑" : "↓") : "";
  });
}

function showMessage({ error = "", message = "" }) {
  problem.textContent = error;
  problem.hidden = !error;
  empty.querySelector("p").textContent = message;
  empty.hidden = !message;
}

async function load() {
  loaded = true;
  clearTimeout(typingTimer);
  const ticket = ++request;
  const params = filters();
  const asOf = params.get("as_of") || localToday();
  renderControls(params);
  params.set("sort_by", sort.by);
  params.set("sort_order", sort.order);
  params.set("page", page);
  results.classList.add("loading");
  results.setAttribute("aria-busy", "true");
  try {
    const response = await authFetch(`/invoices?${params}`);
    const body = await response.json().catch(() => ({}));
    if (ticket !== request) return;
    if (!response.ok) {
      showMessage({ error: responseProblem(response.status, body.detail) });
      return;
    }
    renderTable(tbody, body.items, columns(asOf));
    table.hidden = body.items.length === 0;
    showMessage({ message: body.items.length ? "" : "No invoices match these filters." });
    if (body.items.length) renderPager(pager, body, (target) => { page = target; load(); });
    else clearPager(pager);
  } catch (err) {
    if (ticket === request) showMessage({ error: `Request failed: ${err.message}` });
  } finally {
    if (ticket === request) {
      results.classList.remove("loading");
      results.removeAttribute("aria-busy");
    }
  }
}

function clearFilters() {
  form.reset();
  form.elements.status.value = "";
}

function reload() {
  page = 1;
  load();
}

export function show() {
  if (!loaded) load();
}

function setMoreOpen(open) {
  moreToggle.setAttribute("aria-expanded", String(open));
  morePanel.classList.toggle("open", open);
}

export function reset() {
  request += 1;
  setMoreOpen(false);
  clearTimeout(typingTimer);
  loaded = false;
  sort = { ...DEFAULT_SORT };
  page = 1;
  clearFilters();
  tbody.replaceChildren();
  clearPager(pager);
  showMessage({});
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  reload();
});

section.addEventListener("input", (e) => {
  if (e.target.form !== form) return;
  clearTimeout(typingTimer);
  typingTimer = setTimeout(reload, e.target.type === "date" ? 0 : TYPING_DELAY_MS);
});

moreToggle.addEventListener("click", () => {
  setMoreOpen(moreToggle.getAttribute("aria-expanded") !== "true");
});

statusButtons.forEach((b) => b.addEventListener("click", () => {
  form.elements.status.value = b.dataset.status;
  reload();
}));

clearButtons.forEach((b) => b.addEventListener("click", () => {
  clearFilters();
  reload();
}));

sortHeaders.forEach((th) => th.querySelector("button").addEventListener("click", () => {
  sort = th.dataset.sort === sort.by
    ? { by: sort.by, order: sort.order === "asc" ? "desc" : "asc" }
    : { by: th.dataset.sort, order: "desc" };
  reload();
}));
