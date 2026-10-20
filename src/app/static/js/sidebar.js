const shell = document.getElementById("app");
const menu = document.getElementById("menu");
const sidebar = document.getElementById("sidebar");
const backdrop = shell.querySelector(".backdrop");
const items = sidebar.querySelectorAll(".nav-item[data-route]");

export function render(routes) {
  items.forEach((item) => { item.hidden = !routes.includes(item.dataset.route); });
}

export function setActive(route) {
  items.forEach((item) => {
    if (item.dataset.route === route) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  closeDrawer();
}

function openDrawer() {
  shell.classList.add("drawer-open");
  menu.setAttribute("aria-expanded", "true");
  sidebar.querySelector(".nav-item:not([hidden])")?.focus();
}

export function closeDrawer() {
  if (!shell.classList.contains("drawer-open")) return;
  shell.classList.remove("drawer-open");
  menu.setAttribute("aria-expanded", "false");
  if (sidebar.contains(document.activeElement)) menu.focus();
}

menu.addEventListener("click", openDrawer);
backdrop.addEventListener("click", closeDrawer);
items.forEach((item) => item.addEventListener("click", closeDrawer));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
