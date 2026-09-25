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
    # una fila: brazos abiertos, agachada, dormida (trae sus zetas), caminando
    "joana": {"work": ([3, 0], [1500, 1300]), "ask": ([0, 1], 1100), "rows": 1, "sleep_pose": 2,
              "sleep_erase": (340, 0, 420, 24),
              "smooth": ["work", "ask"], "fades": 5, "key": {"th": 4, "peel": 1, "close": 8}},  # top negro: recorte fino
    # 2 filas: quieto, carga, hacha en alto cargando, carga con la cabeza baja /
    #          alza el hacha, toro encabritado, dormido sobre el toro, recibe un golpe
    "volosin": {"work": ([1, 3, 2, 5], [1000, 900, 1100, 1200]), "ask": ([4, 0], 1100), "sleep_pose": 6,
                "sleep_squash": (0.70, 0.3), "fades": 5,  # toro echado; fundidos largos = más fluido
                "key": {"peel": 0, "close": 22},  # ropa negra: sin pelar (se come los brazos) y tapando agujeros
                "smooth": ["work", "ask"]},
    "medico": {"attack": ([2, 3, 4, 5], 900), "work": ([6, 5], 2100), "ask": ([7, 0], 700), "smooth": ["work", "ask"]},
}


def rgba(path):
    return np.array(Image.open(path).convert("RGBA"))


