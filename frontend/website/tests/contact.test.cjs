const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../src/assets/contact.js"), "utf8");

function setup(reply) {
  const calls = [];
  let submit, options, resets = 0;
  const button = { disabled: false };
  const status = { textContent: "" };
  const form = {
    name: { value: "Test" }, email: { value: "test@example.com" },
    message: { value: "Test message" },
    querySelector: () => button,
    addEventListener: (_, handler) => { submit = handler; }
  };
  const window = {
    HAEMNET: { apiUrl: "https://api.example.com", turnstileSiteKey: "public" },
    location: { href: "" },
    turnstile: {
      render: (_, value) => { options = value; return 0; },
      reset: (id) => { assert.equal(id, 0); resets++; }
    }
  };
  vm.runInNewContext(source, {
    window,
    document: {
      getElementById: (id) => id === "contact-form" ? form : status,
      createElement: () => ({}),
      head: { appendChild: (script) => script.onload() }
    },
    fetch: async (url, request) => {
      calls.push({ url, body: JSON.parse(request.body) });
      if (reply instanceof Error) throw reply;
      return { ok: reply.ok, json: async () => reply.body };
    }
  });
  return {
    calls, button, status, window,
    token: (value) => options.callback(value),
    expire: () => options["expired-callback"](),
    submit: async () => {
      submit({ preventDefault() {} });
      await new Promise((resolve) => setImmediate(resolve));
    },
    resets: () => resets
  };
}

test("failed submission resets consumed token and requires fresh verification", async () => {
  const app = setup({ ok: false, body: { detail: "Email unavailable" } });
  app.token("first");
  await app.submit();
  assert.equal(app.calls[0].body.turnstile_token, "first");
  assert.equal(app.resets(), 1);
  assert.equal(app.button.disabled, false);
  await app.submit();
  assert.equal(app.calls.length, 1);
  app.token("second");
  await app.submit();
  assert.equal(app.calls[1].body.turnstile_token, "second");
});

test("network failure resets the challenge without claiming delivery", async () => {
  const app = setup(new Error("offline"));
  app.token("first");
  await app.submit();
  assert.equal(app.resets(), 1);
  assert.equal(app.window.location.href, "");
  assert.match(app.status.textContent, /Could not reach/);
});

test("successful submission redirects only after server acceptance", async () => {
  const app = setup({ ok: true, body: { sent: true } });
  app.token("first");
  await app.submit();
  assert.equal(app.window.location.href, "/thank-you");
  assert.equal(app.resets(), 0);
});

test("expired verification prevents a request", async () => {
  const app = setup({ ok: true, body: { sent: true } });
  app.token("expired");
  app.expire();
  await app.submit();
  assert.equal(app.calls.length, 0);
});
