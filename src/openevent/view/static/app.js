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
  let currentCursor = null;
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
    const prior = { active, currentCursor, nextCursor, cursorStack };
    try {
      const body = await request("/v1/messages", query);
      if (reset) {
        active = { ...query, cursor: null };
        currentCursor = null;
        cursorStack = [];
      } else if (goingBack) {
        cursorStack = cursorStack.slice(0, -1);
        currentCursor = query.cursor;
      } else {
        cursorStack = [...cursorStack, currentCursor];
        currentCursor = query.cursor;
      }
      nextCursor = body.next_cursor ?? null;
      renderResult(body, active);
      status.textContent = "Ready";
    } catch (error) {
      active = prior.active;
      currentCursor = prior.currentCursor;
      nextCursor = prior.nextCursor;
      cursorStack = prior.cursorStack;
      const message = error.message || "request failed";
      status.textContent = `Error: ${message}`;
      showError(message);
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
    errorBanner.textContent = message;
    errorBanner.hidden = false;
  }

  function clearError() {
    errorBanner.textContent = "";
    errorBanner.hidden = true;
  }

  function renderResult(body, query) {
    list.replaceChildren();
    const messages = body.messages || [];
    if (!messages.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "No visible messages found.";
      list.appendChild(empty);
    }
    messages.forEach((message) => list.appendChild(renderMessage(message, query)));
    const channelText = body.channel
      ? `${body.channel.channel_name || body.channel.channel_id} (${body.channel.channel_id}, ${body.channel.channel_protocol || "not set"})`
      : "all channels";
    const recipientText = query.only_my_recipient
      ? "only messages addressed to this principal"
      : "all visible messages";
    $("resultTitle").textContent = `History for ${query.principal} · ${channelText}`;
    meta.textContent = ` ${messages.length} message${messages.length === 1 ? "" : "s"} · ${recipientText}`;
  }

  function renderMessage(message, query) {
    const card = document.createElement("article");
    card.className = "message-card";
    const summary = renderMessageMetadata(message, "message-summary");
    const actions = document.createElement("div");
    actions.className = "message-actions";
    if (message.payload?.truncated) {
      const detail = document.createElement("button");
      detail.type = "button";
      detail.textContent = "View complete payload";
      detail.addEventListener("click", () => {
        openDetail(message.seq, query, setBusy, showError, clearError);
      });
      actions.appendChild(detail);
    }
    summary.appendChild(actions);
    card.append(summary, renderPayload(message.payload));
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
    } catch (error) {
      if (controller.signal.aborted) throw error;
      throw new Error(`HTTP ${response.status}`);
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

function renderPayload(payload) {
  const panel = document.createElement("div");
  panel.className = "payload-panel";
  const title = document.createElement("h2");
  title.textContent = "Payload";
  panel.appendChild(title);
  const metadata = document.createElement("div");
  metadata.className = "payload-meta";
  metadata.textContent = `encoding: ${payload?.encoding || "unknown"} · size: ${payload?.size_bytes ?? 0} bytes`;
  panel.appendChild(metadata);
  if (payload?.preview) {
    const pre = document.createElement("pre");
    pre.textContent = `omitted: ${payload.preview.omitted_bytes} bytes\n\nHEAD\n${payload.preview.head}\n\nTAIL\n${payload.preview.tail}`;
    panel.appendChild(pre);
  } else {
    const text = payload?.text ?? "";
    const pre = document.createElement("pre");
    let parsed;
    let isJson = false;
    if (payload?.encoding === "utf-8") {
      try {
        parsed = JSON.parse(text);
        isJson = true;
      } catch (_) {
        // Payload text is also valid when it is not JSON.
      }
    }
    if (isJson) {
      const tree = document.createElement("div");
      tree.className = "json-tree";
      tree.appendChild(renderJsonNode(parsed, "payload", true));
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "payload-toggle";
      toggle.textContent = "View original text";
      pre.hidden = true;
      toggle.addEventListener("click", () => {
        pre.hidden = !pre.hidden;
        tree.hidden = !pre.hidden;
        if (!pre.hidden) pre.textContent = text;
        toggle.textContent = pre.hidden ? "View original text" : "View JSON";
      });
      panel.append(toggle, tree);
    } else {
      pre.textContent = text;
    }
    panel.appendChild(pre);
  }
  return panel;
}

function renderJsonNode(value, label, initiallyOpen = false) {
  if (value && typeof value === "object") {
    const isArray = Array.isArray(value);
    const keys = isArray ? null : Object.keys(value);
    const size = isArray ? value.length : keys.length;
    const details = document.createElement("details");
    details.open = initiallyOpen;
    const summary = document.createElement("summary");
    summary.textContent = `${label} ${isArray ? `[${size}]` : `{${size}}`}`;
    details.appendChild(summary);
    let rendered = 0;
    let initialized = false;
    let more = null;

    function appendBatch() {
      if (more) more.remove();
      const end = Math.min(rendered + 100, size);
      for (; rendered < end; rendered += 1) {
        const key = isArray ? rendered : keys[rendered];
        details.appendChild(renderJsonNode(value[key], key));
      }
      if (rendered < size) {
        if (!more) {
          more = document.createElement("button");
          more.type = "button";
          more.className = "json-more";
          more.addEventListener("click", appendBatch);
        }
        more.textContent = `Show ${Math.min(100, size - rendered)} more (${size - rendered} remaining)`;
        details.appendChild(more);
      }
    }

    function expand() {
      if (!details.open || initialized) return;
      initialized = true;
      appendBatch();
    }

    details.addEventListener("toggle", expand);
    expand();
    return details;
  }
  const line = document.createElement("div");
  line.textContent = `${label}: ${value === null ? "null" : JSON.stringify(value)}`;
  return line;
}

function renderMessageMetadata(message, className) {
  const meta = document.createElement("div");
  meta.className = className;
  [
    ["seq", message.seq],
    ["uuid", message.uuid],
    ["time", formatTime(message.ts_ms)],
    ["channel", `${message.channel_id} ${message.channel_name || ""} · ${message.channel_protocol || "not set"}`],
    ["principal", message.principal],
    ["recipients", (message.recipients || []).join(", ") || "[]"],
    ["objects", (message.object_ids || []).join(", ") || "[]"],
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
  return Number.isNaN(date.getTime()) ? String(value || "") : date.toISOString();
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
    const message = "allow pop-ups and try again";
    status.textContent = `Error: ${message}`;
    showError(message);
    setBusy(false);
    return;
  }
  timer = setTimeout(() => {
    window.removeEventListener("message", handler);
    const message = "detail page did not receive credentials";
    status.textContent = `Error: ${message}`;
    showError(message);
    setBusy(false);
  }, 5000);
}

function initDetail() {
  const seq = new URL(location.href).searchParams.get("seq");
  let credentialsReceived = false;
  const timer = setTimeout(showCredentialForm, 5000);
  const handler = (event) => {
    if (
      credentialsReceived ||
      event.origin !== location.origin ||
      event.source !== window.opener ||
      event.data?.type !== "openevent-view:credentials" ||
      event.data.seq !== seq
    ) {
      return;
    }
    credentialsReceived = true;
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
    $("detailContent").replaceChildren();
    $("detailStatus").textContent = "Loading";
    try {
      const body = await request(
        `/v1/messages/${encodeURIComponent(seq)}/payload`,
        credentials,
      );
      $("detailStatus").textContent = "Ready";
      $("detailContent").appendChild(renderDetailMessage(body.message));
    } catch (error) {
      credentialsReceived = false;
      showCredentialForm(error.message || "request failed");
    } finally {
      credentials.principal = null;
      credentials.token = null;
    }
  }

  function showCredentialForm(errorMessage = null) {
    if (credentialsReceived) return;
    clearTimeout(timer);
    window.removeEventListener("message", handler);
    window.opener = null;
    const content = $("detailContent");
    const form = document.createElement("form");
    form.className = "detail-login";
    const principalLabel = document.createElement("label");
    principalLabel.textContent = "Principal";
    const principal = document.createElement("input");
    principal.required = true;
    principal.inputMode = "numeric";
    principalLabel.appendChild(principal);
    const tokenLabel = document.createElement("label");
    tokenLabel.textContent = "Token";
    const token = document.createElement("input");
    token.type = "password";
    token.required = true;
    tokenLabel.appendChild(token);
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.textContent = "Load payload";
    form.append(principalLabel, tokenLabel, submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      for (const control of form.elements) control.disabled = true;
      await load({ principal: principal.value.trim(), token: token.value });
    });
    content.replaceChildren();
    if (errorMessage) {
      const error = document.createElement("div");
      error.className = "error-banner";
      error.setAttribute("role", "alert");
      error.textContent = errorMessage;
      content.appendChild(error);
    }
    content.appendChild(form);
    $("detailStatus").textContent = errorMessage
      ? `Error: ${errorMessage}`
      : "Enter credentials";
  }
}

function renderDetailMessage(message) {
  const container = document.createElement("div");
  container.append(renderMessageMetadata(message, "detail-meta"), renderPayload(message.payload));
  return container;
}
