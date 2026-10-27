/* EftiSocial — pile de cartes « Trouver ».
   Swipe tactile (pointer events) + boutons. Aucune dépendance. */
(function () {
  "use strict";
  var script = document.currentScript;
  var DECK_URL = script.dataset.deckUrl;
  var SWIPE_URL = script.dataset.swipeUrl;
  var CSRF = document.querySelector('meta[name="csrf-token"]').content;
  var deck = document.getElementById("deck");
  var overlay = document.getElementById("match-overlay");
  var cards = [];
  var busy = false;

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function buildCard(data, idx) {
    var el = document.createElement("div");
    el.className = "carte";
    el.style.zIndex = 100 - idx;
    var photo = data.photo_url
      ? '<img src="' + esc(data.photo_url) + '" alt="">'
      : '<div class="photo-vide">' + esc((data.first_name || "?")[0]) + "</div>";
    var tags = (data.shared_interests || [])
      .map(function (i) { return '<span class="tag">' + esc(i) + "</span>"; })
      .join("");
    el.innerHTML =
      photo +
      '<span class="marque-like" hidden>AIMER</span>' +
      '<span class="marque-pass" hidden>NON</span>' +
      '<div class="carte-info"><h2>' + esc(data.first_name) + "</h2>" +
      (data.bio ? "<p>" + esc(data.bio) + "</p>" : "") +
      '<div class="tags">' + tags + "</div>" +
      (data.shared
        ? '<p class="petit">' + data.shared + " " + esc(script.dataset.tShared || "") + "</p>"
        : "") +
      "</div>";
    el.dataset.uid = data.id;
    attachSwipe(el);
    return el;
  }

  function attachSwipe(el) {
    var startX = 0, dx = 0, dragging = false;
    var like = el.querySelector(".marque-like");
    var pass = el.querySelector(".marque-pass");

    el.addEventListener("pointerdown", function (e) {
      if (busy) return;
      dragging = true;
      startX = e.clientX;
      el.setPointerCapture(e.pointerId);
      el.style.transition = "none";
    });
    el.addEventListener("pointermove", function (e) {
      if (!dragging) return;
      dx = e.clientX - startX;
      el.style.transform =
        "translateX(" + dx + "px) rotate(" + dx / 18 + "deg)";
      like.hidden = dx <= 30;
      pass.hidden = dx >= -30;
    });
    function release(commit) {
      if (!dragging) return;
      dragging = false;
      el.style.transition = "";
      var seuil = el.offsetWidth * 0.35;
      if (dx > seuil || commit === "like") swipe(el, "like");
      else if (dx < -seuil || commit === "pass") swipe(el, "pass");
      else {
        el.style.transform = "";
        like.hidden = pass.hidden = true;
      }
      dx = 0;
    }
    el.addEventListener("pointerup", function () { release(); });
    el.addEventListener("pointercancel", function () { release(); });
    el._release = release;
  }

  function topCard() {
    return deck.querySelector(".carte");
  }

  function swipe(el, action) {
    if (busy) return;
    busy = true;
    var off = action === "like" ? el.offsetWidth * 1.6 : -el.offsetWidth * 1.6;
    el.style.transform =
      "translateX(" + off + "px) rotate(" + off / 15 + "deg)";
    setTimeout(function () { el.remove(); }, 220);
    fetch(SWIPE_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": CSRF
      },
      body: JSON.stringify({ target: el.dataset.uid, action: action })
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        busy = false;
        if (res && res.matched && overlay) {
          var n = document.getElementById("match-name");
          if (n) n.textContent = "";
          overlay.hidden = false;
        }
        if (!topCard()) loadDeck();
      })
      .catch(function () { busy = false; });
  }

  function loadDeck() {
    deck.innerHTML = '<p class="vide">' + esc(script.dataset.tLoading || "…") + "</p>";
    fetch(DECK_URL, { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        deck.innerHTML = "";
        cards = data.cards || [];
        if (!cards.length) {
          deck.innerHTML = '<p class="vide">' +
            esc(script.dataset.tEmpty || "") + "</p>";
          return;
        }
        // La première carte (meilleur score) est affichée au-dessus
        cards.forEach(function (c, i) {
          var el = buildCard(c, i);
          el.style.zIndex = cards.length - i;
          deck.appendChild(el);
        });
      })
      .catch(function () {
        deck.innerHTML = '<p class="vide">' +
          esc(script.dataset.tError || "Erreur") + "</p>";
      });
  }

  document.getElementById("btn-like").addEventListener("click", function () {
    var c = topCard(); if (c) swipe(c, "like");
  });
  document.getElementById("btn-pass").addEventListener("click", function () {
    var c = topCard(); if (c) swipe(c, "pass");
  });
  var close = document.getElementById("match-close");
  if (close) close.addEventListener("click", function () {
    overlay.hidden = true;
  });

  loadDeck();
})();
