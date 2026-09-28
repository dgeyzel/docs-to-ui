// App shell behavior: the theme toggle and the source form. Not included in
// exported pages.
(function () {
  "use strict";

  const THEME_KEY = "d2u-theme";

  function currentTheme() {
    const forced = document.documentElement.getAttribute("data-theme");
    if (forced === "light" || forced === "dark") {
      return forced;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function initThemeToggle() {
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      button.addEventListener("click", function () {
        const next = currentTheme() === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        try {
          localStorage.setItem(THEME_KEY, next);
        } catch {
          // Storage can be unavailable (private mode); the toggle still works.
        }
      });
    });
  }

  function initSourceForm() {
    document.querySelectorAll("[data-source-form]").forEach(function (form) {
      form.addEventListener("submit", function () {
        // Only the visible panel's input is sent, so a leftover file or text
        // in the hidden panel doesn't trigger "not both".
        form.querySelectorAll("[role=tabpanel][hidden]").forEach(function (panel) {
          panel.querySelectorAll("input[type=file], textarea").forEach(function (input) {
            input.value = "";
          });
        });
      });
    });
  }

  function init() {
    initThemeToggle();
    initSourceForm();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
