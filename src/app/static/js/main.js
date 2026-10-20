import { clearToken, login, logout, onSessionLost, onSignedIn, refreshSession, setToken } from "./api.js";
import { initChat, setAssistantRoles, startConversation } from "./chat.js";
import * as router from "./router.js";
import * as sidebar from "./sidebar.js";

const appEl = document.getElementById("app");
const loginForm = document.getElementById("login");
const loginError = loginForm.querySelector(".error");
const whoEl = document.getElementById("who");

function showLogin(message = "") {
  clearToken();
  appEl.hidden = true;
  loginForm.hidden = false;
  loginError.textContent = message;
  loginForm.username.focus();
}

function signedIn(body) {
  const routes = router.routesFor(body.role);
  if (!routes.length) {
    logout();
    showLogin("This account has no access to this application.");
    return false;
  }
  setToken(body.access_token);
  whoEl.textContent = `${body.username} · ${body.role}`;
  setAssistantRoles(body.role);
  sidebar.render(routes);
  loginForm.hidden = true;
  appEl.hidden = false;
  router.start(body.role);
  return true;
}

onSignedIn(signedIn);
onSessionLost((message) => {
  router.stop();
  showLogin(message);
});
router.onNavigate(sidebar.setActive);
initChat();

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  loginError.textContent = "";
  const button = loginForm.querySelector("button");
  button.disabled = true;
  try {
    const response = await login(loginForm.username.value, loginForm.password.value);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      loginError.textContent = typeof body.detail === "string" ? body.detail : "Sign-in failed.";
      return;
    }
    loginForm.password.value = "";
    if (signedIn(body)) startConversation(`Signed in as ${body.username}.`);
  } catch (err) {
    loginError.textContent = `Request failed: ${err.message}`;
  } finally {
    button.disabled = false;
  }
});

document.getElementById("logout").addEventListener("click", async () => {
  await logout();
  router.stop();
  showLogin();
});

refreshSession().then((ok) => { if (ok) startConversation("Session restored."); else showLogin(); });
