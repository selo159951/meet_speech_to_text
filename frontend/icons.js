/* Vector icon set. No emoji and no symbol characters in the interface: every icon is an inline SVG.
   24x24 grid, 2 px round strokes, drawn in the style of the open Lucide set (ISC licence).
   ic("trash") -> <svg>;  <button data-icon="info"> is filled in by hydrateIcons(). */
const ICON_PATHS = {
  plus: '<path d="M5 12h14M12 5v14"/>',
  "merge-up": '<path d="M5 3h14M18 13l-6-6-6 6M12 7v14"/>',
  trash: '<path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  keyboard: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  "chevron-up": '<path d="m18 15-6-6-6 6"/>',
  "chevron-down": '<path d="m6 9 6 6 6-6"/>',
  replace: '<path d="M8 3 4 7l4 4M4 7h16M16 21l4-4-4-4M20 17H4"/>',
  play: '<path d="M7 4.5v15a1 1 0 0 0 1.5.9l12-7.5a1 1 0 0 0 0-1.8l-12-7.5A1 1 0 0 0 7 4.5Z" fill="currentColor"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor"/><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3"/>',
  "arrow-right": '<path d="M5 12h14M12 5l7 7-7 7"/>',
  "arrow-left": '<path d="M19 12H5M12 19l-7-7 7-7"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4M12 17h.01"/>',
  dot: '<circle cx="12" cy="12" r="3" fill="currentColor"/>',
  "user-search": '<circle cx="10" cy="7" r="4"/><path d="M10.3 15H7a4 4 0 0 0-4 4v2"/><circle cx="17" cy="17" r="3"/><path d="m21 21-1.9-1.9"/>',
};

function ic(name) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("class", "ic");
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = ICON_PATHS[name] || "";
  return s;
}

/* icon followed by text: icText("check", "Saved") */
function icText(name, text) {
  const f = document.createDocumentFragment();
  f.append(ic(name));
  if (text) f.append(" " + text);
  return f;
}

/* elements with data-icon get their icon in front of whatever text they hold (call again after the text changes) */
function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((e) => {
    e.querySelectorAll(":scope > svg.ic").forEach((x) => x.remove());
    e.prepend(ic(e.dataset.icon));
    if (e.textContent.trim() && !(e.childNodes[1]?.nodeType === 3 && /^\s/.test(e.childNodes[1].data))) e.firstChild.after(" ");
  });
}
