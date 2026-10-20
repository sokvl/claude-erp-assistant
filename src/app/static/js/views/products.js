import { authFetch, responseProblem } from "../api.js";
import { clearPager, formatPrice, renderPager } from "../table.js";

const section = document.querySelector('[data-view="products"]');
const form = document.getElementById("product-filters");
const categoryChips = form.querySelector(".categories");
const useCaseChips = form.querySelector(".use-cases");
const gpuRow = form.querySelector(".gpu-only");
const sortSelect = form.elements.sort;
const toolbarClear = form.querySelector(".clear");
const problem = section.querySelector(".problem");
const results = section.querySelector(".results");
const count = section.querySelector(".count");
const catalog = section.querySelector(".catalog");
const empty = section.querySelector(".empty");
const pager = section.querySelector(".pager");

const GPU = "GPU";
const DEFAULT_SORT = "name:asc";
const TYPING_DELAY_MS = 300;
const FAMILIES = {
  compute: ["GPU", "CPU", "Motherboard", "Server", "Laptop"],
  memory: ["RAM", "Storage"],
  infrastructure: ["Rack", "UPS", "Networking", "PSU", "Cooling", "Case"],
};

const gb = (n) => (n == null ? null : n >= 1024 ? `${n / 1024} TB` : `${n} GB`);
const join = (...parts) => parts.filter(Boolean).join(" ") || null;

const SPEC_SHEETS = {
  GPU: (s) => [
    ["Memory", join(gb(s.vramGb), s.memoryType)],
    ["Architecture", s.architecture],
    ["FP16 tensor", s.fp16TensorTflopsDense && `${s.fp16TensorTflopsDense} TFLOPS`],
  ],
  Laptop: (s) => [["Processor", s.cpu], ["Memory", join(gb(s.ramGb), s.ramKind)], ["Storage", gb(s.storageGb)]],
  Server: (s) => [["Form factor", s.formFactor], ["Processors", s.cpuModel], ["Memory", join(gb(s.ramGb), s.ramKind)]],
  UPS: (s) => [
    ["Capacity", s.capacityVa && `${s.capacityVa} VA, ${s.capacityWatts} W`],
    ["Topology", s.topology],
    ["Outlets", s.outlets],
  ],
  Rack: (s) => [
    ["Height", s.heightU && `${s.heightU}U`],
    ["Footprint", s.widthMm && `${s.widthMm} × ${s.depthMm} mm`],
    ["Load", s.loadCapacityKg && `${s.loadCapacityKg} kg`],
  ],
};

let page = 1;
let loaded = false;
let request = 0;
let typingTimer = null;
const useCases = new Set();

const plural = (n, word) => `${n.toLocaleString("en-US")} ${word}${n === 1 ? "" : "s"}`;

function family(category) {
  return Object.keys(FAMILIES).find((name) => FAMILIES[name].includes(category)) ?? "peripheral";
}

