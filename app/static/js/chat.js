/* EftiSocial — tchat entre membres matchés.
   Polling toutes les 4 s. Contenu inséré via textContent (anti-XSS). */
(function () {
  "use strict";
  var script = document.currentScript;
  var MSGS_URL = script.dataset.msgsUrl;
  var SEND_URL = script.dataset.sendUrl;
  var CSRF = document.querySelector('meta[name="csrf-token"]').content;
  var box = document.getElementById("tchat");
  var form = document.getElementById("form-msg");
  var input = document.getElementById("msg-input");
  var lastId = 0;
  var timer = null;

  function heure(iso) {
    var d = new Date(iso);
    return d.toLocaleTimeString("fr-CA", { hour: "2-digit", minute: "2-digit" });
  }

  function addMsg(m) {
    var div = document.createElement("div");
    div.className = "bulle " + (m.mine ? "bulle-moi" : "bulle-autre");
    var txt = document.createElement("span");
    txt.textContent = m.body;           // textContent : jamais de HTML
    var meta = document.createElement("span");
    meta.className = "bulle-heure";
    meta.textContent = heure(m.created_at);
    div.appendChild(txt);
    div.appendChild(meta);
    box.appendChild(div);
    lastId = Math.max(lastId, m.id);
  }

  function scrollBas() {
    box.scrollTop = box.scrollHeight;
  }

  function poll() {
    fetch(MSGS_URL + "?after=" + lastId,
          { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var recu = false;
        (data.messages || []).forEach(function (m) {
          addMsg(m); recu = true;
        });
        if (recu) scrollBas();
      })
      .catch(function () { /* réseau : on retente au prochain tour */ });
    timer = setTimeout(poll, 4000);
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var body = input.value.trim();
    if (!body) return;
    input.value = "";
    fetch(SEND_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": CSRF
      },
      body: JSON.stringify({ body: body })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.message) { addMsg(data.message); scrollBas(); }
      })
      .catch(function () { input.value = body; });
    input.focus();
  });

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) poll();
  });

  poll();
})();
