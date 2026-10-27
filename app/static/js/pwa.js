/* PWA : enregistre le service worker et gère le bouton
   « Ajouter sur mon téléphone ».
   - Android/Chrome : l'événement beforeinstallprompt permet l'install native.
   - iPhone/Safari : pas d'événement — on affiche les consignes
     (Partager → Sur l'écran d'accueil). */
(function () {
  "use strict";

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" })
      .catch(function () { /* silencieux : l'app fonctionne sans */ });
  }

  // Sélecteur de langue : recharge la page avec ?lang=xx
  var sel = document.getElementById("lang-select");
  if (sel) {
    sel.addEventListener("change", function () {
      var url = new URL(window.location.href);
      url.searchParams.set("lang", sel.value);
      window.location.href = url.toString();
    });
  }

  var btn = document.getElementById("btn-install");
  var aide = document.getElementById("install-aide");
  var aideTexte = document.getElementById("install-aide-texte");
  var aideFermer = document.getElementById("install-aide-fermer");
  var deferred = null;

  if (!btn) return;

  var iOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  var dejaInstalle =
    window.matchMedia("(display-mode: standalone)").matches ||
    navigator.standalone === true;

  // Déjà installée : pas de bouton
  if (dejaInstalle) { btn.hidden = true; return; }

  // Toujours visible : le clic lance l'install native si le navigateur le
  // permet (deferred), sinon affiche les consignes adaptées à l'appareil.
  btn.hidden = false;

  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferred = e;
    btn.hidden = false;
  });

  btn.addEventListener("click", function () {
    if (deferred) {
      deferred.prompt();
      deferred.userChoice.then(function (choice) {
        if (choice.outcome === "accepted") btn.hidden = true;
        deferred = null;
      });
      return;
    }
    // Fallback : consignes selon l'appareil
    if (aideTexte) {
      aideTexte.textContent = iOS
        ? "Sur votre iPhone : touchez le bouton Partager (carré avec une flèche) en bas de Safari, puis « Sur l'écran d'accueil »."
        : "Dans le menu de votre navigateur (⋮ ou ⋯), choisissez « Ajouter à l'écran d'accueil » ou « Installer l'application ».";
    }
    if (aide) aide.hidden = false;
  });

  if (aideFermer) {
    aideFermer.addEventListener("click", function () {
      aide.hidden = true;
    });
  }
})();
