let accessToken = null;
let refreshing = null;
let signedInHandler = () => true;
let sessionLostHandler = () => {};

export function onSignedIn(handler) { signedInHandler = handler; }
export function onSessionLost(handler) { sessionLostHandler = handler; }

export function setToken(token) { accessToken = token; }
export function clearToken() { accessToken = null; }

export function refreshSession() {
  refreshing ??= fetch("/auth/refresh", { method: "POST" })
    .then(async (response) => response.ok && signedInHandler(await response.json()))
    .catch(() => false)
    .finally(() => { refreshing = null; });
  return refreshing;
}

export async function authFetch(url, options = {}) {
  const request = () => fetch(url, { ...options, headers: { ...options.headers, Authorization: `Bearer ${accessToken}` } });
  let response = await request();
  if (response.status === 401 && await refreshSession()) response = await request();
  if (response.status === 401) sessionLostHandler("Your session ended. Sign in again.");
  return response;
}

export function login(username, password) {
  return fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export function logout() {
  return fetch("/auth/logout", { method: "POST" }).catch(() => {});
}

export function describeProblem(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg).join("; ");
  return "The request was refused.";
}

export function responseProblem(status, detail) {
  return status === 422 ? describeProblem(detail) : `HTTP ${status}: ${describeProblem(detail)}`;
}
