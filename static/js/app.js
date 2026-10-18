// Atelier Trésorerie — comportements communs à toutes les pages.
(function () {
  "use strict";

  // ---------- Thème clair / sombre ----------
  const root = document.documentElement;
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    const dark = root.classList.toggle("dark");
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch (e) { /* stockage indisponible */ }
    document.dispatchEvent(new CustomEvent("themechange", { detail: { dark } })); // pour Chart.js (étape 3)
  });

  // ---------- Sidebar mobile ----------
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("backdrop");
  const setMenu = (open) => {
    sidebar?.classList.toggle("-translate-x-full", !open);
    backdrop?.classList.toggle("hidden", !open);
  };
  document.getElementById("menu-toggle")?.addEventListener("click", () => setMenu(true));
  backdrop?.addEventListener("click", () => setMenu(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setMenu(false); });

  // ---------- État de l'IA locale ----------
  async function refreshHealth() {
    const dot = document.getElementById("ollama-dot");
    const label = document.getElementById("ollama-label");
    const detail = document.getElementById("ollama-detail");
    try {
      const res = await fetch("/api/health", { headers: { Accept: "application/json" } });
      const { ollama } = await res.json();
      let color, text;
      if (!ollama.available) {
        color = "bg-loss"; text = "Ollama hors ligne";
      } else if (!ollama.model_installed) {
        color = "bg-warn"; text = `Modèle ${ollama.model} absent`;
      } else {
        color = "bg-gain"; text = `${ollama.model} prêt`;
      }
      if (dot) dot.className = `h-2.5 w-2.5 rounded-full ${color}`;
      if (label) { label.textContent = text; label.title = ollama.error || ""; }
      if (detail) { detail.textContent = text; detail.title = ollama.error || ""; }
    } catch (err) {
      if (label) label.textContent = "État indisponible";
    }
  }
  refreshHealth();
})();
