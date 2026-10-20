export function renderTable(tbody, rows, columns) {
  tbody.replaceChildren(...rows.map((row) => {
    const tr = document.createElement("tr");
    for (const column of columns) {
      const td = document.createElement("td");
      const value = column.value(row);
      if (value instanceof Node) td.append(value);
      else td.textContent = value ?? "";
      if (column.className) td.className = column.className;
      tr.append(td);
    }
    return tr;
  }));
}

export function renderPager(el, { page, pageSize, total }, onPage) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const button = (label, path, enabled, target) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "icon-button";
    b.setAttribute("aria-label", label);
    b.title = label;
    b.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;
    b.disabled = !enabled;
    b.addEventListener("click", () => onPage(target));
    return b;
  };
  const first = total ? (page - 1) * pageSize + 1 : 0;
  const last = Math.min(page * pageSize, total);
  const label = document.createElement("span");
  label.textContent = `${first.toLocaleString("en-US")}–${last.toLocaleString("en-US")} of ${total.toLocaleString("en-US")}`;
  el.replaceChildren(
    label,
    button("Previous page", "M15 6l-6 6 6 6", page > 1, page - 1),
    button("Next page", "M9 6l6 6-6 6", page < pages, page + 1),
  );
}

export function clearPager(el) {
  el.replaceChildren();
}

export function formatMoney(amount, currency) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency, currencyDisplay: "code" }).format(amount);
}

export function formatPrice(amount) {
  const whole = Number.isInteger(amount);
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2,
  }).format(amount);
}

const DAY_FORMAT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

export const formatDay = (iso) => (iso ? DAY_FORMAT.format(new Date(`${iso.slice(0, 10)}T00:00:00Z`)) : "");

export function daysBetween(fromIso, toIso) {
  return Math.round((Date.parse(toIso.slice(0, 10)) - Date.parse(fromIso.slice(0, 10))) / 86_400_000);
}

export function localToday() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export const formatDate = (iso) => (iso ? iso.slice(0, 10) : "");

export const formatDateTime = (iso) => (iso ? `${iso.slice(0, 10)} ${iso.slice(11, 16)}` : "");
