// Personajes pixel art ORIGINALES (16x~18), dibujados en canvas en runtime.
// Para usar tus propios sprites: frontend/sprites/custom/manifest.json (ver README).

const OUTLINE = "#140f16";
const SKIN = { s: "#d9a878", S: "#a8744e" };

export const BUILTIN = {
  templar: {
    name: "Templario", blurb: "Caballero de acero y fe",
    palette: { k: OUTLINE, m: "#b9c2cc", M: "#6d7784", v: "#2a2230", t: "#2f4f8f", T: "#203766",
               g: "#d8b64a", b: "#5a3a22", e: "#e8eef2", h: "#7a5230", l: "#3a3f4a" },
    rows: [
      "......kkkk......",
      ".....kmmmmk...e.",
      "....kmmmmmMk..e.",
      "....kmmmmmMk..e.",
      "....kvvvvvvk..e.",
      "....kmmmmmMk..e.",
      ".....kmmmMk...e.",
      "...kkTttttTkk.e.",
      "..kmkttggttkmke.",
      "..kmktggggtkmggg",
      "..kmkttggttkmkh.",
      "..kMkTttttTkMkh.",
      "..kkkbbbbbbkkm..",
      "....kttttttk....",
      "....kTttttTk....",
      "....kllkkllk....",
      "....kllkkllk....",
      "...kMMk..kMMk...",
      "...kkkk..kkkk...",
    ],
  },
  hexer: {
    name: "Hechicera", blurb: "Lee runas en la oscuridad",
    palette: { k: OUTLINE, p: "#5b2a86", P: "#3b1a5a", ...SKIN, h: "#2a1a2a", e: "#7fffd4",
               r: "#3a2f5a", R: "#251d3d", w: "#6b4a2a", o: "#7df9ff", O: "#2fb5c9" },
    rows: [
      "........k.......",
      ".......kpk...oo.",
      "......kpppk.oOOo",
      ".....kpppPk.oOOo",
      "...kppppppPPk.w.",
      "....khssssShk.w.",
      "....khseseShk.w.",
      "....khssssShk.w.",
      "...khhkrrkhhk.w.",
      "...krrrrrrrRkkw.",
      "..krrrrrrrrRksw.",
      "..krrrrrrrrRk.w.",
      "..kRrrrrrrrRk.w.",
      "..kRrrrrrrrRk.w.",
      "..kRRrrrrrRRk.w.",
      ".kRRRrrrrrRRRkw.",
      ".kkkkkkkkkkkkkw.",
    ],
  },
  cutpurse: {
    name: "Ratero", blurb: "Capucha verde, daga rápida",
    palette: { k: OUTLINE, g: "#3f6b3a", G: "#28462a", f: "#1f1a1a", e: "#ffd36b", ...SKIN,
               l: "#6b4a30", L: "#4a321f", b: "#2a2a2a", d: "#dfe6ea" },
    rows: [
      "......kkkk......",
      ".....kggggk.....",
      "....kgggggGk....",
      "...kgggffggGk...",
      "...kggfefeGGk...",
      "...kgGffffGGk...",
      "...kGgfssfGGk...",
      "..kgGGkkkkGGgk..",
      "..kggllllllggk..",
      ".kggllLllLllggk.",
      ".ksklllllllLksk.",
      ".kdkLllllllLk.k.",
      "..dkLLbbbbLLk...",
      "..d.kllllllk....",
      "....kLllllLk....",
      "....kllkkllk....",
      "....kLLk.kLLk...",
      "...kkkk..kkkk...",
    ],
  },
  anchorite: {
    name: "Ermitaño", blurb: "Silencio, cuerda y farol",
    palette: { k: OUTLINE, ...SKIN, r: "#6b4a2e", R: "#4a3220", y: "#c9a25a", l: "#3a3a3a", L: "#ffd86b" },
    rows: [
      "................",
      "......kkkk......",
      ".....kssssk.....",
      "....ksssssSk....",
      "....kskskSSk....",
      "....ksssssSk....",
      ".....kSssSk.....",
      "...kkrrrrrrkk...",
      "..krrrrrrrrRRk..",
      "..krRrrrrrrRRk..",
      "..ksRyyyyyyRskl.",
      "..kkRrrrrrrRklLl",
      "...kRrrrrrrRklLl",
      "...kRrrrrrrRRkl.",
      "...kRRrrrrrRRk..",
      "..kRRRrrrrrRRRk.",
      "..kkkkkkkkkkkkk.",
    ],
  },
  bonewalker: {
    name: "Osario", blurb: "Hueso viejo, espada oxidada",
    palette: { k: OUTLINE, b: "#e6e0cc", B: "#a9a28a", r: "#ff4a3a", x: "#9a5a32" },
    rows: [
      "................",
      "......kkkk......",
      ".....kbbbbk.....",
      "....kbbbbbBk....",
      "....kbrkbrkk....",
      "....kbbbbbBk....",
      ".....kbkbkk.....",
      "......kbbk......",
      "....kkbbbbkk....",
      "...kbkbBBbkbk...",
      "...kbkbkkbkbk...",
      "...kbkbBBbkbk.x.",
      "....kkbbbbkkkxk.",
      ".....kbkkbk..x..",
      ".....kbkkbk..x..",
      ".....kbkkbk.....",
      "....kbbkkbbk....",
      "....kkkk.kkkk...",
    ],
  },
  vagrant: {
    name: "Vagabundo", blurb: "Una shell cualquiera con horca",
    palette: { k: OUTLINE, c: "#7a4a2a", C: "#55331c", ...SKIN, t: "#b8a27a", T: "#8a7654",
               p: "#4a4a5a", w: "#6b4a2a", f: "#aab0b8", b: "#3a2a1a" },
    rows: [
      ".............f.f",
      "......kkkk...fff",
      ".....kcccck...w.",
      "....kcccccCk..w.",
      "....kssssssk..w.",
      "....kskssksk..w.",
      "....ksssssSk..w.",
      ".....kSssSk...w.",
      "...kkttttttkk.w.",
      "..kttttttttTTkw.",
      "..ktTttttttTksw.",
      "..kskttttttTk.w.",
      "...kbbbbbbbbk.w.",
      "....kppppppk..w.",
      "....kppkkppk..w.",
      "....kppk.kppk.w.",
      "...kkkk..kkkk...",
    ],
  },
};

