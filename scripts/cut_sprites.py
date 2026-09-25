# Corta sprite sheets de frontend/sprites/custom/<id>/ en GIFs por estado.
#   uv run --no-project --with pillow --with scipy scripts/cut_sprites.py [id ...]
# Cada carpeta: sheet.png (8 poses en 2 filas de 4, o "rows": 1 para una sola fila; fondo transparente)
# y opcional sleep-src.png (tumbado).
# Las poses se numeran 0-7 en orden de lectura. Añade tu personaje a CHARS y al manifest.json.
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

CUSTOM = Path(__file__).resolve().parent.parent / "frontend/sprites/custom"
OUT_H = 390  # alto final en px: 3x los 130 px del manifest, para que se vea nítido con zoom
K = OUT_H // 130  # px de imagen por px "de juego" (atrezo, balanceos...)
ZZZ_FROM = CUSTOM / "bufon/sleep-src.png"  # de aquí salen las zetas si el tumbado no trae
CHARS = {
    # gif: (poses, ms por frame o lista de ms, uno por pose)
    "bufon": {"attack": ([2, 3, 4, 5], 180), "ask": ([7, 0], 700), "smooth": ["ask"]},
    "cazador": {"work": ([0, 2, 4, 3, 2, 5], [650, 550, 400, 900, 500, 950]), "attack": ([2, 3, 4, 5], 400), "ask": ([6, 0], 600),
                # durmiendo = pose 8 del sheet; se borran sus zetas fijas (caja en px del recorte) y se animan las nuestras
                "sleep_in_sheet": (200, 0, 444, 127),
                "smooth": ["work", "ask"]},
    # shells: una fila de 4 poses (de pie, caja sorpresa, sentado, caminando)
    "vagabundo": {"work": ([1, 0], [1400, 800]), "ask": ([3, 0], 700), "rows": 1, "sleep_pose": 2,
                  "smooth": ["work", "ask"]},
    # una fila: de pie con la espada, arrodillado, tumbado (no se usa), caminando con la espada al hombro
    "leproso": {"work": ([3, 0], [1300, 900]), "ask": ([0, 1], 800), "rows": 1, "sleep_pose": 1,
                "smooth": ["work", "ask"]},
    "medico": {"attack": ([2, 3, 4, 5], 900), "work": ([6, 5], 2100), "ask": ([7, 0], 700), "smooth": ["work", "ask"]},
}


def rgba(path):
    return np.array(Image.open(path).convert("RGBA"))


def hard_alpha(im):  # pixel art: nada de bordes semitransparentes
    a = np.array(im); a[..., 3] = np.where(a[..., 3] > 110, 255, 0); return Image.fromarray(a)


def components(a, min_px):
    """Etiqueta las piezas opacas; cada píxel suelto se asigna a la pieza grande más cercana."""
    m = a[..., 3] > 0
    lab, n = ndimage.label(m, structure=np.ones((3, 3)))
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    big = [k + 1 for k, s in enumerate(sizes) if s > min_px]
    dist, (iy, ix) = ndimage.distance_transform_edt(~np.isin(lab, big), return_indices=True)
    # a más de 25 px de cualquier pieza grande es basura del fondo: fuera (si no, estira el recorte)
    return np.where(m & (dist <= 25), lab[iy, ix], 0), big, sizes, ndimage.find_objects(lab)