def key_black(a, th=6, outline=3, peel=3, close=0):
    """Sheet con fondo negro opaco: quita el negro conectado con los bordes (el de dentro de la figura
    se queda) y repone un contorno oscuro de `outline` px como el del resto de personajes."""
    if a[..., 3].min() < 255:
        return a  # ya tiene transparencia
    lab, _ = ndimage.label(a[..., :3].max(-1) < th)
    border = np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    bg = np.isin(lab, border[border > 0])
    fig = ndimage.binary_opening(~bg, iterations=2)  # fuera motas sueltas del fondo
    if close:  # sombras casi negras por donde el recorte se cuela (entrepierna…): cierra y rellena
        lab, n = ndimage.label(fig)
        for k, sl in enumerate(ndimage.find_objects(lab), 1):  # figura a figura: sin puentes entre poses
            pad = tuple(slice(max(0, x.start - close), x.stop + close) for x in sl)
            one = lab[pad] == k
            if one.sum() > 1000:
                fig[pad] |= ndimage.binary_fill_holes(ndimage.binary_closing(one, iterations=close))
    dark = a[..., :3].max(-1) < 45
    for _ in range(peel):  # el halo oscuro del borde se pela capa a capa (umbral bajo = no rompe la ropa negra)
        fig &= ~(dark & ndimage.binary_dilation(~fig))
    ring = ndimage.binary_dilation(fig, iterations=outline) & ~fig
    a = a.copy(); a[~fig] = 0; a[ring] = INK
    return a


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
    own, big, sizes, objs = components(a, 8000)
    thr = 0.25 * max(sizes[k - 1] for k in big)
    if any(sizes[k - 1] < thr for k in big):  # polvo, hachas sueltas…: no son poses, van con la más cercana
        own, big, sizes, objs = components(a, thr)
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

    out, zl = [], [z_layer(z) for z in zs]
    for f in range(16):  # respira despacio (0 -> K -> 0 px) y las zetas salen una a una
        c = body_layer(round(K * (1 - np.cos(2 * np.pi * f / 16)) / 2))
        for z in zl[:f * 4 // 16]:
            c.alpha_composite(z)
        out.append(c)
    return out


def smooth(frames, durations, step=80, fade=60, fades=2):
    """Más fps: en cada pose sostenida respira (se estira hasta 2 px desde los pies) y entre poses
    mete `fades` fotogramas de fundido. Devuelve (frames, lista de ms)."""
    out, ms = [], []
    for i, (f, d) in enumerate(zip(frames, durations)):
        hold = d - fades * fade
        n = max(1, round(hold / step))
        for j in range(n):
            out.append(breathe(f, round(K * (1 - np.cos(2 * np.pi * j / max(n, 2))))))  # 0 -> 2K -> 0 px
            ms.append(hold / n)
        nxt = frames[(i + 1) % len(frames)]
        # disolución sin huecos: siempre hay una pose entera. 1ª mitad: A completa y B aparece encima;
        # 2ª mitad: B completa y lo que queda de A se va por detrás. (Image.blend oscurecía y medio
        # borraba el cuerpo cuando las poses no coinciden.)
        A, B = np.array(f), np.array(nxt)
        noise = np.random.default_rng(i).random(A.shape[:2])
        for j in range(1, fades + 1):
            u = j / (fades + 1)
            if u < 0.5:
                c = A.copy(); m = (B[..., 3] > 0) & (noise < 2 * u)
                c[m] = B[m]
            else:
                c = B.copy(); m = (A[..., 3] > 0) & (B[..., 3] == 0) & (noise >= 2 * u - 1)
                c[m] = A[m]
            out.append(Image.fromarray(c)); ms.append(fade)
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


def breathe(f, s):
    """La figura se estira s px hacia arriba desde los pies (respirar, balancearse)."""
    b = f.getbbox()
    if not s or not b:
        return f
    body = f.crop(b); c = Image.new("RGBA", f.size)
    body = body.resize((body.width, body.height + s), Image.LANCZOS)
    c.alpha_composite(hard_alpha(body), (b[0], b[3] - body.height))
    return c


def bard(fr):
    """Bufón tocando: se balancea al compás y las notas salen del laúd flotando hacia el grupo."""
    base = fr[6]
    W = base.width
    bx = base.getbbox()[2]  # borde derecho del bufón = clavijero del laúd
    sx, sy = bx - 10 * K, 44 * K
    n1, n2 = px_art(NOTE), px_art(NOTE2)
    N, LIFE = 36, 12  # frames del bucle y de vida de cada nota: una en el aire cada vez, sin montones
    notes = [(0, n1, 1.8), (12, n2, 1.1), (24, n1, 2.4)]  # (salida, dibujo, deriva x)
    out = []
    for t in range(N):
        beat = abs(np.sin(np.pi * 4 * t / N))  # 4 golpes por compás
        tilt = 4 * np.sin(2 * np.pi * t / N)  # se mece de lado a lado, pivotando en los pies
        c = breathe(base, round(3 * K * beat))
        c = hard_alpha(c.rotate(tilt, resample=Image.BICUBIC, center=(W / 2, OUT_H - 1)))
        for t0, g, drift in notes:
            age = (t - t0) % N
            if age < LIFE:  # sube y se abre hacia el grupo, ondulando
                x = sx + round((age * drift + 5 * np.sin(age / 2)) * K)
                y = sy - round(age * 3.2 * K)
                if 0 <= x < W - g.width and y >= 0:
                    c.alpha_composite(g, (x, y))
        out.append(c)
    return out, 90


PROPS = {"bufon": ("lute", bard)}  # GIF de trabajo con atrezo


def build(cid):
    d = CUSTOM / cid
    sheet = key_black(rgba(d / "sheet.png"), **CHARS[cid].get("key", {}))  # p. ej. {"peel": 0}
    fr, sheet_sc, raw = poses(sheet, CHARS[cid].get("rows", 2))
    for i, im in enumerate(fr):
        im.save(d / f"frame{i}.png")
    for name, (idx, ms) in ((k, v) for k, v in CHARS[cid].items() if k not in ("sleep_in_sheet", "sleep_pose", "sleep_erase", "sleep_squash", "smooth", "rows", "key", "fades")):
        pick = []
        for i in idx:
            if isinstance(i, str):  # "bobN": pose N agachada 2 px (balanceo)
                n = int(i[3:]); c = Image.new("RGBA", fr[n].size)
                c.alpha_composite(fr[n].crop((0, 0, fr[n].width, OUT_H - 2 * K)), (0, 2 * K)); pick.append(c)
            else:
                pick.append(fr[i])
        if name in CHARS[cid].get("smooth", ()):
            pick, ms = smooth(pick, ms if isinstance(ms, list) else [ms] * len(pick), fades=CHARS[cid].get("fades", 2))
        save_gif(d / f"{name}.gif", pick, ms)
    if cid in PROPS:
        name, fn = PROPS[cid]
        save_gif(d / f"{name}.gif", *fn(fr))
    if "sleep_in_sheet" in CHARS[cid]:  # durmiendo dentro del propio sheet (cuadrante de abajo a la derecha)
        h, w = sheet.shape[:2]
        crop = sheet[h // 2:, w * 3 // 4:].copy()
        x0, y0, x1, y1 = CHARS[cid]["sleep_in_sheet"]; crop[y0:y1, x0:x1, 3] = 0
        Image.fromarray(crop).save(d / "sleep-src.png")
        save_gif(d / "sleep.gif", sleeping(d / "sleep-src.png", fr[0].size, sheet_sc), 220)
    elif "sleep_pose" in CHARS[cid]:  # durmiendo = una pose del sheet tal cual (sin zetas propias)
        crop = raw[CHARS[cid]["sleep_pose"]].copy()
        if "sleep_erase" in CHARS[cid]:  # caja (px del recorte) con las zetas fijas del dibujo
            x0, y0, x1, y1 = CHARS[cid]["sleep_erase"]; crop[y0:y1, x0:x1, 3] = 0
        if "sleep_squash" in CHARS[cid]:  # (desde, factor): aplasta lo de abajo = patas recogidas, echado
            frac, k = CHARS[cid]["sleep_squash"]
            im = Image.fromarray(crop); cut = int(im.height * frac)
            legs = im.crop((0, cut, im.width, im.height))
            legs = legs.resize((im.width, max(1, round(legs.height * k))), Image.LANCZOS)
            out = Image.new("RGBA", (im.width, cut + legs.height))
            out.alpha_composite(im.crop((0, 0, im.width, cut))); out.alpha_composite(legs, (0, cut))
            crop = np.array(out)
        Image.fromarray(crop).save(d / "sleep-src.png")
        save_gif(d / "sleep.gif", sleeping(d / "sleep-src.png", fr[0].size, sheet_sc), 220)
    elif (d / "sleep-src.png").exists():
        save_gif(d / "sleep.gif", sleeping(d / "sleep-src.png", fr[0].size), 220)
    print(cid, "ok", fr[0].size)


if __name__ == "__main__":
    for cid in sys.argv[1:] or CHARS:
        build(cid)