function element(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

function tile(product) {
  const li = element("li", `tile ${family(product.category)}`);
  const top = element("div", "tile-top");
  top.append(element("span", "category", product.category), element("span", "brand", product.brand));
  li.append(top, element("h3", "tile-name", product.name), element("p", "sku", product.sku));

  const rows = (SPEC_SHEETS[product.category]?.(product.specs ?? {}) ?? []).filter(([, value]) => value != null && value !== "");
  if (rows.length) {
    const dl = element("dl", "specs");
    for (const [label, value] of rows) {
      const row = element("div");
      row.append(element("dt", null, label), element("dd", null, String(value)));
      dl.append(row);
    }
    li.append(dl);
  }

  const tags = product.specs?.useCases ?? [];
  if (tags.length) {
    const ul = element("ul", "tags");
    ul.append(...tags.map((tag) => element("li", null, tag)));
    li.append(ul);
  }

  const price = element("p", "price", formatPrice(product.listPrice));
  price.append(element("span", null, "list price"));
  li.append(price);
  return li;
}

function chip(label, pressed, onClick) {
  const b = element("button", "chip", label);
  b.type = "button";
  b.setAttribute("aria-pressed", String(pressed));
  b.addEventListener("click", onClick);
  return b;
}

function renderCategoryChips(categories) {
  const current = form.elements.category.value;
  categoryChips.replaceChildren(
    chip("All", current === "", () => selectCategory("")),
    ...categories.map((c) => chip(c, current === c, () => selectCategory(c))),
  );
}

function renderUseCaseChips(values) {
  useCaseChips.replaceChildren(...values.map((value) => chip(value, useCases.has(value), (e) => {
    if (useCases.has(value)) useCases.delete(value);
    else useCases.add(value);
    e.currentTarget.setAttribute("aria-pressed", String(useCases.has(value)));
    reload();
  })));
}

function fillSelect(select, values) {
  select.replaceChildren(select.options[0], ...values.map((value) => new Option(value, value)));
}

function fillFacets(facets) {
  renderCategoryChips(facets.category ?? []);
  fillSelect(form.elements.brand, facets.brand ?? []);
  fillSelect(form.elements.architecture, facets.architecture ?? []);
  fillSelect(form.elements.memory_type, facets.memory_type ?? []);
  renderUseCaseChips(facets.use_case ?? []);
}

function syncGpuControls() {
  const gpu = form.elements.category.value === GPU;
  gpuRow.hidden = !gpu;
  if (!gpu) {
    form.elements.architecture.value = "";
    form.elements.memory_type.value = "";
    useCases.clear();
    useCaseChips.querySelectorAll(".chip").forEach((b) => b.setAttribute("aria-pressed", "false"));
    if (sortSelect.selectedOptions[0]?.hasAttribute("data-gpu")) sortSelect.value = DEFAULT_SORT;
  }
  sortSelect.querySelectorAll("[data-gpu]").forEach((option) => { option.hidden = !gpu; });
}

function selectCategory(category) {
  form.elements.category.value = category;
  categoryChips.querySelectorAll(".chip").forEach((b) => {
    b.setAttribute("aria-pressed", String((b.textContent === "All" ? "" : b.textContent) === category));
  });
  syncGpuControls();
  reload();
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
    if (name !== "sort" && trimmed) params.set(name, trimmed);
  }
  useCases.forEach((value) => params.append("use_case", value));
  toolbarClear.hidden = [...params.keys()].length === 0;
  const [sortBy, sortOrder] = (sortSelect.value || DEFAULT_SORT).split(":");
  params.set("sort_by", sortBy);
  params.set("sort_order", sortOrder);
  params.set("page", page);
  return params;
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
  results.classList.add("loading");
  results.setAttribute("aria-busy", "true");
  try {
    const response = await authFetch(`/products?${query()}`);
    const body = await response.json().catch(() => ({}));
    if (ticket !== request) return;
    if (!response.ok) {
      showMessage({ error: responseProblem(response.status, body.detail) });
      return;
    }
    catalog.replaceChildren(...body.items.map(tile));
    count.textContent = body.total ? plural(body.total, "product") : "";
    showMessage({ message: body.items.length ? "" : "No products match these filters." });
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

function reload() {
  page = 1;
  load();
}

function clearFilters() {
  form.reset();
  form.elements.category.value = "";
  useCases.clear();
  categoryChips.querySelectorAll(".chip").forEach((b) => b.setAttribute("aria-pressed", String(b.textContent === "All")));
  syncGpuControls();
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
  clearTimeout(typingTimer);
  loaded = false;
  page = 1;
  clearFilters();
  fillFacets({});
  catalog.replaceChildren();
  count.textContent = "";
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
  typingTimer = setTimeout(reload, e.target.tagName === "SELECT" ? 0 : TYPING_DELAY_MS);
});

section.querySelectorAll(".clear").forEach((b) => b.addEventListener("click", () => {
  clearFilters();
  reload();
}));
