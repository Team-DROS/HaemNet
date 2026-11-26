(function () {
  var cfg = window.HAEMNET || {};
  var form = document.getElementById("contact-form");
  if (!form || !cfg.apiUrl) return; // plain mailto form keeps working
  var status = document.getElementById("contact-status");
  var token = null;
  var widgetId = null;

  function resetVerification() {
    token = null;
    if (window.turnstile && widgetId !== null) window.turnstile.reset(widgetId);
  }

  if (cfg.turnstileSiteKey) {
    var s = document.createElement("script");
    s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    s.async = true;
    s.onload = function () {
      widgetId = window.turnstile.render("#contact-bot", {
        sitekey: cfg.turnstileSiteKey,
        callback: function (t) { token = t; },
        "expired-callback": function () { token = null; },
        "error-callback": function () { token = null; }
      });
    };
    document.head.appendChild(s);
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var btn = form.querySelector("button");
    if (cfg.turnstileSiteKey && !token) { status.textContent = "Please complete the spam check."; return; }
    // Turnstile tokens are single-use, including requests that fail later.
    var submissionToken = token;
    token = null;
    btn.disabled = true;
    status.textContent = "Sending...";
    fetch(cfg.apiUrl.replace(/\/$/, "") + "/api/contact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: form.name.value, email: form.email.value, message: form.message.value, turnstile_token: submissionToken
      })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, d: d }; });
    }).then(function (res) {
      if (res.ok) { window.location.href = "/thank-you"; return; }
      status.textContent = typeof res.d.detail === "string" ? res.d.detail : "Could not send your message. Please email us directly.";
      resetVerification();
      btn.disabled = false;
    }).catch(function () {
      status.textContent = "Could not reach the server. Please email us directly.";
      resetVerification();
      btn.disabled = false;
    });
  });
})();
