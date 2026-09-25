// Personajes y fondos: todo sale de frontend/sprites/custom/manifest.json (ver README).

// Sin manifest (clon recién hecho) la web sigue funcionando con este marcador.
const PLACEHOLDER = { id: "?", name: "Sin personajes", blurb: "crea sprites/custom/manifest.json", kind: "images",
                      images: {}, height: 96, animated: false };

/**
 * Formato:
 * {
 *   "characters": {
 *     "mi-heroe": { "name": "Mi héroe",
 *                   "images": { "idle": "custom/heroe_idle.gif", "working": "custom/heroe_ataque.gif",
 *                               "needs_input": "custom/heroe_idle.gif" },
 *                   "height": 96, "animated": true }
 *   },
 *   "defaults": { "claude": "mi-heroe" },   // por tipo de agente; "other-agent" = resto de agentes
 *   "backgrounds": [ { "src": "custom/bg/mazmorra.jpg", "fx": "dungeon" } ]   // fx: dungeon|forest|storm|ashes
 * }
 */
export async function loadRegistry() {
  const chars = {};
  let defaults = {}, backgrounds = [];
  try {
    const r = await fetch("sprites/custom/manifest.json", { cache: "no-store" });
    if (r.ok) {
      const m = await r.json();
      for (const [id, def] of Object.entries(m.characters || {})) {
        chars[id] = { id, name: def.name || id, blurb: def.blurb || "custom", kind: "images",
                      images: Object.fromEntries(Object.entries(def.images || {})
                        .map(([k, v]) => [k, "sprites/" + v.replace(/^\/+/, "")])),
                      height: def.height || 96, animated: !!def.animated };
      }
      defaults = m.defaults || {};
      backgrounds = (m.backgrounds || []).map((b) => ({ src: "sprites/" + b.src.replace(/^\/+/, ""), fx: b.fx }));
    }
  } catch { /* sin manifest: marcador */ }
  if (!Object.keys(chars).length) chars["?"] = PLACEHOLDER;
  return { chars, defaults, backgrounds };
}

/** Crea el <img> del personaje para un estado. */
export function spriteImg(ch, state = "idle") {
  const img = document.createElement("img");
  img.className = "sprite custom";
  img.draggable = false;
  img.alt = ch.name;
  const src = ch.images[state] || ch.images.idle || Object.values(ch.images)[0];
  if (src) img.src = src;
  img.style.height = ch.height + "px";
  if (ch.animated) img.classList.add("self-animated");
  return img;
}
