const $ = (id) => document.getElementById(id);
const detailPage = Boolean($("detailContent"));

if (detailPage) {
  initDetail();
} else {
  initList();
}

function initList() {
  const form = $("queryForm");
  const principal = $("principalInput");
  const token = $("tokenInput");
  const channel = $("channelInput");
  const recipient = $("recipientInput");
  const status = $("statusText");
  const meta = $("resultMeta");
  const list = $("messageList");
  const errorBanner = $("errorBanner");
  const latest = $("latestButton");
  const previous = $("previousButton");
  const next = $("nextButton");
  let active = null;
  let nextCursor = null;
  let cursorStack = [];
  let busy = false;

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    run(readInputs(null), true);
  });
  latest.addEventListener("click", () => {
    if (active) run({ ...active, cursor: null }, true);
  });
  next.addEventListener("click", () => {
    if (active && nextCursor) run({ ...active, cursor: nextCursor }, false);
  });
  previous.addEventListener("click", () => {
    if (active && cursorStack.length) {
      run({ ...active, cursor: cursorStack[cursorStack.length - 1] }, false, true);
    }
  });

  function readInputs(cursor) {
    const query = { principal: principal.value.trim(), token: token.value, cursor };
    if (channel.value.trim()) query.channel_id = channel.value.trim();
    if (recipient.checked) query.only_my_recipient = true;
    return query;
  }

  async function run(query, reset, goingBack = false) {
    if (busy) return;
    setBusy(true);
    clearError();
    try {
      const body = await request("/v1/messages", query);
      renderResult(body, query);
      if (reset) {
        cursorStack = [];
      } else if (goingBack) {
        cursorStack.pop();
      } else {
        cursorStack.push(active.cursor);
      }
      active = query;
      nextCursor = body.next_cursor;
      status.textContent = "Ready";
    } catch (error) {
      showError(error.message || "request failed");
    } finally {
      setBusy(false);
    }
  }

  function setBusy(value) {
    busy = value;
    document.body.classList.toggle("busy", value);
    document.body.setAttribute("aria-busy", String(value));
    if (value) status.textContent = "Loading";
    document.querySelectorAll("button,input").forEach((control) => {
      control.disabled = value;
    });
    previous.disabled = value || cursorStack.length === 0;
    next.disabled = value || !nextCursor;
    latest.disabled = value || !active;
  }

  function showError(message) {
    status.textContent = "Error";
    errorBanner.textContent = message;
    errorBanner.hidden = false;
  }

  function clearError() {
    errorBanner.textContent = "";
    errorBanner.hidden = true;
  }

  function renderResult(body, query) {
    const messages = body.messages;
    const cards = messages.map((message) => renderMessage(message, query));
    if (!messages.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = query.cursor === null
        ? "No visible messages found."
        : "No earlier matching messages.";
      cards.push(empty);
    }
    const channelText = body.channel
      ? `${body.channel.channel_name || body.channel.channel_id} (${body.channel.channel_id}, ${body.channel.channel_protocol || "not set"})`
      : "all channels";
    const recipientText = query.only_my_recipient
      ? "only messages addressed to this principal"
      : "all visible messages";
    const title = `History for ${query.principal} · ${channelText}`;
    const summary = ` ${messages.length} message${messages.length === 1 ? "" : "s"} · ${recipientText}`;
    list.replaceChildren(...cards);
    $("resultTitle").textContent = title;
    meta.textContent = summary;
  }

  function renderMessage(message, query) {
    const card = document.createElement("article");
    card.className = "message-card";
    const summary = renderMessageMetadata(message, "message-summary");
    if (message.payload.truncated) {
      const actions = document.createElement("div");
      actions.className = "message-actions";
      const detail = document.createElement("button");
      detail.type = "button";
      detail.textContent = "View complete payload";
      detail.addEventListener("click", () => {
        openDetail(message.seq, query, setBusy, showError, clearError);
      });
      actions.appendChild(detail);
      summary.appendChild(actions);
    }
    card.append(summary, renderPayload(message.payload, { collapsible: true }));
    return card;
  }
}

