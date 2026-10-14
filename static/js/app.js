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

  (function initGroups() {
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
  })();

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

  /* Expose a tiny namespace for inline page scripts. */
  window.IMS = {
    openModal: openModal,
    closeModal: function (id) {
      var m = document.getElementById(id);
      if (m) m.classList.remove("open");
    },
    fetchJSON: fetchJSON,
    paginate: paginateAll
  };
})();
