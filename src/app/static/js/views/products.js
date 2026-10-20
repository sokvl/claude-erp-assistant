import { authFetch, responseProblem } from "../api.js";
import { clearPager, formatMoney, renderPager, renderTable } from "../table.js";

const section = document.querySelector('[data-view="products"]');
const form = document.getElementById("product-filters");
const useCases = form.querySelector(".use-cases");
const problem = section.querySelector(".problem");
const empty = section.querySelector(".empty");
const tbody = section.querySelector("tbody");
const pager = section.querySelector(".pager");

const FACET_SELECTS = ["category", "brand", "architecture", "memory_type"];
const MAX_LISTED_SPECS = 3;

let page = 1;
let loaded = false;
let request = 0;

function keySpecs(product) {
  const specs = product.specs ?? {};
  if (product.category === "GPU") {
    return [specs.vramGb != null ? `${specs.vramGb} GB` : null, specs.architecture].filter(Boolean).join(" · ");
  }
  return Object.entries(specs)
    .slice(0, MAX_LISTED_SPECS)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : value}`)
    .join(" · ");
}

const COLUMNS = [
  {
    className: "wrap",
    value: (p) => {
      const cell = document.createDocumentFragment();
      const sku = document.createElement("span");
      sku.className = "muted";
      sku.textContent = p.sku ?? "";
      cell.append(p.name, sku);
      return cell;
    },
  },
  { value: (p) => p.brand },
  { value: (p) => p.category },
  { value: (p) => formatMoney(p.listPrice, "USD"), className: "num" },
  { value: keySpecs, className: "wrap" },
];

function showMessage({ error = "", message = "" }) {
  problem.textContent = error;
  problem.hidden = !error;
  empty.textContent = message;
  empty.hidden = !message;
}

function fillFacets(facets) {
  for (const name of FACET_SELECTS) {
    const select = form.elements[name];
    select.replaceChildren(select.options[0], ...(facets[name] ?? []).map((value) => new Option(value, value)));
  }
  useCases.replaceChildren(useCases.querySelector("legend"), ...(facets.use_case ?? []).map((value) => {
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.name = "use_case";
    box.value = value;
    label.append(box, value);
    return label;
  }));
}

async function loadFacets() {
  const response = await authFetch("/products/facets");
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(responseProblem(response.status, body.detail));
  fillFacets(body);
}

function query() {
  const params = new URLSearchParams();
  for (const [name, value] of new FormData(form)) {
    const trimmed = value.trim();
    if (trimmed) params.append(name, trimmed);
  }
  params.set("page", page);
  return params;
}

async function load() {
  loaded = true;
  const ticket = ++request;
  showMessage({ message: "Loading…" });
  try {
    const response = await authFetch(`/products?${query()}`);
    const body = await response.json().catch(() => ({}));
    if (ticket !== request) return;
    if (!response.ok) {
      showMessage({ error: responseProblem(response.status, body.detail) });
      return;
    }
    renderTable(tbody, body.items, COLUMNS);
    showMessage({ message: body.items.length ? "" : "No products match these filters." });
    renderPager(pager, body, "products", (target) => { page = target; load(); });
  } catch (err) {
    if (ticket === request) showMessage({ error: `Request failed: ${err.message}` });
  }
}

export async function show() {
  if (loaded) return;
  loaded = true;
  try {
    await loadFacets();
  } catch (err) {
    showMessage({ error: `Could not load the filters: ${err.message}` });
  }
  load();
}

export function reset() {
  request += 1;
  loaded = false;
  page = 1;
  form.reset();
  fillFacets({});
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