def poses(a, rows=2):
    h = a.shape[0]
    own, big, _, objs = components(a, 8000)
    # dos poses pegadas entre filas (p. ej. humo que toca los pies de arriba): se parten por la mitad
    for k in list(big) if rows == 2 else []:
        ys = objs[k - 1][0]
        if ys.start < h * .45 and ys.stop > h * .55:
            new = own.max() + 1
            own[h // 2:][own[h // 2:] == k] = new; big.append(new)
    # en una fila, dos poses que se tocan (una espada, un pie): la pieza más ancha se parte por la
    # columna con menos píxeles de su tramo central
    while rows == 1 and len(big) < 4:
        k = max(big, key=lambda k: np.ptp(np.nonzero(own == k)[1]))
        cols = (own == k).sum(0)
        xs = np.nonzero(cols)[0]; x0, x1 = xs.min(), xs.max()
        mid = slice(x0 + (x1 - x0) * 3 // 10, x0 + (x1 - x0) * 7 // 10)
        cut = mid.start + int(np.argmin(cols[mid]))
        new = own.max() + 1
        own[:, cut:][own[:, cut:] == k] = new; big.append(new)
    assert len(big) == 4 * rows, f"esperaba {4 * rows} poses, hay {len(big)}"

    def key(k):
        ys, xs = np.nonzero(own == k); return (rows == 2 and ys.min() > h * .45, xs.min())
    frames = []
    for k in sorted(big, key=key):
        ys, xs = np.nonzero(own == k)
        f = a.copy(); f[own != k] = 0
        f = f[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        fh = f.shape[0]
        cx = np.nonzero(f[int(fh * .8):, :, 3])[1].mean()  # centro de los pies para alinear (no bailan entre poses)
        frames.append((f, cx))
    raw = [f for f, _ in frames]  # recortes a resolución original (para dormir con una pose del sheet)
    W = int(max(max(cx, f.shape[1] - cx) for f, cx in frames) * 2) + 2
    H = max(f.shape[0] for f, _ in frames)
    out = []
    for f, cx in frames:
        c = Image.new("RGBA", (W, H))
        c.alpha_composite(Image.fromarray(f), (int(W / 2 - cx), H - f.shape[0]))
        out.append(hard_alpha(c.resize((round(W * OUT_H / H), OUT_H), Image.LANCZOS)))
    return out, OUT_H / H, raw


def sleeping(src, size, fixed_sc=None):
    """Frames durmiendo: el cuerpo respira 1 px y aparecen 3 zetas una a una.
    Por defecto el cuerpo (tumbado) ocupa todo el ancho; con fixed_sc se usa esa escala y se centra."""
    b = rgba(src)
    own, parts, sizes, objs = components(b, 1000)
    body = max(parts, key=lambda k: sizes[k - 1])
    # extensión = la pieza principal (los píxeles perdidos lejos, p. ej. restos del fondo, se ignoran)
    ys, xs = np.nonzero(own[objs[body - 1]] == body)
    ys, xs = ys + objs[body - 1][0].start, xs + objs[body - 1][1].start
    # zetas = piezas sueltas que acaban por encima de la mitad del cuerpo (el resto son trozos del cuerpo)
    zs = sorted((k for k in parts if k != body and objs[k - 1][0].stop <= (ys.min() + ys.max()) / 2), key=lambda k: sizes[k - 1])
    own[np.isin(own, parts) & ~np.isin(own, zs)] = body
    y1, x0, x1 = ys.max() + 1, xs.min(), xs.max() + 1
    bsc = sc = fixed_sc or size[0] / (x1 - x0)
    off = (size[0] - (x1 - x0) * bsc) / 2  # 0 si ocupa todo el ancho

    def body_layer(stretch):
        f = b.copy(); f[own != body] = 0
        im = Image.fromarray(f[ys.min():y1, x0:x1])
        im = hard_alpha(im.resize((round(im.width * bsc), round(im.height * bsc)), Image.LANCZOS))
        if stretch:  # el lomo sube stretch px, los pies no se mueven
            im = im.resize((im.width, im.height + stretch), Image.NEAREST)
        c = Image.new("RGBA", size); c.alpha_composite(im, (round(off), size[1] - im.height)); return c

    if zs:  # zetas propias: en su sitio original
        zsrc, zown, zobjs = b, own, objs
        ax = off + (objs[zs[0] - 1][1].start - x0) * sc
        ay = size[1] - (y1 - objs[zs[0] - 1][0].stop) * sc
    else:  # prestadas: sobre el punto más alto del cuerpo
        zsrc = rgba(ZZZ_FROM)
        zown, zparts, zsizes, zobjs = components(zsrc, 1000)
        zbody = max(zparts, key=lambda k: zsizes[k - 1])
        zs = sorted((k for k in zparts if k != zbody), key=lambda k: zsizes[k - 1])
        sc = K * 152 / 1619  # misma escala de zetas que el bufón
        top = ys.min(); ax = off + (xs[ys == top].mean() - x0) * bsc
        ay = size[1] - (y1 - top) * bsc - 2 * K
    zx, zy = zobjs[zs[0] - 1][1].start, zobjs[zs[0] - 1][0].stop
    zh = (zobjs[zs[0] - 1][0].stop - zobjs[zs[0] - 1][0].start) * sc
    zg = max(1, 12 * K / zh)  # si la zeta pequeña queda diminuta, se agrandan todas desde su esquina
    zw = (max(zobjs[z - 1][1].stop for z in zs) - zx) * sc * zg
    ax = min(ax, size[0] - zw)  # que no se salgan por la derecha
    ay = max(ay, (zy - min(zobjs[z - 1][0].start for z in zs)) * sc * zg)  # ni por arriba

    def z_layer(z):
        f = zsrc.copy(); f[zown != z] = 0; oy, ox = zobjs[z - 1]
        im = Image.fromarray(f[oy, ox])
        im = hard_alpha(im.resize((round(im.width * sc * zg), round(im.height * sc * zg)), Image.LANCZOS))
        c = Image.new("RGBA", size)
        c.alpha_composite(im, (round(ax + (ox.start - zx) * sc * zg), round(ay + (oy.start - zy) * sc * zg)))
        return c

    out = []
    for nz, st in [(0, 0), (1, 1), (2, 0), (3, 1)]:
        c = body_layer(st * K)
        for z in zs[:nz]:
            c.alpha_composite(z_layer(z))
        out.append(c)
    return out


def smooth(frames, durations, step=80, fade=60):
    """Más fps: en cada pose sostenida respira (se estira hasta 2 px desde los pies) y entre poses
    mete 2 fotogramas de fundido. Devuelve (frames, lista de ms)."""
    out, ms = [], []
    for i, (f, d) in enumerate(zip(frames, durations)):
        hold = d - 2 * fade
        n = max(1, round(hold / step))
        for j in range(n):
            s = round(K * (1 - np.cos(2 * np.pi * j / max(n, 2))))  # 0 -> 2K -> 0 px
            b = f.getbbox()
            if s and b:
                body = f.crop(b); c = Image.new("RGBA", f.size)
                body = body.resize((body.width, body.height + s), Image.LANCZOS)
                c.alpha_composite(hard_alpha(body), (b[0], b[3] - body.height)); out.append(c)
            else:
                out.append(f)
            ms.append(hold / n)
        nxt = frames[(i + 1) % len(frames)]
        for t in (1 / 3, 2 / 3):
            out.append(hard_alpha(Image.blend(f, nxt, t))); ms.append(fade)
    return out, [round(m) for m in ms]


def save_gif(path, frames, ms):
    """GIF con paleta común de 255 colores + índice 0 transparente."""
    q = []
    for f in frames:
        pal = f.convert("RGB").quantize(255, method=Image.MEDIANCUT)
        p = np.array(pal) + 1; p[np.array(f)[..., 3] == 0] = 0
        img = Image.fromarray(p.astype(np.uint8), "P"); img.putpalette([0, 0, 0] + pal.getpalette()[:765])
        q.append(img)
    q[0].save(path, save_all=True, append_images=q[1:], duration=ms, loop=0, disposal=2, transparency=0)


# ---------- atrezo dibujado a mano (pixel art 1:1, contorno negro como los sprites) ----------
INK = (13, 10, 8, 255)


def glyph(rows, colors):
    """Dibujo a partir de filas de texto: cada carácter es un color de `colors`, '.' transparente."""
    im = Image.new("RGBA", (len(rows[0]), len(rows)))
    for y, r in enumerate(rows):
        for x, ch in enumerate(r):
            if ch != ".":
                im.putpixel((x, y), colors[ch])
    return im


def outlined(layer):
    """Añade contorno de 1 px alrededor de lo dibujado."""
    a = np.array(layer); m = a[..., 3] > 0
    ring = ndimage.binary_dilation(m, np.ones((3, 3))) & ~m
    a[ring] = INK
    return Image.fromarray(a)


NOTE = glyph(["....#..", "....##.", "....#.#", "....#..", "..###..", ".####..", ".###..."],
             {"#": (232, 184, 80, 255)})
NOTE2 = glyph(["..#####", "..#...#", "..#...#", "###.###", "###.###", "##..##."], {"#": (232, 184, 80, 255)})


def px_art(g):
    """Dibujo de 1 px con contorno, ampliado a la resolución de los sprites (K px por pixel)."""
    p = Image.new("RGBA", (g.width + 2, g.height + 2)); p.alpha_composite(g, (1, 1)); p = outlined(p)
    return p.resize((p.width * K, p.height * K), Image.NEAREST)


def bard(fr):
    """Bufón tocando: notas que salen del laúd y se van flotando hacia los lados (a animar al grupo)."""
    base, bob = fr[6], Image.new("RGBA", fr[6].size)
    bob.alpha_composite(fr[6].crop((0, 0, fr[6].width, OUT_H - 2 * K)), (0, 2 * K))
    W = base.width
    bx = base.getbbox()[2]  # borde derecho del bufón = clavijero del laúd
    sx, sy = bx - 10 * K, 44 * K
    n1, n2 = px_art(NOTE), px_art(NOTE2)
    notes = [(0, n1, 7), (3, n2, 3), (5, n1, 9), (8, n2, 4), (10, n1, 6)]  # (frame de salida, dibujo, deriva x)
    out = []
    for t in range(12):
        c = Image.new("RGBA", base.size); c.alpha_composite(base if t % 2 == 0 else bob)
        for t0, g, side in notes:
            age = (t - t0) % 12
            if age < 6:  # vive 6 frames: sale del laúd hacia el grupo, subiendo y ondulando
                x, y = sx + (age * side + (1 if age % 2 else -1)) * K, sy - age * 7 * K
                if 0 <= x < W - g.width and y >= 0:
                    c.alpha_composite(g, (x, y))
        out.append(c)
    return out, 220


PROPS = {"bufon": ("lute", bard)}  # GIF de trabajo con atrezo


def build(cid):
    d = CUSTOM / cid
    sheet = rgba(d / "sheet.png")
    fr, sheet_sc, raw = poses(sheet, CHARS[cid].get("rows", 2))
    for i, im in enumerate(fr):
        im.save(d / f"frame{i}.png")
    for name, (idx, ms) in ((k, v) for k, v in CHARS[cid].items() if k not in ("sleep_in_sheet", "sleep_pose", "smooth", "rows")):
        pick = []
        for i in idx:
            if isinstance(i, str):  # "bobN": pose N agachada 2 px (balanceo)
                n = int(i[3:]); c = Image.new("RGBA", fr[n].size)
                c.alpha_composite(fr[n].crop((0, 0, fr[n].width, OUT_H - 2 * K)), (0, 2 * K)); pick.append(c)
            else:
                pick.append(fr[i])
        if name in CHARS[cid].get("smooth", ()):
            pick, ms = smooth(pick, ms if isinstance(ms, list) else [ms] * len(pick))
        save_gif(d / f"{name}.gif", pick, ms)
    if cid in PROPS:
        name, fn = PROPS[cid]
        save_gif(d / f"{name}.gif", *fn(fr))
    if "sleep_in_sheet" in CHARS[cid]:  # durmiendo dentro del propio sheet (cuadrante de abajo a la derecha)
        h, w = sheet.shape[:2]
        crop = sheet[h // 2:, w * 3 // 4:].copy()
        x0, y0, x1, y1 = CHARS[cid]["sleep_in_sheet"]; crop[y0:y1, x0:x1, 3] = 0
        Image.fromarray(crop).save(d / "sleep-src.png")
        save_gif(d / "sleep.gif", sleeping(d / "sleep-src.png", fr[0].size, sheet_sc), 700)
    elif "sleep_pose" in CHARS[cid]:  # durmiendo = una pose del sheet tal cual (sin zetas propias)
        Image.fromarray(raw[CHARS[cid]["sleep_pose"]]).save(d / "sleep-src.png")
        save_gif(d / "sleep.gif", sleeping(d / "sleep-src.png", fr[0].size, sheet_sc), 700)
    elif (d / "sleep-src.png").exists():
        save_gif(d / "sleep.gif", sleeping(d / "sleep-src.png", fr[0].size), 700)
    print(cid, "ok", fr[0].size)


if __name__ == "__main__":
    for cid in sys.argv[1:] or CHARS:
        build(cid)
