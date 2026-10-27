/* Page membre : bouton « Aimer » -> swipe like. */
(function () {
  "use strict";
  var script = document.currentScript;
  var SWIPE_URL = script.dataset.swipeUrl;
  var CSRF = document.querySelector('meta[name="csrf-token"]').content;
  var btn = document.getElementById("btn-aimer");
  var overlay = document.getElementById("match-overlay");
  var close = document.getElementById("match-close");

  if (close) {
    close.addEventListener("click", function () { overlay.hidden = true; });
  }
  if (!btn) return;

  btn.addEventListener("click", function () {
    btn.disabled = true;
    fetch(SWIPE_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": CSRF
      },
      body: JSON.stringify({ target: btn.dataset.uid, action: "like" })
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res && res.matched && overlay) overlay.hidden = false;
        else { btn.textContent = script.dataset.tLiked || "♥"; }
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = script.dataset.tRetry || "…";
      });
  });
})();
