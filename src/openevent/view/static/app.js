const form = document.getElementById("queryForm");
const principalInput = document.getElementById("principalInput");
const tokenInput = document.getElementById("tokenInput");
const channelInput = document.getElementById("channelInput");
const recipientInput = document.getElementById("recipientInput");
const statusText = document.getElementById("statusText");
const resultMeta = document.getElementById("resultMeta");
const messageList = document.getElementById("messageList");
const nextButton = document.getElementById("nextButton");
const searchButton = document.getElementById("searchButton");

let nextCursor = null;
let lastQuery = null;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  nextCursor = null;
  messageList.innerHTML = "";
  lastQuery = buildQuery(null);
  await fetchMessages(lastQuery, false);
});

nextButton.addEventListener("click", async () => {
  if (!lastQuery || !nextCursor) return;
  const query = { ...lastQuery, cursor: nextCursor };
  await fetchMessages(query, true);
});

function buildQuery(cursor) {
  const query = {
    principal: principalInput.value.trim(),
    token: tokenInput.value,
    cursor,
    order: "desc",
  };
  const channel = channelInput.value.trim();
  if (channel) query.channel_id = channel;
  if (recipientInput.checked) query.only_my_recipient = true;
  return query;
}

async function fetchMessages(query, append) {
  setBusy(true);
  try {
    const response = await fetch("/v1/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(query),
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.error?.message || `HTTP ${response.status}`);
    }
    nextCursor = body.next_cursor || null;
    nextButton.disabled = !body.has_more || !nextCursor;
    renderMessages(body.messages || [], append);
    const count = body.messages ? body.messages.length : 0;
    resultMeta.textContent = `${append ? "Appended" : "Returned"} ${count} message${count === 1 ? "" : "s"}, scanned ${body.scanned || 0}, more available: ${body.has_more ? "yes" : "no"}`;
    statusText.textContent = "Ready";
  } catch (error) {
    renderError(error.message || String(error), append);
    statusText.textContent = "Error";
    nextButton.disabled = true;
  } finally {
    setBusy(false);
  }
}

function setBusy(isBusy) {
  searchButton.disabled = isBusy;
  nextButton.disabled = isBusy || !nextCursor;
  statusText.textContent = isBusy ? "Loading" : statusText.textContent;
}

function renderMessages(messages, append) {
  if (!append) {
    messageList.innerHTML = "";
  }
  if (!messages.length && !append) {
    messageList.innerHTML = '<div class="empty-state">No visible messages found.</div>';
    return;
  }
  for (const message of messages) {
    messageList.appendChild(renderMessage(message));
  }
}

function renderError(message, append) {
  if (!append) {
    messageList.innerHTML = "";
  }
  const node = document.createElement("div");
  node.className = "error-state";
  node.textContent = message;
  messageList.prepend(node);
}

function renderMessage(message) {
  const article = document.createElement("article");
  article.className = "message-card";
  article.appendChild(renderSummary(message));
  article.appendChild(renderPayload(message.payload));
  return article;
}

function renderSummary(message) {
  const summary = document.createElement("div");
  summary.className = "message-summary";
  const fields = [
    ["seq", message.seq],
    ["channel", formatChannel(message)],
    ["time", formatTime(message.ts_ms)],
    ["principal", message.principal],
    ["recipients", (message.recipients || []).join(", ") || "[]"],
  ];
  for (const [name, value] of fields) {
    const field = document.createElement("div");
    field.className = "field";
    field.innerHTML = `<span class="field-name"></span><span class="field-value"></span>`;
    field.querySelector(".field-name").textContent = name;
    field.querySelector(".field-value").textContent = String(value);
    summary.appendChild(field);
  }
  return summary;
}

function renderPayload(payload) {
  const panel = document.createElement("div");
  panel.className = "payload-panel";
  const title = document.createElement("h2");
  title.className = "payload-title";
  title.textContent = "payload";
  panel.appendChild(title);

  if (payload && payload.json !== null && payload.json !== undefined) {
    const tree = document.createElement("div");
    tree.className = "json-tree";
    tree.appendChild(renderJsonNode(payload.json, "payload"));
    panel.appendChild(tree);
    return panel;
  }

  const text = document.createElement("pre");
  text.className = "payload-text";
  const details = [];
  if (payload?.encoding) details.push(`encoding: ${payload.encoding}`);
  if (payload?.json_error) details.push(payload.json_error);
  if (payload?.truncated) details.push("truncated");
  text.textContent = `${details.join(" | ")}\n\n${payload?.text || ""}`;
  panel.appendChild(text);
  return panel;
}

function renderJsonNode(value, label) {
  if (Array.isArray(value)) {
    const details = document.createElement("details");
    details.open = true;
    const summary = document.createElement("summary");
    summary.innerHTML = `<span class="json-key"></span> <span>[${value.length}]</span>`;
    summary.querySelector(".json-key").textContent = label;
    details.appendChild(summary);
    value.forEach((item, index) => details.appendChild(renderJsonNode(item, String(index))));
    return details;
  }
  if (value && typeof value === "object") {
    const keys = Object.keys(value);
    const details = document.createElement("details");
    details.open = true;
    const summary = document.createElement("summary");
    summary.innerHTML = `<span class="json-key"></span> <span>{${keys.length}}</span>`;
    summary.querySelector(".json-key").textContent = label;
    details.appendChild(summary);
    for (const key of keys) {
      details.appendChild(renderJsonNode(value[key], key));
    }
    return details;
  }
  const line = document.createElement("div");
  const type = value === null ? "null" : typeof value;
  line.innerHTML = `<span class="json-key"></span>: <span></span>`;
  line.querySelector(".json-key").textContent = label;
  const valueNode = line.querySelector("span:last-child");
  valueNode.className = `json-${type}`;
  valueNode.textContent = value === null ? "null" : JSON.stringify(value);
  return line;
}

function formatChannel(message) {
  const id = message.channel_id ?? "";
  const name = message.channel_name;
  if (!name) return String(id);
  return `${id} ${name}`;
}

function formatTime(tsMs) {
  if (!tsMs) return "";
  const date = new Date(Number(tsMs));
  if (Number.isNaN(date.getTime())) return String(tsMs);
  return date.toISOString();
}
