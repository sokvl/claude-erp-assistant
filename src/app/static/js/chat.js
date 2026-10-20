import { authFetch, describeProblem } from "./api.js";
import { loadConversation } from "./conversations.js";
import { refreshHistory } from "./sidebar.js";
import { localToday } from "./table.js";

marked.setOptions({ gfm: true, breaks: true });

const log = document.getElementById("log");
const form = document.getElementById("form");
const input = document.getElementById("input");
const send = document.getElementById("send");
const assistantSelect = document.getElementById("assistant");
const analystOption = assistantSelect.querySelector('option[value="analyst"]');

const suggestionsByAssistant = {
  advisor: [
    'Customer wants to fine-tune a 13B model, budget $2k.',
    'What do we have in stock from NVIDIA?',
  ],
  analyst: [
    'Who were our top 5 customers in Q1 2020?',
    'How much was overdue on 2020-05-31?',
    'Revenue by product category per quarter in 2019.',
  ],
};
const placeholders = {
  advisor: "Type the customer's question. Enter to send, Shift+Enter for a new line.",
  analyst: "Ask about invoices, revenue or payments. Enter to send, Shift+Enter for a new line.",
};

let conversationId = null;
let generation = 0;
let activeChat = null;
let typewriterTimer = null;
const chartUrls = [];

function renderMarkdown(el, raw) {
  const html = DOMPurify.sanitize(marked.parse(raw), { ADD_ATTR: ["target"] });
  el.innerHTML = html;
  el.querySelectorAll("a[href]").forEach((a) => { a.target = "_blank"; a.rel = "noopener noreferrer"; });
}

function add(cls, text) {
  const el = document.createElement("div");
  el.className = cls;
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}

const addNote = (text, kind = "") => add(`note ${kind}`, text);

function addThinking() {
  const el = document.createElement("div");
  el.className = "note thinking";
  el.innerHTML = '<span class="spinner"></span>Thinking…';
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}

function renderSuggestions() {
  const el = document.createElement("div");
  el.className = "suggestion";
  el.id = "suggestion";
  el.innerHTML = '<span class="suggestion-label">Try asking</span><span id="typewriter"></span><span class="cursor">|</span>';
  log.appendChild(el);

  let sIndex = 0, cIndex = 0, deleting = false;
  const typewriterEl = el.querySelector("#typewriter");

  const suggestions = suggestionsByAssistant[assistantSelect.value];

  function tick() {
    const current = suggestions[sIndex];
    if (!deleting) {
      cIndex++;
      typewriterEl.textContent = current.slice(0, cIndex);
      if (cIndex === current.length) {
        typewriterTimer = setTimeout(() => { deleting = true; tick(); }, 1600);
        return;
      }
    } else {
      cIndex--;
      typewriterEl.textContent = current.slice(0, cIndex);
      if (cIndex === 0) {
        deleting = false;
        sIndex = (sIndex + 1) % suggestions.length;
      }
    }
    typewriterTimer = setTimeout(tick, deleting ? 25 : 45);
  }
  tick();
}

function stopSuggestions() {
  clearTimeout(typewriterTimer);
  const el = document.getElementById("suggestion");
  if (el) el.remove();
}

