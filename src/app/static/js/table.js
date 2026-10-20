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

export const formatDate = (iso) => (iso ? iso.slice(0, 10) : "");

export const formatDateTime = (iso) => (iso ? `${iso.slice(0, 10)} ${iso.slice(11, 16)}` : "");
