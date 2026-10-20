import * as chat from "./chat.js";
import * as audit from "./views/audit.js";
import * as invoices from "./views/invoices.js";

const ROUTES = {
  chat: { roles: ["consultant", "manager"], view: chat },
  invoices: { roles: ["manager"], view: invoices },
  audit: { roles: ["admin"], view: audit },
};

let role = null;
let navigated = () => {};

export function routesFor(someRole) {
  return Object.keys(ROUTES).filter((name) => ROUTES[name].roles.includes(someRole));
}

export function onNavigate(handler) { navigated = handler; }

function parse() {
  const [, name = "", ...rest] = location.hash.split("/");
  return { name, arg: rest.length ? decodeURIComponent(rest.join("/")) : null };
}

function render() {
  if (!role) return;
  const { name, arg } = parse();
  if (!ROUTES[name]?.roles.includes(role)) {
    location.replace(`#/${routesFor(role)[0]}`);
    return;
  }
  document.querySelectorAll("[data-view]").forEach((section) => { section.hidden = section.dataset.view !== name; });
  navigated(name);
  ROUTES[name].view.show(arg);
}

export function start(signedInRole) {
  role = signedInRole;
  render();
}

export function stop() {
  role = null;
  Object.values(ROUTES).forEach(({ view }) => view.reset());
  history.replaceState(null, "", location.pathname);
}

window.addEventListener("hashchange", render);
