// Characters and backgrounds: everything comes from frontend/sprites/custom/manifest.json (see README).

// Without a manifest (fresh clone) the web still works with this placeholder.
const PLACEHOLDER = { id: "?", name: "No characters", blurb: "create sprites/custom/manifest.json", kind: "images",
                      images: {}, height: 96, animated: false };

/**
 * Format:
 * {
 *   "characters": {
 *     "my-hero": { "name": "My hero",
 *                   "images": { "idle": "custom/hero_idle.gif", "working": "custom/hero_attack.gif",
 *                               "needs_input": "custom/hero_idle.gif" },
 *                   "height": 96, "animated": true }
 *   },
 *   "defaults": { "claude": "my-hero" },    // per agent type; "other-agent" = every other agent
 *   "backgrounds": [ { "src": "custom/bg/dungeon.jpg", "fx": "dungeon" } ]   // fx: dungeon|forest|storm|ashes
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
  } catch { /* no manifest: placeholder */ }
  if (!Object.keys(chars).length) chars["?"] = PLACEHOLDER;
  return { chars, defaults, backgrounds };
}

/** Builds the character's <img> for a state. */
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
