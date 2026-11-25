// SPDX-License-Identifier: Apache-2.0
// Shared by both manuals (no inline scripts: the Content-Security-Policy forbids them).
// place the numbers on the screenshots (coordinates computed by tools/make_manual_shots.py)
fetch("shots.json").then((r) => r.json()).then((shots) => {
  document.querySelectorAll("figure.shot").forEach((fig) => {
    const s = shots[fig.dataset.shot];
    if (!s) return;
    s.markers.forEach((m) => {
      const el = document.createElement("span");
      el.className = "mk"; el.textContent = m.n;
      el.style.left = m.x + "%"; el.style.top = m.y + "%";
      fig.appendChild(el);
    });
  });
});

// "Print / save as PDF" links
document.querySelectorAll("[data-print]").forEach((link) => link.addEventListener("click", (event) => {
  event.preventDefault();
  window.print();
}));
