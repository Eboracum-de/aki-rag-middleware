"use strict";

document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".bulk-toggle").forEach(function (toggle) {
    toggle.addEventListener("change", function () {
      var form = toggle.closest("form");
      if (!form) return;
      form.querySelectorAll('input[name="finding_id"]').forEach(function (box) {
        box.checked = toggle.checked;
      });
    });
  });

  document.querySelectorAll(".bulk-finding-form").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var submitter = event.submitter;
      var checked = form.querySelectorAll('input[name="finding_id"]:checked').length;
      if (!checked) {
        event.preventDefault();
        window.alert("Bitte mindestens ein Finding auswählen.");
        return;
      }
      if (submitter && submitter.value === "resolve") {
        var target = form.querySelector('select[name="target_entity_id"]');
        if (!target || !target.value) {
          event.preventDefault();
          window.alert("Bitte eine Ziel-Entity auswählen.");
        }
      }
    });
  });

  document.querySelectorAll("form.confirm-submit[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm || "Aktion wirklich ausführen?")) {
        event.preventDefault();
      }
    });
  });
});
