import { listConversations } from "./conversations.js";

const shell = document.getElementById("app");
const historyEl = document.getElementById("history");
const menu = document.getElementById("menu");
const sidebar = document.getElementById("sidebar");
const backdrop = shell.querySelector(".backdrop");
const items = sidebar.querySelectorAll(".nav-item[data-route]");

export function render(routes, { username, role }) {
  sidebar.querySelectorAll("[data-route]").forEach((el) => { el.hidden = !routes.includes(el.dataset.route); });
  sidebar.querySelector(".avatar").textContent = username.charAt(0);
  sidebar.querySelector(".user-name").textContent = username;
  sidebar.querySelector(".user-role").textContent = role;
}

export function setActive(route) {
  items.forEach((item) => {
    if (item.dataset.route === route) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  markHistory();
  closeDrawer();
}

function markHistory() {
  historyEl.querySelectorAll("a").forEach((link) => {
    if (link.getAttribute("href") === location.hash) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function heading(text) {
  const h = document.createElement("h2");
  h.textContent = text;
  return h;
}

function note(text) {
  const p = document.createElement("p");
  p.className = "history-note";
  p.textContent = text;
  return p;
}

function historyLink(conversation) {
  const link = document.createElement("a");
  link.className = "history-item";
  link.href = `#/chat/${encodeURIComponent(conversation.id)}`;
  link.textContent = conversation.title;
  link.title = conversation.title;
  link.addEventListener("click", closeDrawer);
  return link;
}

export async function refreshHistory() {
  const { items, placeholder } = await listConversations();
  if (placeholder) {
    historyEl.replaceChildren(heading("History"), note("Chat history will appear here."));
    return;
  }
  if (!items.length) {
    historyEl.replaceChildren(heading("History"), note("No conversations yet."));
    return;
  }
  const today = new Date().toDateString();
  const isToday = (c) => new Date(c.lastMessageAt).toDateString() === today;
  const groups = [["Today", items.filter(isToday)], ["Earlier", items.filter((c) => !isToday(c))]];
  historyEl.replaceChildren(...groups.filter(([, group]) => group.length).flatMap(([label, group]) => [heading(label), ...group.map(historyLink)]));
  markHistory();
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
