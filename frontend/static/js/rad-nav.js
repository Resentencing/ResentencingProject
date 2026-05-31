document.addEventListener("DOMContentLoaded", () => {
  const header = document.querySelector(".rad-site-header");
  if (!header) return;
  const toggle = header.querySelector(".rad-nav-toggle");
  const panel = header.querySelector("#rad-header-nav-panel");
  if (!toggle || !panel) return;

  function setNavOpen(open) {
    header.classList.toggle("rad-site-header--nav-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
  }

  toggle.addEventListener("click", () => {
    setNavOpen(!header.classList.contains("rad-site-header--nav-open"));
  });

  panel.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => setNavOpen(false));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setNavOpen(false);
  });

  window.matchMedia("(min-width: 901px)").addEventListener("change", (event) => {
    if (event.matches) setNavOpen(false);
  });
});
