import { authFetch, describeProblem } from "../api.js";
import { formatDate, formatDateTime, renderTable } from "../table.js";

const section = document.querySelector('[data-view="audit"]');
const form = document.getElementById("audit-form");
const problem = section.querySelector(".problem");
const empty = section.querySelector(".empty");
const tableWrap = section.querySelector(".table-wrap");
const tbody = section.querySelector("tbody");

const COLUMNS = [
  { value: (e) => formatDateTime(e.at) },
  { value: (e) => e.type },
  { value: (e) => (e.actor ? `${e.actor.type}: ${e.actor.id}` : "") },
  { value: (e) => formatDate(e.paidOn) },
  { value: (e) => formatDate(e.suggestedPaidOn) },
  { value: (e) => e.reason, className: "wrap" },
  { value: (e) => e.conversationId },
];

let shown = null;
let request = 0;

function showResults({ events = [], message = "", error = "" }) {
  problem.textContent = error;
  problem.hidden = !error;
  empty.textContent = message;
  empty.hidden = !message;
  renderTable(tbody, events, COLUMNS);
  tableWrap.hidden = events.length === 0;
}

async function load(invoiceId) {
  const ticket = ++request;
  showResults({ message: "Loading…" });
  try {
    const response = await authFetch(`/audit/invoices/${encodeURIComponent(invoiceId)}/events`);
    const body = await response.json().catch(() => ({}));
    if (ticket !== request) return;
    if (!response.ok) showResults({ error: `HTTP ${response.status}: ${describeProblem(body.detail)}` });
    else if (!body.events.length) showResults({ message: `No events recorded for invoice ${invoiceId}.` });
    else showResults({ events: body.events });
  } catch (err) {
    if (ticket === request) showResults({ error: `Request failed: ${err.message}` });
  }
}

export function show(invoiceId) {
  if (invoiceId === shown) return;
  shown = invoiceId;
  form.invoice_id.value = invoiceId ?? "";
  if (invoiceId) load(invoiceId);
  else showResults({});
}

export function reset() {
  request += 1;
  shown = null;
  form.reset();
  showResults({});
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const invoiceId = form.invoice_id.value.trim();
  if (!invoiceId) return;
  const target = `#/audit/${encodeURIComponent(invoiceId)}`;
  if (location.hash === target) {
    shown = null;
    show(invoiceId);
  } else {
    location.hash = target;
  }
});