async function addChart(chartId) {
  const el = add("msg assistant chart", "");
  try {
    const response = await authFetch(`/charts/${chartId}/image`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const url = URL.createObjectURL(await response.blob());
    chartUrls.push(url);
    const img = new Image();
    img.alt = "Chart of the figures above";
    img.onload = () => { log.scrollTop = log.scrollHeight; };
    img.src = url;
    el.appendChild(img);
  } catch (err) {
    el.remove();
    addNote(`Could not load the chart: ${err.message}`, "error");
  }
}

function addConfirmation(actionId, invoiceId, consequence) {
  const el = document.createElement("div");
  el.className = "msg assistant confirm";
  el.innerHTML = `
    <div>Close invoice <strong></strong>? <span class="amount"></span> open for <span class="who"></span>.</div>
    <label class="paid-on">Payment received on <input type="date" class="paid-on-date"></label>
    <div class="paid-on-hint">Leave the date empty to close without a payment, as a write-off.</div>
    <div class="confirm-error" hidden></div>
    <div class="confirm-actions">
      <button type="button" class="primary approve">Approve</button>
      <button type="button" class="reject">Reject</button>
    </div>`;
  el.querySelector("strong").textContent = invoiceId;
  el.querySelector(".amount").textContent =
    `${consequence.currency} ${consequence.currentAmountOpen.toLocaleString()}`;
  el.querySelector(".who").textContent = consequence.customerName;
  const dateField = el.querySelector(".paid-on-date");
  dateField.min = consequence.postingDate ?? "";
  dateField.max = localToday();
  dateField.value = consequence.suggestedPaidOn ?? "";
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  el.querySelector(".approve").addEventListener("click", () => decide(actionId, invoiceId, "approve", el, dateField.value || null));
  el.querySelector(".reject").addEventListener("click", () => decide(actionId, invoiceId, "reject", el, null));
}

function describeDecision(invoiceId, body, paidOn) {
  if (body.status === "rejected") return `Close of invoice ${invoiceId} rejected.`;
  if (!body.invoiceClosed) return `Invoice ${invoiceId} was already closed.`;
  return paidOn
    ? `Invoice ${invoiceId} closed, payment received on ${paidOn}.`
    : `Invoice ${invoiceId} closed without a payment date (write-off).`;
}

async function decide(actionId, invoiceId, verb, el, paidOn) {
  const controls = el.querySelectorAll("button, input");
  const problem = el.querySelector(".confirm-error");
  controls.forEach((c) => (c.disabled = true));
  problem.hidden = true;
  try {
    const response = await authFetch(`/pending-actions/${actionId}/${verb}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(verb === "approve" ? { paid_on: paidOn } : {}),
    });
    const body = await response.json().catch(() => ({}));
    if (response.ok) {
      el.querySelector(".confirm-actions").remove();
      addNote(describeDecision(invoiceId, body, paidOn));
    } else if (response.status === 409) {
      el.querySelector(".confirm-actions").remove();
      addNote("This request expired or was already decided.", "error");
    } else {
      controls.forEach((c) => (c.disabled = false));
      problem.textContent = response.status === 422 ? describeProblem(body.detail) : `HTTP ${response.status}: ${describeProblem(body.detail)}`;
      problem.hidden = false;
    }
  } catch (err) {
    controls.forEach((c) => (c.disabled = false));
    addNote(`Request failed: ${err.message}`, "error");
  }
}

function parseEvent(raw) {
  let event = "message";
  const dataLines = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  return dataLines.length ? { event, data: JSON.parse(dataLines.join("\n")) } : null;
}

async function submit(e) {
  e.preventDefault();
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  send.disabled = true;
  stopSuggestions();
  add("msg user", message);
  const turn = generation;
  const controller = new AbortController();
  activeChat = controller;
  const current = () => turn === generation;
  let bubble = null;
  let bubbleRaw = "";
  let lastTool = null;
  let thinking = addThinking();
  const stopThinking = () => { if (thinking) { thinking.remove(); thinking = null; } };

  try {
    const response = await authFetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, message, assistant: assistantSelect.value }),
      signal: controller.signal,
    });
    if (!response.ok) {
      stopThinking();
      const body = await response.json().catch(() => ({}));
      const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
      addNote(`HTTP ${response.status}: ${detail}`, "error");
      if (response.status === 404) conversationId = null;
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finished = false;

    while (true) {
      const { value, done } = await reader.read();
      if (done || !current()) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const parsed = parseEvent(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (!parsed) continue;
        const { event, data } = parsed;

        if (event === "conversation") {
          conversationId = data.conversation_id;
          if (location.hash.startsWith("#/chat")) history.replaceState(null, "", `#/chat/${encodeURIComponent(conversationId)}`);
        } else if (event === "tool") {
          stopThinking();
          if (data.name !== lastTool) addNote(`looking up: ${data.name}`, "tool");
          lastTool = data.name;
        } else if (event === "chart") {
          stopThinking();
          bubble = null;
          bubbleRaw = "";
          addChart(data.chart_id);
        } else if (event === "confirmation_required") {
          stopThinking();
          bubble = null;
          bubbleRaw = "";
          addConfirmation(data.pending_action_id, data.invoice_id, data.consequence);
        } else if (event === "text") {
          stopThinking();
          lastTool = null;
          if (!bubble) bubble = add("msg assistant", "");
          bubbleRaw += data.text;
          renderMarkdown(bubble, bubbleRaw);
          log.scrollTop = log.scrollHeight;
        } else if (event === "done") {
          finished = true;
          refreshHistory();
          if (data.truncated) addNote("Answer was cut off at the length limit.");
        } else if (event === "error") {
          finished = true;
          addNote(`${data.message} (${data.code})`, "error");
        }
      }
    }
    if (!finished && current()) addNote("Connection closed before the answer finished.", "error");
  } catch (err) {
    if (current()) addNote(`Request failed: ${err.message}`, "error");
  } finally {
    stopThinking();
    if (current()) {
      activeChat = null;
      send.disabled = false;
      input.focus();
    }
  }
}

function clearConversation() {
  generation += 1;
  activeChat?.abort();
  activeChat = null;
  send.disabled = false;
  conversationId = null;
  stopSuggestions();
  chartUrls.splice(0).forEach(URL.revokeObjectURL);
  log.innerHTML = "";
}

function leaveConversationRoute() {
  if (location.hash.startsWith("#/chat/")) history.replaceState(null, "", "#/chat");
}

function useAssistant(name) {
  assistantSelect.value = name;
  input.placeholder = placeholders[name];
}

export function startConversation(note) {
  clearConversation();
  addNote(note);
  renderSuggestions();
}

export async function show(id) {
  if (!id || id === conversationId) return;
  const turn = generation;
  const conversation = await loadConversation(id);
  if (turn !== generation || location.hash !== `#/chat/${encodeURIComponent(id)}`) return;
  if (!conversation) {
    leaveConversationRoute();
    startConversation("This conversation can't be reopened yet. Started a new one.");
    return;
  }
  clearConversation();
  conversationId = id;
  useAssistant(conversation.assistant);
  for (const message of conversation.messages) {
    if (message.role === "user") add("msg user", message.content);
    else renderMarkdown(add("msg assistant", ""), message.content);
    (message.chartIds ?? []).forEach(addChart);
  }
}

export function setAssistantRoles(role) {
  const manager = role === "manager";
  analystOption.hidden = !manager;
  analystOption.disabled = !manager;
  if (!manager && assistantSelect.value === "analyst") {
    assistantSelect.value = "advisor";
    input.placeholder = placeholders.advisor;
  }
}

export function reset() {
  startConversation("Signed out.");
}

export function initChat() {
  renderSuggestions();
  document.getElementById("new-chat").addEventListener("click", () => {
    startConversation("New conversation started.");
    location.hash = "#/chat";
  });
  assistantSelect.addEventListener("change", () => {
    input.placeholder = placeholders[assistantSelect.value];
    leaveConversationRoute();
    startConversation(`New conversation with the ${assistantSelect.selectedOptions[0].text.toLowerCase()}.`);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", submit);
}
