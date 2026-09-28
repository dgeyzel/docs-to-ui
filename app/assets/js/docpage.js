// Doc-page interactivity: collapsible sections, tabs, copy buttons and
// navigation highlighting. Vanilla JS with no network access, so it also
// works inside standalone HTML exports.
(function () {
  "use strict";

  const COPIED_LABEL_MS = 2000;

  function setExpanded(toggle, expanded) {
    toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    const target = document.getElementById(toggle.getAttribute("aria-controls"));
    if (target) {
      target.hidden = !expanded;
    }
  }

  function initCollapsibles() {
    document.querySelectorAll("[data-collapse-toggle]").forEach(function (toggle) {
      toggle.addEventListener("click", function () {
        setExpanded(toggle, toggle.getAttribute("aria-expanded") !== "true");
      });
    });
  }

  function selectTab(tab) {
    const tablist = tab.closest("[role=tablist]");
    tablist.querySelectorAll("[role=tab]").forEach(function (other) {
      const selected = other === tab;
      other.setAttribute("aria-selected", selected ? "true" : "false");
      other.tabIndex = selected ? 0 : -1;
      const panel = document.getElementById(other.getAttribute("aria-controls"));
      if (panel) {
        panel.hidden = !selected;
      }
    });
  }

  function initTabs() {
    document.querySelectorAll("[data-tabs]").forEach(function (container) {
      const tabs = Array.from(container.querySelectorAll("[data-tab]"));
      tabs.forEach(function (tab, index) {
        tab.addEventListener("click", function () {
          selectTab(tab);
        });
        tab.addEventListener("keydown", function (event) {
          let next = null;
          if (event.key === "ArrowRight") {
            next = tabs[(index + 1) % tabs.length];
          } else if (event.key === "ArrowLeft") {
            next = tabs[(index - 1 + tabs.length) % tabs.length];
          }
          if (next) {
            event.preventDefault();
            selectTab(next);
            next.focus();
          }
        });
      });
    });
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    // Fallback for contexts without the async clipboard API.
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand("copy");
    document.body.removeChild(area);
    return copied ? Promise.resolve() : Promise.reject(new Error("Copy failed"));
  }

  function initCopyButtons() {
    document.querySelectorAll("[data-copy]").forEach(function (button) {
      const label = button.textContent;
      button.addEventListener("click", function () {
        const code = button.parentElement.querySelector("pre");
        if (!code) {
          return;
        }
        copyText(code.textContent).then(
          function () {
            button.textContent = "Copied";
            window.setTimeout(function () {
              button.textContent = label;
            }, COPIED_LABEL_MS);
          },
          function () {
            button.textContent = "Copy failed";
            window.setTimeout(function () {
              button.textContent = label;
            }, COPIED_LABEL_MS);
          },
        );
      });
    });
  }

  function expandTarget(id) {
    const card = id ? document.getElementById(id) : null;
    if (!card) {
      return;
    }
    const toggle = card.querySelector("[data-collapse-toggle]");
    if (toggle && toggle.getAttribute("aria-expanded") === "false") {
      setExpanded(toggle, true);
    }
  }

  function initNavigation() {
    const links = Array.from(document.querySelectorAll("[data-nav-link]"));
    const byId = new Map();
    links.forEach(function (link) {
      const id = decodeURIComponent(link.hash.slice(1));
      byId.set(id, link);
      link.addEventListener("click", function () {
        expandTarget(id);
      });
    });
    expandTarget(decodeURIComponent(window.location.hash.slice(1)));

    if (!("IntersectionObserver" in window) || links.length === 0) {
      return;
    }
    const observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) {
            return;
          }
          links.forEach(function (link) {
            link.removeAttribute("aria-current");
          });
          const active = byId.get(entry.target.id);
          if (active) {
            active.setAttribute("aria-current", "true");
          }
        });
      },
      { rootMargin: "0px 0px -70% 0px" },
    );
    byId.forEach(function (_, id) {
      const card = document.getElementById(id);
      if (card) {
        observer.observe(card);
      }
    });
  }

  function init() {
    initCollapsibles();
    initTabs();
    initCopyButtons();
    initNavigation();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
