const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

// Run the shipped script against a small DOM and controlled request timers.
class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.listeners = new Map();
    this.attributes = new Map();
    this.className = "";
    this.value = "";
    this.textContent = "";
    this.disabled = false;
    this.classList = {
      toggle: (name, enabled) => {
        const names = new Set(this.className.split(" ").filter(Boolean));
        if (enabled) names.add(name);
        else names.delete(name);
        this.className = [...names].join(" ");
      },
    };
  }
  appendChild(child) {
    child.remove();
    child.parent = this;
    this.children.push(child);
    return child;
  }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  replaceChildren(...children) {
    this.children.forEach((child) => { child.parent = null; });
    this.children = [];
    this.append(...children);
  }
  remove() {
    if (!this.parent) return;
    this.parent.children = this.parent.children.filter((child) => child !== this);
    this.parent = null;
  }
  setAttribute(name, value) { this.attributes.set(name, value); }
  addEventListener(name, handler) {
    const handlers = this.listeners.get(name) || [];
    handlers.push(handler);
    this.listeners.set(name, handlers);
  }
  removeEventListener(name, handler) {
    this.listeners.set(name, (this.listeners.get(name) || []).filter((item) => item !== handler));
  }
  fire(name, event = {}) {
    return Promise.all((this.listeners.get(name) || []).map((handler) => handler({
      preventDefault() {}, ...event,
    })));
  }
  get elements() { return descendants(this).filter((item) => ["button", "input"].includes(item.tagName)); }
}

function descendants(element) {
  return [element, ...element.children.flatMap(descendants)];
}

