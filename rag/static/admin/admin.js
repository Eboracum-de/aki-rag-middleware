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

  document.querySelectorAll(".bulk-run-toggle").forEach(function (toggle) {
    toggle.addEventListener("change", function () {
      document.querySelectorAll('input[name="run_id"].bulk-run-item').forEach(function (box) {
        box.checked = toggle.checked;
      });
    });
  });

  document.querySelectorAll(".bulk-run-form").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var checked = document.querySelectorAll('input[name="run_id"].bulk-run-item:checked').length;
      if (!checked) {
        event.preventDefault();
        window.alert("Bitte mindestens eine Recherche auswählen.");
      }
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

  document.querySelectorAll("form.claim-builder[data-claim-builder]").forEach(function (form) {
    var subject = form.querySelector('select[name="subject_entity_id"]');
    var predicate = form.querySelector('select[name="predicate_id"]');
    var object = form.querySelector('select[name="object_entity_id"]');
    var hint = form.querySelector(".claim-builder-hint");
    var submit = form.querySelector('button[type="submit"]');
    if (!subject || !predicate || !object) return;

    var options = Array.from(predicate.options);
    function applyCompatibility(preferFirstForSubject) {
      if (preferFirstForSubject) {
        var firstForSubject = options.find(function (option) {
          return option.dataset.subject === subject.value;
        });
        if (firstForSubject) object.value = firstForSubject.dataset.object || "";
      }
      var firstVisible = null;
      options.forEach(function (option) {
        var visible = option.dataset.subject === subject.value &&
          option.dataset.object === object.value &&
          subject.value !== object.value;
        option.hidden = !visible;
        option.disabled = !visible;
        if (visible && !firstVisible) firstVisible = option;
      });
      if (firstVisible) {
        options.forEach(function (option) { option.selected = false; });
        firstVisible.selected = true;
        predicate.disabled = false;
        if (submit) submit.disabled = false;
        if (hint) hint.textContent = "Nur für dieses gerichtete Entity-Paar zulässige Ontologie-Relationen werden angezeigt.";
      } else {
        predicate.selectedIndex = -1;
        predicate.disabled = true;
        if (submit) submit.disabled = true;
        if (hint) hint.textContent = "Für dieses gerichtete Entity-Paar ist keine Ontologie-Relation zugelassen.";
      }
    }

    if (options.length) {
      subject.value = options[0].dataset.subject || subject.value;
      object.value = options[0].dataset.object || object.value;
    }
    applyCompatibility(false);
    subject.addEventListener("change", function () { applyCompatibility(true); });
    object.addEventListener("change", function () { applyCompatibility(false); });
  });

  document.querySelectorAll("form.confirm-submit[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (event.defaultPrevented) return;
      if (!window.confirm(form.dataset.confirm || "Aktion wirklich ausführen?")) {
        event.preventDefault();
      }
    });
  });
});
