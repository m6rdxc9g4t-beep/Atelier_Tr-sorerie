/* Atelier — préférence de thème commune à la suite (v2).
   Source de vérité : Atelier_Projets/design-system/brand/atelier-theme.js, copiée telle quelle dans chaque app.
   À charger le plus tôt possible (script bloquant dans <head>, ou premier import du point d'entrée)
   pour poser le thème avant l'affichage.

   Préférence : "system" | "light" | "dark".
   - Sur le VPS (hôte en …atelier.<domaine>) : cookie atelier_theme sur le domaine de la suite, partagé
     par le portail et toutes les apps (un changement dans une app vaut pour toutes).
   - Ailleurs (Vercel, app de bureau, localhost) : localStorage « atelier:theme ».
   Effet : <html data-theme="light|dark"> + classe "dark" (Tailwind) + data-theme-pref.

   API : window.atelierTheme.get() → préférence, .set(pref), .resolved() → "light" | "dark".
   Événement : "atelier-theme" sur window à chaque changement (detail = préférence). */
(function () {
  var KEY = 'atelier:theme';
  var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  var valid = function (v) { return v === 'light' || v === 'dark' || v === 'system'; };

  function suiteDomain() {
    var parts = location.hostname.split('.');
    var i = parts.indexOf('atelier');
    return i >= 0 && i < parts.length - 1 ? parts.slice(i).join('.') : null;
  }
  function get() {
    var m = document.cookie.match(/(?:^|; )atelier_theme=(light|dark|system)/);
    if (m) return m[1];
    try { var v = localStorage.getItem(KEY); if (valid(v)) return v; } catch (e) {}
    return 'system';
  }
  function resolved(pref) {
    pref = pref || get();
    return pref === 'dark' || (pref === 'system' && media && media.matches) ? 'dark' : 'light';
  }
  function apply(pref) {
    var r = document.documentElement;
    var mode = resolved(pref);
    r.dataset.theme = mode;
    r.dataset.themePref = pref;
    r.classList.toggle('dark', mode === 'dark');
    r.style.colorScheme = mode;
  }
  function set(pref) {
    if (!valid(pref)) return;
    apply(pref);
    try { localStorage.setItem(KEY, pref); } catch (e) {}
    var d = suiteDomain();
    if (d) {
      document.cookie = 'atelier_theme=' + pref + '; Domain=' + d + '; Path=/; Max-Age=31536000; SameSite=Lax' +
        (location.protocol === 'https:' ? '; Secure' : '');
    }
    window.dispatchEvent(new CustomEvent('atelier-theme', { detail: pref }));
  }

  apply(get());
  if (media && media.addEventListener) {
    media.addEventListener('change', function () { if (get() === 'system') apply('system'); });
  }
  // Un autre onglet (ou une autre app de la suite) a changé le thème : on suit au retour sur la page.
  document.addEventListener('visibilitychange', function () { if (!document.hidden) apply(get()); });

  window.atelierTheme = { get: get, set: set, resolved: function () { return resolved(); } };
})();