async function request(url, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 35000);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: controller.signal,
    });
    let result;
    try {
      result = await response.json();
    } catch {
      throw new Error(`The HTTP ${response.status} response body is incomplete or contains invalid JSON.`);
    }
    if (!response.ok) throw new Error(result.error?.message || `HTTP ${response.status}`);
    return result;
  } catch (error) {
    if (controller.signal.aborted) throw new Error("request timed out after 35 seconds");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function renderPayload(payload, { collapsible = false } = {}) {
  const panel = document.createElement(collapsible ? "details" : "div");
  panel.className = "payload-panel";
  if (collapsible) panel.open = !payload.truncated;
  const title = document.createElement(collapsible ? "summary" : "h2");
  title.textContent = "Payload";
  panel.appendChild(title);
  const metadata = document.createElement(collapsible ? "span" : "div");
  metadata.className = "payload-meta";
  metadata.textContent = `encoding: ${payload.encoding} · size: ${payload.size_bytes} bytes`;
  (collapsible ? title : panel).appendChild(metadata);
  if (collapsible && payload.truncated) {
    function showPreview() {
      if (!panel.open) return;
      renderPayloadContent(panel, payload);
      panel.removeEventListener("toggle", showPreview);
    }
    panel.addEventListener("toggle", showPreview);
  } else {
    renderPayloadContent(panel, payload);
  }
  return panel;
}

function renderPayloadContent(panel, payload) {
  if (payload.preview) {
    const pre = document.createElement("pre");
    pre.textContent = `omitted: ${payload.preview.omitted_bytes} bytes\n\nHEAD\n${payload.preview.head}\n\nTAIL\n${payload.preview.tail}`;
    panel.appendChild(pre);
  } else {
    const text = payload.text;
    const pre = document.createElement("pre");
    let formatted;
    if (payload.encoding === "utf-8") {
      try {
        formatted = JSON.stringify(JSON.parse(text), null, 2);
        pre.className = "json-text";
      } catch (_) {
        // Keep the original text if parsing or formatting is unavailable.
      }
    }
    pre.textContent = formatted ?? text;
    if (formatted !== undefined && formatted !== text) {
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "payload-toggle";
      toggle.textContent = "View original text";
      let original = false;
      toggle.addEventListener("click", () => {
        original = !original;
        pre.textContent = original ? text : formatted;
        toggle.textContent = original ? "View JSON" : "View original text";
      });
      panel.appendChild(toggle);
    }
    panel.appendChild(pre);
  }
}

function renderMessageMetadata(message, className) {
  const meta = document.createElement("div");
  meta.className = className;
  [
    ["seq", message.seq],
    ["uuid", message.uuid],
    ["time", formatTime(message.ts_ms)],
    ["channel", `${message.channel_id} ${message.channel_name} · ${message.channel_protocol || "not set"}`],
    ["principal", message.principal],
    ["recipients", message.recipients.join(", ") || "[]"],
    ["objects", message.object_ids.join(", ") || "[]"],
  ].forEach(([name, value]) => {
    const field = document.createElement("div");
    field.className = "field";
    const label = document.createElement("span");
    label.className = "field-name";
    label.textContent = name;
    const text = document.createElement("span");
    text.className = "field-value";
    text.textContent = String(value);
    field.append(label, text);
    meta.appendChild(field);
  });
  return meta;
}

function formatTime(value) {
  const date = new Date(Number(value));
  return Number.isNaN(date.getTime()) ? value : date.toISOString();
}

function openDetail(seq, query, setBusy, showError, clearError) {
  const status = $("statusText");
  setBusy(true);
  clearError();
  const target = `${location.origin}/message?seq=${encodeURIComponent(seq)}`;
  let child = null;
  let timer = null;
  const handler = (event) => {
    if (
      event.origin !== location.origin ||
      event.source !== child ||
      event.data?.type !== "openevent-view:ready" ||
      event.data.seq !== String(seq)
    ) {
      return;
    }
    clearTimeout(timer);
    window.removeEventListener("message", handler);
    child.postMessage(
      {
        type: "openevent-view:credentials",
        seq: String(seq),
        principal: query.principal,
        token: query.token,
      },
      location.origin,
    );
    status.textContent = "Ready";
    setBusy(false);
  };
  window.addEventListener("message", handler);
  child = window.open(target, "_blank");
  if (!child) {
    window.removeEventListener("message", handler);
    showError("allow pop-ups and try again");
    setBusy(false);
    return;
  }
  timer = setTimeout(() => {
    window.removeEventListener("message", handler);
    showError("detail page did not receive credentials");
    setBusy(false);
  }, 5000);
}

function initDetail() {
  const seq = new URL(location.href).searchParams.get("seq");
  const form = $("credentialForm");
  const status = $("detailStatus");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const credentials = { principal: $("detailPrincipal").value.trim(), token: $("detailToken").value };
    form.reset();
    load(credentials);
  });

  const timer = setTimeout(showCredentialForm, 5000);
  const handler = (event) => {
    if (
      event.origin !== location.origin ||
      event.source !== window.opener ||
      event.data?.type !== "openevent-view:credentials" ||
      event.data.seq !== seq
    ) {
      return;
    }
    clearTimeout(timer);
    window.removeEventListener("message", handler);
    load({ principal: event.data.principal, token: event.data.token });
    window.opener = null;
  };
  window.addEventListener("message", handler);
  if (window.opener) {
    window.opener.postMessage({ type: "openevent-view:ready", seq }, location.origin);
  } else {
    showCredentialForm();
  }

  async function load(credentials) {
    form.hidden = true;
    status.textContent = "Loading";
    try {
      const body = await request(
        `/v1/messages/${encodeURIComponent(seq)}/payload`,
        credentials,
      );
      $("detailContent").appendChild(renderDetailMessage(body.message));
      status.textContent = "Ready";
    } catch (error) {
      showCredentialForm(error.message || "request failed");
    } finally {
      credentials.principal = null;
      credentials.token = null;
    }
  }

  function showCredentialForm(errorMessage = "") {
    clearTimeout(timer);
    window.removeEventListener("message", handler);
    window.opener = null;
    const error = $("detailError");
    error.textContent = errorMessage;
    error.hidden = !errorMessage;
    form.hidden = false;
    status.textContent = errorMessage ? "Error" : "Enter credentials";
  }
}

function renderDetailMessage(message) {
  const container = document.createElement("div");
  container.append(renderMessageMetadata(message, "detail-meta"), renderPayload(message.payload));
  return container;
}
