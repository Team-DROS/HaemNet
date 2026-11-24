// Mobile menu and contact form. No dependencies, no cookies, no tracking.
(function () {
  var toggle = document.querySelector('.nav-toggle');
  var nav = document.getElementById('site-nav');
  if (toggle && nav) {
    var setOpen = function (open) {
      nav.classList.toggle('open', open);
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    };
    toggle.addEventListener('click', function () { setOpen(!nav.classList.contains('open')); });
    nav.addEventListener('click', function (e) { if (e.target.tagName === 'A') setOpen(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setOpen(false); });
  }

  // Sticky mobile call to action: appears once the hero has scrolled away.
  var sticky = document.querySelector('.sticky-cta');
  if (sticky) {
    var onScroll = function () { sticky.classList.toggle('show', window.scrollY > 520); };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  var form = document.getElementById('contact-form');
  if (!form) return;

  var status = document.getElementById('form-status');
  var button = form.querySelector('button[type=submit]');
  var email = form.getAttribute('data-email');
  var endpoint = form.getAttribute('data-endpoint');

  var rules = {
    name: function (v) { return v.trim().length >= 2 ? '' : 'Enter your name.'; },
    email: function (v) { return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v.trim()) ? '' : 'Enter a valid email address.'; },
    role: function (v) { return v ? '' : 'Choose the option that describes you.'; },
    message: function (v) { return v.trim().length >= 10 ? '' : 'Write at least a short sentence (10 characters).'; }
  };

  function check(field) {
    var el = form.elements[field];
    var msg = rules[field](el.value);
    var out = document.getElementById(field + '-error');
    out.textContent = msg;
    if (msg) el.setAttribute('aria-invalid', 'true'); else el.removeAttribute('aria-invalid');
    return !msg;
  }

  Object.keys(rules).forEach(function (f) {
    form.elements[f].addEventListener('blur', function () { check(f); });
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    status.hidden = true;
    var ok = Object.keys(rules).map(check).every(Boolean);
    if (!ok) {
      var firstBad = form.querySelector('[aria-invalid=true]');
      if (firstBad) firstBad.focus();
      return;
    }
    // Bots fill the hidden field; pretend success and send nothing.
    if (form.elements.website.value) { window.location.href = '/thank-you'; return; }

    var data = {
      name: form.elements.name.value.trim(),
      email: form.elements.email.value.trim(),
      role: form.elements.role.value,
      organisation: form.elements.organisation.value.trim(),
      message: form.elements.message.value.trim()
    };

    if (!endpoint) {
      var body = 'Name: ' + data.name + '\nEmail: ' + data.email + '\nI am: ' + data.role + '\nOrganisation: ' + data.organisation + '\n\n' + data.message;
      window.location.href = 'mailto:' + email + '?subject=' + encodeURIComponent('HaemNet enquiry from ' + data.name) + '&body=' + encodeURIComponent(body);
      status.className = 'form-status notice info';
      status.textContent = 'Your email app should open with the message ready to send. If it does not, write to ' + email + '.';
      status.hidden = false;
      return;
    }

    button.disabled = true;
    var label = button.textContent;
    button.textContent = 'Sending...';
    fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(data) })
      .then(function (r) { if (!r.ok) throw new Error('bad status'); window.location.href = '/thank-you'; })
      .catch(function () {
        button.disabled = false;
        button.textContent = label;
        status.className = 'form-status error';
        status.textContent = 'We could not send your message. Please try again, or write to ' + email + '.';
        status.hidden = false;
      });
  });
})();
