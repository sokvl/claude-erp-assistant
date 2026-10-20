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

export function renderPager(el, { page, pageSize, total }, noun, onPage) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const button = (label, enabled, target) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.disabled = !enabled;
    b.addEventListener("click", () => onPage(target));
    return b;
  };
  const label = document.createElement("span");
  label.textContent = `Page ${page.toLocaleString()} of ${pages.toLocaleString()} · ${total.toLocaleString()} ${noun}`;
  el.replaceChildren(button("Previous", page > 1, page - 1), label, button("Next", page < pages, page + 1));
}

export function clearPager(el) {
  el.replaceChildren();
}

export function formatMoney(amount, currency) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
}

export function localToday() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export const formatDate = (iso) => (iso ? iso.slice(0, 10) : "");

export const formatDateTime = (iso) => (iso ? `${iso.slice(0, 10)} ${iso.slice(11, 16)}` : "");
