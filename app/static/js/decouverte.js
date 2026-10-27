/* Découverte : recherche texte + filtre « Mes passions ». */
(function () {
  "use strict";
  var recherche = document.getElementById("recherche");
  var items = Array.prototype.slice.call(
    document.querySelectorAll("#liste-passions li[data-nom]"));
  var filtre = "toutes";

  function appliquer() {
    var q = (recherche.value || "").toLowerCase();
    items.forEach(function (li) {
      var nom = li.dataset.nom || "";
      var visible = nom.toLowerCase().indexOf(q) !== -1;
      if (filtre === "miennes" && li.dataset.mine !== "1") visible = false;
      li.style.display = visible ? "" : "none";
    });
  }

  recherche.addEventListener("input", appliquer);
  document.querySelectorAll(".chip[data-filtre]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      filtre = chip.dataset.filtre;
      document.querySelectorAll(".chip[data-filtre]").forEach(function (c) {
        c.classList.toggle("on", c === chip);
      });
      appliquer();
    });
  });
})();
