/* Shared front-end helpers for the Inventory & Sales Management System.
   Kept generic — page-specific behaviour lives inline in each template. */
(function () {
  "use strict";

  /* ---- Mobile sidebar toggle ---- */
  document.addEventListener("click", function (e) {
    var sidebar = document.getElementById("navLinks");
    if (!sidebar) return;
    if (e.target.closest("#navToggle")) {
      sidebar.classList.toggle("open");
      return;
    }
    /* Close the off-canvas sidebar when tapping the backdrop or a nav link. */
    if (e.target.closest("#sidebarOverlay") || e.target.closest(".side-link")) {
      sidebar.classList.remove("open");
    }
  });

  /* ---- Collapsible sidebar groups ----
     The group holding the current page is opened by the server.  Any other
     group remembers whether the user last left it open (per browser). */
  var GROUP_KEY = "amamio.navGroups";

  function readGroups() {
    try { return JSON.parse(window.localStorage.getItem(GROUP_KEY)) || {}; }
    catch (e) { return {}; }
  }
  function writeGroups(state) {
    try { window.localStorage.setItem(GROUP_KEY, JSON.stringify(state)); } catch (e) { /* optional */ }
  }
  function setGroup(group, open) {
    group.classList.toggle("is-open", open);
    var head = group.querySelector(".side-group-head");
    if (head) head.setAttribute("aria-expanded", open ? "true" : "false");
  }

  // app.js loads in <head> (so page scripts can use window.IMS straight
  // away); anything that touches the page waits for it to be parsed.
  function whenReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  whenReady(function initGroups() {
    var state = readGroups();
    document.querySelectorAll(".side-group").forEach(function (group) {
      var name = group.getAttribute("data-group");
      if (!group.classList.contains("has-active") && state[name]) setGroup(group, true);
    });
    // Enable the open/close animation only after the first paint, so the
    // page doesn't visibly animate groups open on every load.
    window.requestAnimationFrame(function () {
      document.documentElement.classList.add("nav-ready");
    });
  });

  document.addEventListener("click", function (e) {
    var head = e.target.closest(".side-group-head");
    if (!head) return;
    var group = head.closest(".side-group");
    var open = !group.classList.contains("is-open");
    setGroup(group, open);
    var state = readGroups();
    state[group.getAttribute("data-group")] = open;
    writeGroups(state);
  });

  /* ---- Confirm dialogs on [data-confirm] elements/forms ---- */
  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-confirm]");
    if (el && !confirm(el.getAttribute("data-confirm"))) {
      e.preventDefault();
      e.stopPropagation();
    }
  });
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form.matches("[data-confirm]") &&
        !confirm(form.getAttribute("data-confirm"))) {
      e.preventDefault();
    }
  }, true);

  /* ---- Modal open/close ----
     Trigger:  <button data-modal-open="modalId">
     Close:    any element with [data-modal-close] inside, or backdrop click. */
  function openModal(id) {
    var m = document.getElementById(id);
    if (m) m.classList.add("open");
  }
  function closeModal(el) {
    var backdrop = el.closest(".modal-backdrop");
    if (backdrop) backdrop.classList.remove("open");
  }
  document.addEventListener("click", function (e) {
    var opener = e.target.closest("[data-modal-open]");
    if (opener) {
      e.preventDefault();
      openModal(opener.getAttribute("data-modal-open"));
      return;
    }
    if (e.target.closest("[data-modal-close]")) {
      closeModal(e.target);
      return;
    }
    if (e.target.classList && e.target.classList.contains("modal-backdrop")) {
      e.target.classList.remove("open");
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var open = document.querySelector(".modal-backdrop.open");
      if (open) open.classList.remove("open");
    }
  });

  /* ---- Small fetch helper returning parsed JSON ---- */
  function fetchJSON(url, options) {
    options = options || {};
    var opts = Object.assign({ headers: {} }, options);
    if (opts.body && typeof opts.body === "object" &&
        !(opts.body instanceof FormData)) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    return fetch(url, opts).then(function (r) {
      var ct = r.headers.get("content-type") || "";
      var parse = ct.indexOf("application/json") !== -1
        ? r.json() : r.text();
      return parse.then(function (data) {
        if (!r.ok) throw { status: r.status, data: data };
        return data;
      });
    });
  }

  /* ---- Table paging ----
     Every .table with more than 15 rows shows 15 at a time, with Previous /
     Next and a "Rows per page" choice of 15, 30 or 50.  Rows are only hidden,
     never removed, so forms inside a table still submit every row and
     printing shows the whole table.  Opt out with data-no-paginate. */
  var PAGE_SIZES = [15, 30, 50];
  var SIZE_KEY = "amamio.pageSize";

  function savedSize() {
    try {
      var v = parseInt(window.localStorage.getItem(SIZE_KEY), 10);
      return PAGE_SIZES.indexOf(v) !== -1 ? v : PAGE_SIZES[0];
    } catch (e) { return PAGE_SIZES[0]; }
  }
  function saveSize(v) {
    try { window.localStorage.setItem(SIZE_KEY, String(v)); } catch (e) { /* optional */ }
  }

  function paginate(table) {
    if (table.hasAttribute("data-no-paginate") || table.dataset.paged) return;
    var body = table.tBodies[0];
    if (!body) return;
    var rows = Array.prototype.slice.call(body.rows);
    if (rows.length <= PAGE_SIZES[0]) return;
    table.dataset.paged = "1";

    var size = savedSize();
    var page = 0;

    var bar = document.createElement("div");
    bar.className = "pager no-print";
    bar.innerHTML =
      '<span class="pager-info" aria-live="polite"></span>' +
      '<span class="pager-controls">' +
        '<label class="pager-size">Rows per page ' +
          "<select aria-label=\"Rows per page\">" +
            PAGE_SIZES.map(function (n) {
              return '<option value="' + n + '">' + n + "</option>";
            }).join("") +
          "</select></label>" +
        '<button type="button" class="pager-btn" data-dir="-1" aria-label="Previous page">&lsaquo; Previous</button>' +
        '<span class="pager-page"></span>' +
        '<button type="button" class="pager-btn" data-dir="1" aria-label="Next page">Next &rsaquo;</button>' +
      "</span>";

    var anchor = table.closest(".table-wrap") || table;
    anchor.parentNode.insertBefore(bar, anchor.nextSibling);

    var info = bar.querySelector(".pager-info");
    var label = bar.querySelector(".pager-page");
    var select = bar.querySelector("select");
    var prev = bar.querySelector('[data-dir="-1"]');
    var next = bar.querySelector('[data-dir="1"]');
    select.value = String(size);

    function render() {
      var pages = Math.max(1, Math.ceil(rows.length / size));
      page = Math.min(Math.max(page, 0), pages - 1);
      var start = page * size;
      var end = Math.min(start + size, rows.length);
      rows.forEach(function (row, i) {
        row.classList.toggle("is-paged-out", i < start || i >= end);
      });
      info.innerHTML = "Showing <b>" + (start + 1) + "&ndash;" + end +
        "</b> of <b>" + rows.length + "</b>";
      label.textContent = "Page " + (page + 1) + " of " + pages;
      prev.disabled = page === 0;
      next.disabled = page >= pages - 1;
    }

    function go(delta) {
      page += delta;
      render();
      // Keep the top of the table in view after changing page.
      var top = anchor.getBoundingClientRect().top;
      if (top < 80) window.scrollBy({ top: top - 90, behavior: "smooth" });
    }

    prev.addEventListener("click", function () { go(-1); });
    next.addEventListener("click", function () { go(1); });
    select.addEventListener("change", function () {
      var first = page * size;              // keep the first visible row in view
      size = parseInt(select.value, 10);
      page = Math.floor(first / size);
      saveSize(size);
      render();
    });
    render();
  }

  function paginateAll(root) {
    (root || document).querySelectorAll("table.table").forEach(paginate);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { paginateAll(); });
  } else {
    paginateAll();
  }

  /* ---- Wizard: one step on screen at a time ----
     <form data-wizard data-submit-label="Save">
       <section class="wz-step" data-title="…" data-hint="…"> fields </section>
       <section class="wz-step" data-title="Review" data-review></section>
     </form>
     - Next checks only the fields of the current step.
     - data-when="name=value" (or name!=value, or name=a|b) skips a step
       unless the condition holds.
     - A [data-review] step lists everything entered, grouped per step.
     - Pages may listen for "wz:enter" (detail.index) on a step, and
       "wz:validate" (cancelable; set detail.message) to add their own rules.
     - data-wizard-start="n" opens at step n (e.g. after a server error). */
  function fieldValue(form, name) {
    var els = form.querySelectorAll('[name="' + name + '"]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if ((el.type === "radio" || el.type === "checkbox")) {
        if (el.checked) return el.value;
      } else {
        return el.value;
      }
    }
    return "";
  }

  function stepApplies(form, step) {
    var rule = step.getAttribute("data-when");
    if (!rule) return true;
    var neg = rule.indexOf("!=") !== -1;
    var parts = rule.split(neg ? "!=" : "=");
    var value = fieldValue(form, parts[0].trim());
    var options = (parts[1] || "").split("|").map(function (s) { return s.trim(); });
    var hit = options.indexOf(value) !== -1;
    return neg ? !hit : hit;
  }

  function labelFor(el) {
    if (el.getAttribute("data-review-label")) return el.getAttribute("data-review-label");
    var group = el.closest("[data-review-label]");
    if (group) return group.getAttribute("data-review-label");
    if (el.id) {
      var lab = el.form && el.form.querySelector('label[for="' + el.id + '"]');
      if (lab) return lab.textContent.replace("*", "").trim();
    }
    var row = el.closest(".form-row");
    var fl = row && row.querySelector(".form-label");
    return fl ? fl.textContent.replace("*", "").trim() : (el.name || "");
  }

  function displayValue(el) {
    if (el.tagName === "SELECT") {
      var opt = el.options[el.selectedIndex];
      return opt && el.value !== "" ? opt.textContent.trim() : "";
    }
    if (el.type === "radio") {
      // A choice card shows only its title; a chip shows its label.
      var card = el.closest("label");
      var t = card && (card.querySelector(".choice-title") || card.querySelector("span"));
      return t ? t.textContent.trim() : el.value;
    }
    if (el.type === "checkbox") return el.checked ? "Yes" : "No";
    var unit = el.closest(".big-field") && el.closest(".big-field").querySelector(".unit");
    return el.value + (unit && el.value !== "" ? " " + unit.textContent.trim() : "");
  }

  function esc(value) {
    var d = document.createElement("div");
    d.textContent = value === null || value === undefined ? "" : String(value);
    return d.innerHTML;
  }

  function initWizard(form) {
    if (form.dataset.wzReady) return;
    form.dataset.wzReady = "1";
    var steps = Array.prototype.slice.call(form.querySelectorAll(".wz-step"));
    if (!steps.length) return;
    // The wizard checks each visible step itself; native validation would
    // trip over required fields in steps that were skipped.
    form.noValidate = true;
    var current = 0;

    // Header: progress bar, "Step n of m", title, hint.
    var head = document.createElement("div");
    head.className = "wz-head";
    head.innerHTML = '<div class="wz-progress" role="presentation"></div>' +
      '<div class="wz-count" aria-live="polite"></div>' +
      '<h2 class="wz-title"></h2><p class="wz-hint"></p>';
    form.insertBefore(head, steps[0]);
    var bar = head.querySelector(".wz-progress");
    steps.forEach(function (s, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.setAttribute("aria-label", "Go to step: " + (s.getAttribute("data-title") || i + 1));
      b.addEventListener("click", function () { if (i < current) go(i); });
      bar.appendChild(b);
      // Each step's own error line.
      var err = document.createElement("div");
      err.className = "wz-error";
      err.setAttribute("role", "alert");
      s.appendChild(err);
    });

    // Footer: Back / Next / Save.
    var nav = document.createElement("div");
    nav.className = "wz-nav";
    var cancelHref = form.getAttribute("data-cancel");
    nav.innerHTML =
      '<button type="button" class="btn btn-ghost" data-wz-back>Back</button>' +
      (cancelHref ? '<a class="btn btn-ghost" data-wz-cancel href="' + esc(cancelHref) + '">Cancel</a>' : "") +
      '<span class="wz-spacer"></span>' +
      '<button type="button" class="btn btn-primary" data-wz-next>Next</button>' +
      '<button type="submit" class="btn btn-primary" data-wz-submit>' +
        esc(form.getAttribute("data-submit-label") || "Save") + "</button>";
    form.appendChild(nav);
    var backBtn = nav.querySelector("[data-wz-back]");
    var cancelBtn = nav.querySelector("[data-wz-cancel]");
    var nextBtn = nav.querySelector("[data-wz-next]");
    var submitBtn = nav.querySelector("[data-wz-submit]");

    function visible() {
      return steps.map(function (s, i) { return stepApplies(form, s) ? i : -1; })
                  .filter(function (i) { return i !== -1; });
    }

    function fieldsOf(step) {
      return Array.prototype.slice.call(
        step.querySelectorAll("input, select, textarea")).filter(function (el) {
          return !el.disabled && el.type !== "hidden" && el.name && !el.closest("[data-review-skip]");
        });
    }

    function showError(step, message) {
      var err = step.querySelector(".wz-error");
      err.textContent = message || "";
      err.classList.toggle("is-shown", !!message);
    }

    function validate(step) {
      showError(step, "");
      var fields = fieldsOf(step);
      for (var i = 0; i < fields.length; i++) {
        if (!fields[i].checkValidity()) {
          fields[i].reportValidity();
          return false;
        }
      }
      var ev = new CustomEvent("wz:validate", { cancelable: true, detail: {} });
      if (!step.dispatchEvent(ev)) {
        showError(step, ev.detail.message || "Please check this step.");
        return false;
      }
      return true;
    }

    function buildReview(step) {
      var html = "";
      visible().forEach(function (i) {
        var s = steps[i];
        if (s === step || s.hasAttribute("data-review") || s.hasAttribute("data-no-review")) return;
        var rows = [], seen = {};
        // A step can describe itself (e.g. a list of line items) by setting
        // step.reviewHtml = function () { return "<dt>…</dt><dd>…</dd>"; }
        if (typeof s.reviewHtml === "function") {
          rows.push(s.reviewHtml());
        } else {
          fieldsOf(s).forEach(function (el) {
            if (el.type === "radio" && !el.checked) return;
            if (seen[el.name] && el.type === "radio") return;
            var v = displayValue(el);
            if (v === "" || v === null) return;
            seen[el.name] = true;
            rows.push("<dt>" + esc(labelFor(el)) + "</dt><dd>" + esc(v) + "</dd>");
          });
        }
        if (!rows.join("")) return;
        html += '<div><div class="review-group-title">' + esc(s.getAttribute("data-title") || "") +
          ' <a href="#" class="review-edit" data-wz-goto="' + i + '">Change</a></div>' +
          '<dl class="review-list">' + rows.join("") + "</dl></div>";
      });
      var target = step.querySelector(".review");
      if (!target) {
        target = document.createElement("div");
        target.className = "review";
        var body = step.querySelector(".wz-body") || step;
        body.insertBefore(target, body.firstChild);
      }
      target.innerHTML = html || '<p class="muted">Nothing entered yet.</p>';
    }

    function render() {
      var vis = visible();
      var pos = vis.indexOf(current);
      steps.forEach(function (s, i) {
        s.classList.toggle("is-current", i === current);
        var b = bar.children[i];
        b.className = vis.indexOf(i) === -1 ? "is-skipped"
          : i === current ? "is-current" : (vis.indexOf(i) < pos ? "is-done" : "");
      });
      var step = steps[current];
      head.querySelector(".wz-count").textContent = "Step " + (pos + 1) + " of " + vis.length;
      head.querySelector(".wz-title").textContent = step.getAttribute("data-title") || "";
      var hint = step.getAttribute("data-hint") || "";
      var hintEl = head.querySelector(".wz-hint");
      hintEl.textContent = hint;
      hintEl.style.display = hint ? "" : "none";
      var last = pos === vis.length - 1;
      backBtn.style.display = pos === 0 ? "none" : "";
      if (cancelBtn) cancelBtn.style.display = pos === 0 ? "" : "none";
      nextBtn.style.display = last ? "none" : "";
      submitBtn.style.display = last ? "" : "none";
      if (step.hasAttribute("data-review")) buildReview(step);
      step.dispatchEvent(new CustomEvent("wz:enter", { detail: { index: current } }));
      var first = step.querySelector("input:not([type=hidden]):not([type=radio]):not([type=checkbox]), select, textarea");
      if (first && !step.hasAttribute("data-review") && window.matchMedia("(min-width: 900px)").matches) {
        try { first.focus({ preventScroll: true }); } catch (e) { first.focus(); }
      }
    }

    function go(index) {
      current = index;
      render();
      var top = form.getBoundingClientRect().top + window.pageYOffset - 90;
      if (window.pageYOffset > top) window.scrollTo({ top: top, behavior: "smooth" });
    }

    function next() {
      if (!validate(steps[current])) return;
      var vis = visible();
      var pos = vis.indexOf(current);
      if (pos < vis.length - 1) go(vis[pos + 1]);
    }

    function back() {
      var vis = visible();
      var pos = vis.indexOf(current);
      if (pos > 0) go(vis[pos - 1]);
    }

    nextBtn.addEventListener("click", next);
    backBtn.addEventListener("click", back);
    form.addEventListener("click", function (e) {
      var to = e.target.closest("[data-wz-goto]");
      if (to) { e.preventDefault(); go(parseInt(to.getAttribute("data-wz-goto"), 10)); }
      var nx = e.target.closest("[data-wz-next-inline]");
      if (nx) { e.preventDefault(); next(); }
    });
    // A choice card marked data-autonext moves on as soon as it is picked.
    form.addEventListener("change", function (e) {
      if (e.target.matches("[data-autonext]") && e.target.checked) {
        window.setTimeout(next, 180);
      }
    });
    // Enter moves to the next step instead of submitting half a form.
    form.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" || e.target.tagName === "TEXTAREA" || e.target.type === "submit") return;
      var vis = visible();
      if (vis.indexOf(current) < vis.length - 1) { e.preventDefault(); next(); }
    });
    form.addEventListener("submit", function (e) {
      // Validate every visible step before saving; jump to the first problem.
      var vis = visible();
      for (var i = 0; i < vis.length; i++) {
        var s = steps[vis[i]];
        if (s.hasAttribute("data-review")) continue;
        var ok = fieldsOf(s).every(function (el) { return el.checkValidity(); });
        if (!ok) { e.preventDefault(); go(vis[i]); validate(s); return; }
      }
      // Fields in skipped steps must not be submitted.
      steps.forEach(function (s, i) {
        if (vis.indexOf(i) === -1) {
          fieldsOf(s).forEach(function (el) { el.disabled = true; });
        }
      });
      submitBtn.disabled = true;
      submitBtn.textContent = "Saving…";
    });

    var start = parseInt(form.getAttribute("data-wizard-start") || "0", 10) || 0;
    current = Math.min(Math.max(start, 0), steps.length - 1);
    render();
    form.__wizard = { go: go, next: next, back: back, render: render };
  }

  function initWizards(root) {
    (root || document).querySelectorAll("form[data-wizard]").forEach(initWizard);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { initWizards(); });
  } else {
    initWizards();
  }

  /* ---- Live tally: <div data-tally data-total="12" data-fields="a,b,c"> ----
     Shows how the counted parts add up against the declared total. */
  function initTallies() {
    document.querySelectorAll("[data-tally]").forEach(function (box) {
      var form = box.closest("form");
      var names = (box.getAttribute("data-fields") || "").split(",");
      var total = parseFloat(box.getAttribute("data-total")) || 0;
      var unit = box.getAttribute("data-unit") || "";
      function update() {
        var sum = 0;
        names.forEach(function (n) {
          var el = form.querySelector('[name="' + n.trim() + '"]');
          sum += el ? (parseFloat(el.value) || 0) : 0;
        });
        sum = Math.round(sum * 1000) / 1000;
        var diff = Math.round((sum - total) * 1000) / 1000;
        box.classList.toggle("is-even", diff === 0);
        box.classList.toggle("is-off", diff !== 0);
        box.innerHTML = "<span>Counted <b>" + sum + " " + esc(unit) + "</b> of <b>" +
          total + " " + esc(unit) + "</b> declared</span><span>" +
          (diff === 0 ? "Matches the label" : (diff > 0 ? "<b>" + diff + "</b> more than declared"
            : "<b>" + Math.abs(diff) + "</b> short of declared")) + "</span>";
      }
      form.addEventListener("input", update);
      update();
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTallies);
  } else {
    initTallies();
  }

  /* ---- Appearance: light / dark / match my device ----
     Switches at once, then saves the choice to the user's account so it
     follows them to any device.  Without JavaScript the form still posts. */
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form.id !== "themeForm") return;
    var btn = e.submitter;
    if (!btn || !btn.value) return;
    e.preventDefault();
    var pref = btn.value, root = document.documentElement;
    root.setAttribute("data-theme-pref", pref);
    if (pref === "system") {
      var light = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
      root.setAttribute("data-theme", light ? "light" : "dark");
    } else {
      root.setAttribute("data-theme", pref);
    }
    form.querySelectorAll(".theme-option").forEach(function (b) {
      var on = b === btn;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    var sw = document.getElementById("themeSwitch");
    if (sw) sw.open = false;
    var body = new FormData();
    body.append("theme", pref);
    fetch(form.action, { method: "POST", body: body,
                         headers: { "X-Requested-With": "fetch" } }).catch(function () {});
  });
  // Close the appearance menu on an outside click or Escape.
  document.addEventListener("click", function (e) {
    var sw = document.getElementById("themeSwitch");
    if (sw && sw.open && !sw.contains(e.target)) sw.open = false;
  });
  document.addEventListener("keydown", function (e) {
    var sw = document.getElementById("themeSwitch");
    if (e.key === "Escape" && sw && sw.open) sw.open = false;
  });

  /* ---- "About this page" note: remember if it was folded, per page ---- */
  var NOTE_KEY = "amamio.notesFolded";
  function foldedNotes() {
    try { return JSON.parse(window.localStorage.getItem(NOTE_KEY)) || {}; }
    catch (e) { return {}; }
  }
  whenReady(function () {
    var note = document.querySelector(".page-note[data-note-key]");
    if (!note) return;
    var key = note.getAttribute("data-note-key");
    if (foldedNotes()[key]) note.open = false;
    note.addEventListener("toggle", function () {
      var state = foldedNotes();
      if (note.open) delete state[key]; else state[key] = true;
      try { window.localStorage.setItem(NOTE_KEY, JSON.stringify(state)); } catch (e) { /* optional */ }
    });
  });

  /* ---- Hover tooltip for chart marks: any element with data-tip ---- */
  (function () {
    var tip = null;
    function show(el, e) {
      if (!tip) {
        tip = document.createElement("div");
        tip.className = "viz-tip";
        tip.setAttribute("role", "tooltip");
        document.body.appendChild(tip);
      }
      tip.textContent = el.getAttribute("data-tip");
      tip.style.display = "block";
      move(e);
    }
    function move(e) {
      if (!tip || tip.style.display !== "block") return;
      var x = e.clientX + 14, y = e.clientY + 14;
      var w = tip.offsetWidth, h = tip.offsetHeight;
      if (x + w > window.innerWidth - 8) x = e.clientX - w - 14;
      if (y + h > window.innerHeight - 8) y = e.clientY - h - 14;
      tip.style.left = x + "px";
      tip.style.top = y + "px";
    }
    document.addEventListener("mouseover", function (e) {
      var el = e.target.closest && e.target.closest("[data-tip]");
      if (el) show(el, e);
      else if (tip) tip.style.display = "none";
    });
    document.addEventListener("mousemove", move);
    document.addEventListener("scroll", function () { if (tip) tip.style.display = "none"; }, true);
  })();

  /* Expose a tiny namespace for inline page scripts. */
  window.IMS = {
    initWizards: initWizards,
    esc: esc,
    openModal: openModal,
    closeModal: function (id) {
      var m = document.getElementById(id);
      if (m) m.classList.remove("open");
    },
    fetchJSON: fetchJSON,
    paginate: paginateAll
  };
})();
