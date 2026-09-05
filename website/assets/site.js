// Controls for the grids. Progressive enhancement only: every table is complete in
// the HTML and fully readable with JS disabled.
(function () {
  var KEY = "evmintel.chains";
  var gridRunners = [];

  // ---- chain picker: which columns every grid shows, remembered across pages ----
  var toggles = Array.prototype.slice.call(
    document.querySelectorAll("[data-chain-toggle]"));

  // Fingerprint of the current chain universe. A saved selection is only meaningful
  // against the same set of chains, so when the site is regenerated with chains
  // added or removed we drop the stored list rather than apply it to stale columns.
  var universe = toggles.map(function (t) { return t.dataset.chainToggle; })
                        .sort().join(",");

  function load() {
    try {
      var v = JSON.parse(localStorage.getItem(KEY));
      if (!v || v.universe !== universe || !Array.isArray(v.list)) return null;
      return v.list;
    } catch (e) { return null; }
  }
  function save(list) {
    try {
      if (list) localStorage.setItem(KEY, JSON.stringify({ universe: universe, list: list }));
      else localStorage.removeItem(KEY);
    } catch (e) { /* private browsing — the view still works, it just won't persist */ }
  }

  function applyColumns() {
    var on = {};
    var n = 0;
    toggles.forEach(function (t) {
      on[t.dataset.chainToggle] = t.checked;
      if (t.checked) n++;
    });
    document.querySelectorAll("[data-chain]").forEach(function (cell) {
      cell.classList.toggle("col-off", on[cell.dataset.chain] === false);
    });
    var label = document.getElementById("picker-label");
    if (label) {
      label.textContent = "Chains: " +
        (n === toggles.length ? "all" : n === 0 ? "none" : n + " of " + toggles.length);
    }
    save(n === toggles.length ? null : toggles.filter(function (t) { return t.checked; })
                                              .map(function (t) { return t.dataset.chainToggle; }));
    gridRunners.forEach(function (r) { r(); });
  }

  if (toggles.length) {
    var saved = load();
    if (saved) {
      toggles.forEach(function (t) {
        t.checked = saved.indexOf(t.dataset.chainToggle) !== -1;
      });
    }
    toggles.forEach(function (t) { t.addEventListener("change", applyColumns); });
    var all = document.querySelector("[data-chain-all]");
    var none = document.querySelector("[data-chain-none]");
    if (all) all.addEventListener("click", function () {
      toggles.forEach(function (t) { t.checked = true; }); applyColumns();
    });
    if (none) none.addEventListener("click", function () {
      toggles.forEach(function (t) { t.checked = false; }); applyColumns();
    });
    applyColumns();
  }

  // ---- per-grid filter + hide-uniform ----------------------------------------
  var boxes = Array.prototype.slice.call(document.querySelectorAll("[data-filter]"));

  function wire(tid) {
    var target = document.getElementById(tid);
    if (!target) return null;
    var rows = Array.prototype.slice.call(target.querySelectorAll("tbody tr"));
    var out = document.getElementById(tid + "-count");
    var box = document.querySelector('[data-filter="' + tid + '"]');
    var chk = document.querySelector('[data-uniform-for="' + tid + '"]');
    // "every chain agrees" has to mean every VISIBLE chain: with three columns
    // selected, a row those three share is uniform even if a hidden fourth differs.
    // The server-side data-uniform flag is the no-JS fallback.
    function isUniform(r) {
      var seen = null;
      var cells = r.querySelectorAll("td[data-chain]");
      for (var i = 0; i < cells.length; i++) {
        if (cells[i].classList.contains("col-off")) continue;
        var v = cells[i].textContent.trim();
        if (seen === null) seen = v;
        else if (v !== seen) return false;
      }
      return seen !== null;
    }
    function run() {
      var q = box && box.value ? box.value.trim().toLowerCase() : "";
      var hideUniform = chk && chk.checked;
      var n = 0;
      rows.forEach(function (r) {
        var hit = (!q || r.textContent.toLowerCase().indexOf(q) !== -1) &&
                  !(hideUniform && isUniform(r));
        r.hidden = !hit;
        if (hit) n++;
      });
      if (out) {
        out.textContent = (n === rows.length)
          ? rows.length + " rows"
          : n + " of " + rows.length + " rows";
      }
    }
    if (box) box.addEventListener("input", run);
    if (chk) chk.addEventListener("change", run);
    return run;
  }

  var runners = gridRunners;
  boxes.forEach(function (b) {
    var run = wire(b.dataset.filter);
    if (run) { runners.push(run); run(); }
  });

  var q = new URLSearchParams(location.search).get("q");
  if (q) {
    boxes.forEach(function (b) { b.value = q; });
    runners.forEach(function (r) { r(); });
  }

  // A row addressed by #hash must be visible even if a filter is hiding it.
  function revealTarget() {
    var el = location.hash && document.querySelector(location.hash);
    while (el) {
      if (el.hidden) el.hidden = false;
      el = el.parentElement;
    }
  }
  window.addEventListener("hashchange", revealTarget);
  revealTarget();
})();