function createApp(detail = false, options = {}) {
  const ids = new Map();
  const body = new Element("body");
  const elements = detail
    ? { detailContent: "div", detailStatus: "span" }
    : {
        queryForm: "form", principalInput: "input", tokenInput: "input",
        channelInput: "input", recipientInput: "input", statusText: "span",
        resultMeta: "span", resultTitle: "span", messageList: "div", errorBanner: "div",
        latestButton: "button", previousButton: "button", nextButton: "button",
      };
  for (const [id, tag] of Object.entries(elements)) {
    const element = new Element(tag);
    element.disabled = ["latestButton", "previousButton", "nextButton"].includes(id);
    ids.set(id, element);
    body.appendChild(element);
  }
  const timers = new Map();
  let timerId = 0;
  let fetchImpl = options.fetch || (() => { throw new Error("unexpected fetch"); });
  const window = new Element("window");
  window.opener = options.opener || null;
  window.open = options.open || (() => null);
  const context = vm.createContext({
    document: {
      body,
      getElementById: (id) => ids.get(id) || null,
      createElement: (tag) => new Element(tag),
      querySelectorAll: () => body.elements,
    },
    window,
    location: { href: options.href || "http://view/message?seq=0", origin: "http://view" },
    URL, AbortController,
    fetch: (...args) => fetchImpl(...args),
    setTimeout: (callback, delay) => {
      const id = ++timerId;
      timers.set(id, { callback, delay });
      return id;
    },
    clearTimeout: (id) => timers.delete(id),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../src/openevent/view/static/app.js"), "utf8"), context);
  return {
    context, ids, body, timers, window,
    setFetch: (callback) => { fetchImpl = callback; },
    timeout: (delay = 35000) => {
      const entries = [...timers].filter(([, timer]) => timer.delay === delay);
      assert.equal(entries.length, 1, `one ${delay} ms deadline is armed`);
      for (const [id, timer] of entries) {
        timers.delete(id);
        timer.callback();
      }
    },
  };
}

function pendingUntilAborted(signal) {
  return new Promise((_, reject) => signal.addEventListener("abort", () => {
    const error = new Error("aborted");
    error.name = "AbortError";
    reject(error);
  }, { once: true }));
}
const settled = () => new Promise((resolve) => setImmediate(resolve));
const response = (result) => ({ ok: true, status: 200, json: async () => result });
const utf8Payload = (text) => ({ encoding: "utf-8", text, truncated: false, size_bytes: Buffer.byteLength(text) });
const message = {
  seq: "0", uuid: "0", ts_ms: "1000", channel_id: "0", channel_name: "System",
  channel_protocol: "system", principal: "0", recipients: ["2"], object_ids: ["3"],
  payload: utf8Payload('{"ready":true}'),
};

test("overall request timeout covers both fetch and response body", async () => {
  for (const phase of ["fetch", "body"]) {
    const app = createApp();
    let signal;
    app.setFetch(async (_, options) => {
      signal = options.signal;
      if (phase === "fetch") return pendingUntilAborted(signal);
      return { ok: true, status: 200, json: () => pendingUntilAborted(signal) };
    });
    const pending = app.context.request("/v1/messages", {});
    await settled();
    app.timeout();
    await assert.rejects(pending, /timed out after 35 seconds/);
    assert.equal(signal.aborted, true);
    assert.equal(app.timers.size, 0);
  }
});

test("request cleans up its timer after success, HTTP error, and invalid JSON", async () => {
  for (const kind of ["success", "http", "json"]) {
    const app = createApp();
    app.setFetch(async () => ({
      ok: kind !== "http", status: kind === "http" ? 504 : 200,
      json: async () => {
        if (kind === "json") throw new SyntaxError("bad JSON");
        return kind === "http" ? { error: { message: "query deadline exceeded" } } : { ready: true };
      },
    }));
    if (kind === "success") assert.equal((await app.context.request("/", {})).ready, true);
    else await assert.rejects(app.context.request("/", {}), kind === "http" ? /query deadline exceeded/ : /HTTP 200/);
    assert.equal(app.timers.size, 0);
  }
});

test("list timeout preserves the page and pagination, unlocks controls, and allows retry", async () => {
  const app = createApp();
  app.ids.get("principalInput").value = "2";
  app.ids.get("tokenInput").value = "secret";
  app.setFetch(async () => response({ messages: [{ ...message, seq: "10" }], next_cursor: { before_seq: "10" } }));
  await app.ids.get("queryForm").fire("submit");
  await settled();
  const originalCard = app.ids.get("messageList").children[0];
  const queries = [];
  app.setFetch((_, options) => {
    queries.push(JSON.parse(options.body));
    return pendingUntilAborted(options.signal);
  });
  await app.ids.get("nextButton").fire("click");
  assert.equal(app.ids.get("principalInput").disabled, true);
  app.timeout();
  await settled();
  assert.equal(app.ids.get("messageList").children[0], originalCard);
  assert.equal(app.ids.get("principalInput").disabled, false);
  assert.equal(app.ids.get("nextButton").disabled, false);
  assert.equal(app.ids.get("previousButton").disabled, true);
  assert.equal(app.ids.get("latestButton").disabled, false);
  assert.equal(app.body.attributes.get("aria-busy"), "false");
  assert.match(app.ids.get("errorBanner").textContent, /timed out/);
  app.setFetch(async (_, options) => {
    queries.push(JSON.parse(options.body));
    return response({ messages: [message], next_cursor: null });
  });
  await app.ids.get("nextButton").fire("click");
  await settled();
  assert.deepEqual(queries.map((query) => query.cursor), [{ before_seq: "10" }, { before_seq: "10" }]);
  assert.equal(app.ids.get("previousButton").disabled, false);
  assert.equal(app.ids.get("errorBanner").hidden, true);
});

test("detail request supports seq zero and restores credential entry after timeout", async () => {
  const app = createApp(true);
  let requested;
  app.setFetch((url, options) => {
    requested = url;
    return pendingUntilAborted(options.signal);
  });
  const form = app.ids.get("detailContent").children[0];
  form.elements[0].value = "2";
  form.elements[1].value = "secret";
  const pending = form.fire("submit");
  app.timeout();
  await pending;
  assert.equal(requested, "/v1/messages/0/payload");
  const retryForm = app.ids.get("detailContent").children[1];
  assert.equal(retryForm.tagName, "form");
  assert.ok(retryForm.elements.every((control) => !control.disabled));
  assert.match(app.ids.get("detailStatus").textContent, /timed out/);
  assert.equal(app.timers.size, 0);
});

test("a large array creates only its first batch, and nested branches load on expansion", async () => {
  const app = createApp();
  const panel = app.context.renderPayload(utf8Payload(JSON.stringify(Array(100000).fill(0))));
  const tree = panel.children.find((node) => node.className === "json-tree");
  assert.equal(tree.className, "json-tree");
  const root = tree.children[0];
  assert.equal(root.children.length, 102); // summary, 100 values, more button
  assert.ok(descendants(panel).length < 112);
  await root.children.at(-1).fire("click");
  assert.equal(root.children.length, 202);
  assert.equal(root.children[200].textContent, "199: 0");

  const nested = app.context.renderJsonNode({ nested: Array(100000).fill(0) }, "payload", true);
  const branch = nested.children[1];
  assert.equal(branch.children.length, 1);
  branch.open = true;
  await branch.fire("toggle");
  assert.equal(branch.children.length, 102);
  branch.open = false;
  await branch.fire("toggle");
  branch.open = true;
  await branch.fire("toggle");
  assert.equal(branch.children.length, 102, "reopening keeps the rendered batch");
});

test("object batches eventually expose every field without duplicating or omitting entries", async () => {
  const app = createApp();
  const value = Object.fromEntries(Array.from({ length: 205 }, (_, index) => [`key${index}`, index]));
  const root = app.context.renderJsonNode(value, "payload", true);
  await root.children.at(-1).fire("click");
  await root.children.at(-1).fire("click");
  assert.equal(root.children.length, 206);
  assert.deepEqual(root.children.slice(1).map((node) => node.textContent),
    Object.entries(value).map(([key, item]) => `${key}: ${item}`));
  assert.equal(root.children.at(-1).tagName, "div");
});

test("list and detail show the same metadata including seq zero", async () => {
  const app = createApp();
  app.setFetch(async () => response({ messages: [message] }));
  app.ids.get("principalInput").value = "2";
  await app.ids.get("queryForm").fire("submit");
  await settled();
  const listMeta = app.ids.get("messageList").children[0].children[0];
  const detailMeta = app.context.renderDetailMessage(message).children[0];
  const fields = (meta) => meta.children.filter((node) => node.className === "field")
    .map((node) => node.children.map((child) => child.textContent));
  assert.deepEqual(fields(listMeta), fields(detailMeta));
  assert.deepEqual(fields(detailMeta)[0], ["seq", "0"]);
});

test("pagination uses applied inputs through next, previous, and latest until Query succeeds", async () => {
  const app = createApp();
  const queries = [];
  app.setFetch(async (_, options) => {
    const query = JSON.parse(options.body);
    queries.push(query);
    return response(query.cursor
      ? { messages: [message], next_cursor: null }
      : { messages: [{ ...message, seq: "10" }], next_cursor: { before_seq: "10" } });
  });
  for (const id of ["nextButton", "previousButton", "latestButton"]) {
    assert.equal(app.ids.get(id).disabled, true);
    await app.ids.get(id).fire("click");
  }
  assert.equal(queries.length, 0);
  app.ids.get("principalInput").value = "2";
  app.ids.get("tokenInput").value = "original-token";
  app.ids.get("channelInput").value = "0";
  app.ids.get("recipientInput").checked = true;
  await app.ids.get("queryForm").fire("submit");
  await settled();
  app.ids.get("principalInput").value = "3";
  app.ids.get("tokenInput").value = "edited-token";
  app.ids.get("channelInput").value = "7";
  app.ids.get("recipientInput").checked = false;

  await app.ids.get("nextButton").fire("click");
  await settled();
  assert.equal(app.ids.get("nextButton").disabled, true);
  assert.equal(app.ids.get("previousButton").disabled, false);
  await app.ids.get("nextButton").fire("click");
  assert.equal(queries.length, 2, "no next page means no new request");

  await app.ids.get("previousButton").fire("click");
  await settled();
  assert.equal(app.ids.get("previousButton").disabled, true);
  await app.ids.get("nextButton").fire("click");
  await settled();
  await app.ids.get("latestButton").fire("click");
  await settled();
  assert.equal(app.ids.get("previousButton").disabled, true, "latest clears the old cursor stack");
  assert.deepEqual(queries.map((query) => query.cursor), [null, { before_seq: "10" }, null, { before_seq: "10" }, null]);
  for (const query of queries) {
    assert.equal(query.principal, "2");
    assert.equal(query.token, "original-token");
    assert.equal(query.channel_id, "0");
    assert.equal(query.only_my_recipient, true);
  }
  await app.ids.get("queryForm").fire("submit");
  await settled();
  assert.deepEqual(queries.at(-1), { principal: "3", token: "edited-token", channel_id: "7", cursor: null });
  assert.equal(app.ids.get("previousButton").disabled, true);
});

test("every payload shows its encoding and original byte count", () => {
  const app = createApp();
  const cases = [
    utf8Payload("中文"), utf8Payload('{"a":1}'), utf8Payload("false"),
    { encoding: "base64", text: "/w==", truncated: false, size_bytes: 1 },
    { encoding: "utf-8", truncated: true, size_bytes: 40000,
      preview: { head: "start", tail: "end", omitted_bytes: 39992 } },
    { encoding: "base64", truncated: true, size_bytes: 40000,
      preview: { head: "/w==", tail: "/w==", omitted_bytes: 39998 } },
  ];
  for (const payload of cases) {
    const panel = app.context.renderPayload(payload);
    const metadata = panel.children.find((node) => node.className === "payload-meta");
    assert.equal(metadata.textContent, `encoding: ${payload.encoding} · size: ${payload.size_bytes} bytes`);
    if (payload.preview) {
      assert.match(panel.children.at(-1).textContent, new RegExp(`omitted: ${payload.preview.omitted_bytes} bytes`));
      assert.equal(panel.children.some((node) => node.className === "json-tree"), false);
    }
  }
});

test("JSON view preserves exact original text and plain text or Base64 is never parsed", async () => {
  const app = createApp();
  const original = ' { "id": 9007199254740993, "a": 1, "a": 2 }\n';
  const panel = app.context.renderPayload(utf8Payload(original));
  const tree = panel.children.find((node) => node.className === "json-tree");
  const toggle = panel.children.find((node) => node.className === "payload-toggle");
  const pre = panel.children.at(-1);
  assert.ok(tree);
  assert.equal(pre.hidden, true);
  assert.equal(toggle.textContent, "View original text");
  await toggle.fire("click");
  assert.equal(pre.textContent, original, "original numbers, duplicate keys and whitespace are preserved");
  assert.equal(pre.hidden, false);
  assert.equal(tree.hidden, true);
  assert.equal(toggle.textContent, "View JSON");
  await toggle.fire("click");
  assert.equal(pre.hidden, true);
  assert.equal(tree.hidden, false);

  for (const payload of [utf8Payload("{not JSON}"), utf8Payload(""),
    { encoding: "base64", text: "1234", size_bytes: 3, truncated: false }]) {
    const plain = app.context.renderPayload(payload);
    assert.equal(plain.children.some((node) => node.className === "json-tree"), false);
    assert.equal(plain.children.at(-1).textContent, payload.text);
  }
});

test("deep JSON creates one level at a time and can show its source without traversal", async () => {
  const app = createApp();
  const text = "[".repeat(5000) + "0" + "]".repeat(5000);
  const panel = app.context.renderPayload(utf8Payload(text));
  const tree = panel.children.find((node) => node.className === "json-tree");
  assert.ok(tree, "deep valid JSON is displayed as a tree");
  assert.ok(descendants(panel).length < 15, "unexpanded descendants do not become DOM nodes");
  let branch = tree.children[0].children[1];
  for (let depth = 0; depth < 5; depth += 1) {
    assert.equal(branch.children.length, 1);
    branch.open = true;
    await branch.fire("toggle");
    assert.equal(branch.children.length, 2);
    branch = branch.children[1];
  }
  await panel.children.find((node) => node.className === "payload-toggle").fire("click");
  assert.equal(panel.children.at(-1).textContent, text);
});

const previewMessage = {
  ...message,
  payload: { encoding: "utf-8", truncated: true, size_bytes: 40000,
    preview: { head: "start", tail: "end", omitted_bytes: 39992 } },
};

async function showPreview(app) {
  app.ids.get("principalInput").value = "2";
  app.ids.get("tokenInput").value = "secret";
  app.setFetch(async () => response({ messages: [previewMessage], next_cursor: null }));
  await app.ids.get("queryForm").fire("submit");
  await settled();
  return descendants(app.ids.get("messageList")).find((node) => node.textContent === "View complete payload");
}

test("new detail tab receives applied credentials once, loads seq zero, and releases handoff state", async () => {
  const parent = createApp();
  const detailButton = await showPreview(parent);
  parent.ids.get("principalInput").value = "3";
  parent.ids.get("tokenInput").value = "unsubmitted-token";
  let child;
  const requests = [];
  const sent = [];
  parent.window.postMessage = (data, origin) => {
    assert.equal(origin, "http://view");
    Promise.resolve().then(() => parent.window.fire("message", { data, origin, source: child.window }));
  };
  parent.window.open = (href, target) => {
    assert.equal(href, "http://view/message?seq=0");
    assert.equal(target, "_blank");
    child = createApp(true, {
      href, opener: parent.window,
      fetch: async (url, options) => {
        requests.push({ url, body: JSON.parse(options.body) });
        return response({ message });
      },
    });
    child.window.postMessage = (data, origin) => {
      sent.push(data);
      assert.equal(origin, "http://view");
      Promise.resolve().then(() => child.window.fire("message", { data, origin, source: parent.window }));
    };
    return child.window;
  };
  await detailButton.fire("click");
  await settled();
  assert.equal(sent.length, 1);
  assert.deepEqual(requests, [{ url: "/v1/messages/0/payload", body: { principal: "2", token: "secret" } }]);
  assert.equal(parent.ids.get("statusText").textContent, "Ready");
  assert.equal(parent.ids.get("principalInput").disabled, false);
  assert.equal(child.ids.get("detailStatus").textContent, "Ready");
  assert.equal(child.window.opener, null);
  for (const app of [parent, child]) {
    assert.equal(app.timers.size, 0);
    assert.equal((app.window.listeners.get("message") || []).length, 0);
  }
});

test("parent ignores ready messages with the wrong origin, window, sequence, or type", async () => {
  const parent = createApp();
  const detailButton = await showPreview(parent);
  const sent = [];
  const child = { postMessage: (...args) => sent.push(args) };
  parent.window.open = () => child;
  await detailButton.fire("click");
  const ready = { origin: "http://view", source: child, data: { type: "openevent-view:ready", seq: "0" } };
  for (const event of [
    { ...ready, origin: "http://other" }, { ...ready, source: {} },
    { ...ready, data: { ...ready.data, seq: "1" } }, { ...ready, data: { ...ready.data, type: "other" } },
  ]) await parent.window.fire("message", event);
  assert.equal(sent.length, 0);
  assert.equal(parent.ids.get("principalInput").disabled, true);
  assert.equal(parent.timers.size, 1);
  await parent.window.fire("message", ready);
  await parent.window.fire("message", ready);
  assert.equal(sent.length, 1);
  assert.equal(sent[0][0].seq, "0");
  assert.equal(sent[0][0].token, "secret");
  assert.equal(sent[0][1], "http://view");
  assert.equal(parent.ids.get("principalInput").disabled, false);
  assert.equal(parent.timers.size, 0);
  assert.equal(parent.window.listeners.get("message").length, 0);
});

test("detail ignores credentials with the wrong origin, opener, sequence, or type", async () => {
  const ready = [];
  const opener = { postMessage: (...args) => ready.push(args) };
  const requests = [];
  const child = createApp(true, { opener, fetch: async (url, options) => {
    requests.push({ url, body: JSON.parse(options.body) });
    return response({ message });
  } });
  assert.equal(ready.length, 1);
  assert.equal(ready[0][0].type, "openevent-view:ready");
  assert.equal(ready[0][0].seq, "0");
  assert.equal(ready[0][1], "http://view");
  const credentials = { origin: "http://view", source: opener,
    data: { type: "openevent-view:credentials", seq: "0", principal: "2", token: "secret" } };
  for (const event of [
    { ...credentials, origin: "http://other" }, { ...credentials, source: {} },
    { ...credentials, data: { ...credentials.data, seq: "1" } },
    { ...credentials, data: { ...credentials.data, type: "other" } },
  ]) await child.window.fire("message", event);
  assert.equal(requests.length, 0);
  assert.equal(child.timers.size, 1);
  await child.window.fire("message", credentials);
  await settled();
  await child.window.fire("message", credentials);
  assert.equal(requests.length, 1);
  assert.equal(child.window.opener, null);
  assert.equal(child.timers.size, 0);
  assert.equal(child.window.listeners.get("message").length, 0);
});

test("blocked detail popup leaves the page intact and clears busy and handoff state", async () => {
  const parent = createApp();
  const detailButton = await showPreview(parent);
  const card = parent.ids.get("messageList").children[0];
  parent.window.open = () => null;
  await detailButton.fire("click");
  assert.equal(parent.ids.get("messageList").children[0], card);
  assert.equal(parent.ids.get("principalInput").disabled, false);
  assert.equal(parent.ids.get("nextButton").disabled, true);
  assert.match(parent.ids.get("errorBanner").textContent, /allow pop-ups/);
  assert.equal(parent.timers.size, 0);
  assert.equal(parent.window.listeners.get("message").length, 0);
});

test("handoff timeout clears both listeners, unlocks the parent, and offers manual credentials", async () => {
  const parent = createApp();
  const detailButton = await showPreview(parent);
  let sent = 0;
  const childWindow = { postMessage: () => { sent += 1; } };
  parent.window.open = () => childWindow;
  await detailButton.fire("click");
  parent.timeout(5000);
  assert.equal(parent.ids.get("principalInput").disabled, false);
  assert.match(parent.ids.get("errorBanner").textContent, /did not receive credentials/);
  assert.equal(parent.window.listeners.get("message").length, 0);
  await parent.window.fire("message", { origin: "http://view", source: childWindow,
    data: { type: "openevent-view:ready", seq: "0" } });
  assert.equal(sent, 0, "late ready messages do not receive credentials");
  assert.equal(parent.timers.size, 0);

  const opener = { postMessage() {} };
  const child = createApp(true, { opener });
  child.timeout(5000);
  assert.equal(child.ids.get("detailStatus").textContent, "Enter credentials");
  assert.equal(child.ids.get("detailContent").children[0].tagName, "form");
  assert.equal(child.window.opener, null);
  assert.equal(child.window.listeners.get("message").length, 0);
  assert.equal(child.timers.size, 0);
  await child.window.fire("message", { origin: "http://view", source: opener,
    data: { type: "openevent-view:credentials", seq: "0", principal: "2", token: "late-token" } });
  const manualRequests = [];
  child.setFetch(async (url, options) => {
    manualRequests.push({ url, body: JSON.parse(options.body) });
    return response({ message });
  });
  const form = child.ids.get("detailContent").children[0];
  form.elements[0].value = "4";
  form.elements[1].value = "manual-token";
  await form.fire("submit");
  assert.deepEqual(manualRequests, [{ url: "/v1/messages/0/payload", body: { principal: "4", token: "manual-token" } }]);
  assert.equal(child.ids.get("detailStatus").textContent, "Ready");
  assert.equal(child.timers.size, 0);
});