export const BUILTIN_DEFAULTS = {
  claude: "templar", codex: "hexer", "other-agent": "cutpurse", shell: "vagrant",
};

const cache = new Map();

/** Genera un dataURL PNG a tamaño 1:1 (se escala con CSS image-rendering: pixelated). */
export function renderPixels(def) {
  if (cache.has(def)) return cache.get(def);
  const h = def.rows.length;
  const w = Math.max(...def.rows.map((r) => r.length));
  const cv = document.createElement("canvas");
  cv.width = w; cv.height = h;
  const ctx = cv.getContext("2d");
  def.rows.forEach((row, y) => {
    [...row].forEach((ch, x) => {
      const col = def.palette[ch];
      if (!col) return;
      ctx.fillStyle = col;
      ctx.fillRect(x, y, 1, 1);
    });
  });
  const out = { url: cv.toDataURL(), w, h };
  cache.set(def, out);
  return out;
}

/**
 * Registro de personajes = builtin + custom (sprites/custom/manifest.json si existe).
 * Formato custom:
 * {
 *   "characters": {
 *     "mi-heroe": { "name": "Mi héroe",
 *                   "images": { "idle": "custom/heroe_idle.gif", "working": "custom/heroe_ataque.gif",
 *                               "needs_input": "custom/heroe_idle.gif" },
 *                   "height": 96, "animated": true }
 *   },
 *   "defaults": { "claude": "mi-heroe" }
 * }
 */
export async function loadRegistry() {
  const chars = {};
  for (const [id, def] of Object.entries(BUILTIN)) chars[id] = { id, ...def, kind: "pixels" };
  let defaults = { ...BUILTIN_DEFAULTS };
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
      defaults = { ...defaults, ...(m.defaults || {}) };
    }
  } catch { /* sin custom: vale */ }
  return { chars, defaults };
}

/** Crea el <img> del personaje para un estado. scale = px por pixel en builtin. */
export function spriteImg(ch, state = "idle", scale = 4) {
  const img = document.createElement("img");
  img.className = "sprite";
  img.draggable = false;
  img.alt = ch.name;
  if (ch.kind === "pixels") {
    const { url, w, h } = renderPixels(ch);
    img.src = url;
    img.width = w * scale; img.height = h * scale;
  } else {
    img.src = ch.images[state] || ch.images.idle || Object.values(ch.images)[0];
    img.style.height = ch.height + "px";
    img.classList.add("custom");
    if (ch.animated) img.classList.add("self-animated");
  }
  return img;
}
