document.addEventListener("DOMContentLoaded", () => {
  const header = document.querySelector(".rad-site-header");
  const toggle = document.querySelector(".rad-nav-toggle");
  const panel = document.getElementById("rad-header-nav-panel");
  if (!header || !toggle || !panel) return;

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
