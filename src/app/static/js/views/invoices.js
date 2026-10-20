import { authFetch, responseProblem } from "../api.js";
import { clearPager, formatDate, formatMoney, localToday, renderPager, renderTable } from "../table.js";

const section = document.querySelector('[data-view="invoices"]');
const form = document.getElementById("invoice-filters");
const problem = section.querySelector(".problem");
const empty = section.querySelector(".empty");
const tbody = section.querySelector("tbody");
const pager = section.querySelector(".pager");
const sortHeaders = section.querySelectorAll("th[data-sort]");

const DEFAULT_SORT = { by: "posting_date", order: "desc" };

let sort = { ...DEFAULT_SORT };
let page = 1;
let loaded = false;
let request = 0;

function statusOf(invoice, asOf) {
  if (!invoice.isOpen) return "cleared";
  return formatDate(invoice.dates.dueInDate) < asOf ? "overdue" : "open";
}

function columns(asOf) {
  return [
    { value: (i) => i.invoiceId },
    {
      className: "wrap",
      value: (i) => {
        const cell = document.createDocumentFragment();
        const number = document.createElement("span");
        number.className = "muted";
        number.textContent = i.customer.number;
        cell.append(i.customer.name, number);
        return cell;
      },
    },
    { value: (i) => formatDate(i.dates.postingDate) },
    { value: (i) => formatDate(i.dates.dueInDate) },
    { className: "num", value: (i) => formatMoney(i.amounts.totalOpen, i.currency) },
    {
      value: (i) => {
        const badge = document.createElement("span");
        const status = statusOf(i, asOf);
        badge.className = `status ${status}`;
        badge.textContent = status;
        return badge;
      },
    },
    { value: (i) => formatDate(i.dates.clearDate) },
  ];
}

function query() {
  const params = new URLSearchParams();
  for (const [name, value] of new FormData(form)) {
    const trimmed = value.trim();
    if (trimmed) params.set(name, name === "currency" ? trimmed.toUpperCase() : trimmed);
  }
  params.set("sort_by", sort.by);
  params.set("sort_order", sort.order);
  params.set("page", page);
  return params;
}

function renderSort() {
  sortHeaders.forEach((th) => {
    const active = th.dataset.sort === sort.by;
    th.setAttribute("aria-sort", active ? (sort.order === "asc" ? "ascending" : "descending") : "none");
    th.querySelector("button").dataset.arrow = active ? (sort.order === "asc" ? " ↑" : " ↓") : "";
  });
}

function showMessage({ error = "", message = "" }) {
  problem.textContent = error;
  problem.hidden = !error;
  empty.textContent = message;
  empty.hidden = !message;
}

async function load() {
  loaded = true;
  const ticket = ++request;
  const params = query();
  const asOf = params.get("as_of") || localToday();
  renderSort();
  showMessage({ message: "Loading…" });
  try {
    const response = await authFetch(`/invoices?${params}`);
    const body = await response.json().catch(() => ({}));
    if (ticket !== request) return;
    if (!response.ok) {
      showMessage({ error: responseProblem(response.status, body.detail) });
      return;
    }
    renderTable(tbody, body.items, columns(asOf));
    showMessage({ message: body.items.length ? "" : "No invoices match these filters." });
    renderPager(pager, body, "invoices", (target) => { page = target; load(); });
  } catch (err) {
    if (ticket === request) showMessage({ error: `Request failed: ${err.message}` });
  }
}

export function show() {
  if (!loaded) load();
}

export function reset() {
  request += 1;
  loaded = false;
  sort = { ...DEFAULT_SORT };
  page = 1;
  form.reset();
  tbody.replaceChildren();
  clearPager(pager);
  showMessage({});
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  page = 1;
  load();
});

form.querySelector(".clear").addEventListener("click", () => {
  form.reset();
  page = 1;
  load();
});

sortHeaders.forEach((th) => th.querySelector("button").addEventListener("click", () => {
  sort = th.dataset.sort === sort.by
    ? { by: sort.by, order: sort.order === "asc" ? "desc" : "asc" }
    : { by: th.dataset.sort, order: "desc" };
  page = 1;
  load();
}));
