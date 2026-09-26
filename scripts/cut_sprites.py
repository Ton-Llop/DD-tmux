# Cuts sprite sheets from frontend/sprites/custom/<id>/ into one GIF per state.
#   uv run --no-project --with pillow --with scipy scripts/cut_sprites.py [id ...]
# Each folder: sheet.png (8 poses in 2 rows of 4, or "rows": 1 for a single row; transparent background)
# and an optional sleep-src.png (lying down).
# Poses are numbered 0-7 in reading order. Add your character to CHARS and to manifest.json.
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

CUSTOM = Path(__file__).resolve().parent.parent / "frontend/sprites/custom"
OUT_H = 390  # final height in px: 3x the manifest's 130 px, so it stays crisp when zoomed
K = OUT_H // 130  # image px per "game" px (props, sways...)
ZZZ_FROM = CUSTOM / "bufon/sleep-src.png"  # the z's come from here if the sleeping pose has none
CHARS = {
    # gif: (poses, ms per frame or a list of ms, one per pose)
    "bufon": {"attack": ([2, 3, 4, 5], 180), "ask": ([7, 0], 700), "smooth": ["ask"]},
    "cazador": {"work": ([0, 2, 4, 3, 2, 5], [650, 550, 400, 900, 500, 950]), "attack": ([2, 3, 4, 5], 400), "ask": ([6, 0], 600),
                # sleeping = pose 8 of the sheet; its baked-in z's are erased (box in crop px) and ours are animated
                "sleep_in_sheet": (200, 0, 444, 127),
                "smooth": ["work", "ask"]},
    # shells: one row of 4 poses (standing, jack-in-the-box, sitting, walking)
    "vagabundo": {"work": ([1, 0], [1400, 800]), "ask": ([3, 0], 700), "rows": 1, "sleep_pose": 2,
                  "smooth": ["work", "ask"]},
    # one row: standing with the sword, kneeling, lying down (unused), walking with the sword on the shoulder
    "leproso": {"work": ([3, 0], [1300, 900]), "ask": ([0, 1], 800), "rows": 1, "sleep_pose": 1,
                "smooth": ["work", "ask"]},
    # one row: arms open, crouching, asleep (brings its own z's), walking
    "joana": {"work": ([3, 0], [1500, 1300]), "ask": ([0, 1], 1100), "rows": 1, "sleep_pose": 2,
              "sleep_erase": (340, 0, 420, 24),
              "smooth": ["work", "ask"], "fades": 5, "key": {"th": 4, "peel": 1, "close": 8}},  # black top: fine cut
    # 2 rows: still, charge, charging with axe raised, charge with head down /
    #         raises the axe, rearing bull, asleep on the bull, takes a hit
    "volosin": {"work": ([1, 3, 2, 5], [1000, 900, 1100, 1200]), "ask": ([4, 0], 1100), "sleep_pose": 6,
                "sleep_squash": (0.70, 0.3), "fades": 5,  # bull lying down; long fades = smoother
                "key": {"peel": 0, "close": 22},  # black clothes: no peeling (it eats the arms) and filling holes
                "smooth": ["work", "ask"]},
    "medico": {"attack": ([2, 3, 4, 5], 900), "work": ([6, 5], 2100), "ask": ([7, 0], 700), "smooth": ["work", "ask"]},
}


def rgba(path):
    return np.array(Image.open(path).convert("RGBA"))


def key_black(a, th=6, outline=3, peel=3, close=0):
    """Sheet with an opaque black background: removes the black connected to the edges (black inside the figure
    stays) and restores a dark `outline` px contour like the other characters have."""
    if a[..., 3].min() < 255:
        return a  # already has transparency
    lab, _ = ndimage.label(a[..., :3].max(-1) < th)
    border = np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    bg = np.isin(lab, border[border > 0])
    fig = ndimage.binary_opening(~bg, iterations=2)  # drop loose background specks
    if close:  # near-black shadows where the cut leaks in (crotch…): close and fill
        lab, n = ndimage.label(fig)
        for k, sl in enumerate(ndimage.find_objects(lab), 1):  # figure by figure: no bridges between poses
            pad = tuple(slice(max(0, x.start - close), x.stop + close) for x in sl)
            one = lab[pad] == k
            if one.sum() > 1000:
                fig[pad] |= ndimage.binary_fill_holes(ndimage.binary_closing(one, iterations=close))
    dark = a[..., :3].max(-1) < 45
    for _ in range(peel):  # the dark edge halo is peeled layer by layer (low threshold = black clothes survive)
        fig &= ~(dark & ndimage.binary_dilation(~fig))
    ring = ndimage.binary_dilation(fig, iterations=outline) & ~fig
    a = a.copy(); a[~fig] = 0; a[ring] = INK
    return a


def hard_alpha(im):  # pixel art: no semi-transparent edges
    a = np.array(im); a[..., 3] = np.where(a[..., 3] > 110, 255, 0); return Image.fromarray(a)


def components(a, min_px):
    """Labels the opaque pieces; each loose pixel goes to the nearest big piece."""
    m = a[..., 3] > 0
    lab, n = ndimage.label(m, structure=np.ones((3, 3)))
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    big = [k + 1 for k, s in enumerate(sizes) if s > min_px]
    dist, (iy, ix) = ndimage.distance_transform_edt(~np.isin(lab, big), return_indices=True)
    # more than 25 px from any big piece is background junk: drop it (otherwise it stretches the crop)
    return np.where(m & (dist <= 25), lab[iy, ix], 0), big, sizes, ndimage.find_objects(lab)


def poses(a, rows=2):
    h = a.shape[0]
    own, big, sizes, objs = components(a, 8000)
    thr = 0.25 * max(sizes[k - 1] for k in big)
    if any(sizes[k - 1] < thr for k in big):  # dust, loose axes…: not poses, they join the nearest one
        own, big, sizes, objs = components(a, thr)
    # two poses touching across rows (e.g. smoke touching the feet above): split down the middle
    for k in list(big) if rows == 2 else []:
        ys = objs[k - 1][0]
        if ys.start < h * .45 and ys.stop > h * .55:
            new = own.max() + 1
            own[h // 2:][own[h // 2:] == k] = new; big.append(new)
    # in one row, two poses that touch (a sword, a foot): the widest piece is split at the
    # column with the fewest pixels in its middle stretch
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
        cx = np.nonzero(f[int(fh * .8):, :, 3])[1].mean()  # feet centre for alignment (no jitter between poses)
        frames.append((f, cx))
    raw = [f for f, _ in frames]  # crops at original resolution (to sleep with a sheet pose)
    W = int(max(max(cx, f.shape[1] - cx) for f, cx in frames) * 2) + 2
    H = max(f.shape[0] for f, _ in frames)
    out = []
    for f, cx in frames:
        c = Image.new("RGBA", (W, H))
        c.alpha_composite(Image.fromarray(f), (int(W / 2 - cx), H - f.shape[0]))
        out.append(hard_alpha(c.resize((round(W * OUT_H / H), OUT_H), Image.LANCZOS)))
    return out, OUT_H / H, raw


def sleeping(src, size, fixed_sc=None):
    """Sleeping frames: the body breathes 1 px and 3 z's appear one by one.
    By default the (lying) body fills the width; with fixed_sc that scale is used and it is centred."""
    b = rgba(src)
    own, parts, sizes, objs = components(b, 1000)
    body = max(parts, key=lambda k: sizes[k - 1])
    # extent = the main piece (stray pixels far away, e.g. background leftovers, are ignored)
    ys, xs = np.nonzero(own[objs[body - 1]] == body)
    ys, xs = ys + objs[body - 1][0].start, xs + objs[body - 1][1].start
    # z's = loose pieces ending above the middle of the body (the rest are body parts)
    zs = sorted((k for k in parts if k != body and objs[k - 1][0].stop <= (ys.min() + ys.max()) / 2), key=lambda k: sizes[k - 1])
    own[np.isin(own, parts) & ~np.isin(own, zs)] = body
    y1, x0, x1 = ys.max() + 1, xs.min(), xs.max() + 1
    bsc = sc = fixed_sc or size[0] / (x1 - x0)
    off = (size[0] - (x1 - x0) * bsc) / 2  # 0 if it fills the width

    def body_layer(stretch):
        f = b.copy(); f[own != body] = 0
        im = Image.fromarray(f[ys.min():y1, x0:x1])
        im = hard_alpha(im.resize((round(im.width * bsc), round(im.height * bsc)), Image.LANCZOS))
        if stretch:  # the back rises stretch px, the feet stay put
            im = im.resize((im.width, im.height + stretch), Image.NEAREST)
        c = Image.new("RGBA", size); c.alpha_composite(im, (round(off), size[1] - im.height)); return c

    if zs:  # own z's: in their original place
        zsrc, zown, zobjs = b, own, objs
        ax = off + (objs[zs[0] - 1][1].start - x0) * sc
        ay = size[1] - (y1 - objs[zs[0] - 1][0].stop) * sc
    else:  # borrowed: above the body's highest point
        zsrc = rgba(ZZZ_FROM)
        zown, zparts, zsizes, zobjs = components(zsrc, 1000)
        zbody = max(zparts, key=lambda k: zsizes[k - 1])
        zs = sorted((k for k in zparts if k != zbody), key=lambda k: zsizes[k - 1])
        sc = K * 152 / 1619  # same z scale as the jester
        top = ys.min(); ax = off + (xs[ys == top].mean() - x0) * bsc
        ay = size[1] - (y1 - top) * bsc - 2 * K
    zx, zy = zobjs[zs[0] - 1][1].start, zobjs[zs[0] - 1][0].stop
    zh = (zobjs[zs[0] - 1][0].stop - zobjs[zs[0] - 1][0].start) * sc
    zg = max(1, 12 * K / zh)  # if the small z ends up tiny, all of them grow from their corner
    zw = (max(zobjs[z - 1][1].stop for z in zs) - zx) * sc * zg
    ax = min(ax, size[0] - zw)  # keep them inside on the right
    ay = max(ay, (zy - min(zobjs[z - 1][0].start for z in zs)) * sc * zg)  # and at the top

    def z_layer(z):
        f = zsrc.copy(); f[zown != z] = 0; oy, ox = zobjs[z - 1]
        im = Image.fromarray(f[oy, ox])
        im = hard_alpha(im.resize((round(im.width * sc * zg), round(im.height * sc * zg)), Image.LANCZOS))
        c = Image.new("RGBA", size)
        c.alpha_composite(im, (round(ax + (ox.start - zx) * sc * zg), round(ay + (oy.start - zy) * sc * zg)))
        return c

    out, zl = [], [z_layer(z) for z in zs]
    for f in range(16):  # breathes slowly (0 -> K -> 0 px) and the z's come out one by one
        c = body_layer(round(K * (1 - np.cos(2 * np.pi * f / 16)) / 2))
        for z in zl[:f * 4 // 16]:
            c.alpha_composite(z)
        out.append(c)
    return out


def smooth(frames, durations, step=80, fade=60, fades=2):
    """More fps: each held pose breathes (stretches up to 2 px from the feet) and between poses
    it adds `fades` crossfade frames. Returns (frames, list of ms)."""
    out, ms = [], []
    for i, (f, d) in enumerate(zip(frames, durations)):
        hold = d - fades * fade
        n = max(1, round(hold / step))
        for j in range(n):
            out.append(breathe(f, round(K * (1 - np.cos(2 * np.pi * j / max(n, 2))))))  # 0 -> 2K -> 0 px
            ms.append(hold / n)
        nxt = frames[(i + 1) % len(frames)]
        # gapless dissolve: there is always one whole pose. 1st half: A whole and B appears on top;
        # 2nd half: B whole and what is left of A fades behind. (Image.blend darkened and half
        # erased the body when the poses did not match.)
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
    """GIF with a shared 255-colour palette + transparent index 0."""
    q = []
    for f in frames:
        pal = f.convert("RGB").quantize(255, method=Image.MEDIANCUT)
        p = np.array(pal) + 1; p[np.array(f)[..., 3] == 0] = 0
        img = Image.fromarray(p.astype(np.uint8), "P"); img.putpalette([0, 0, 0] + pal.getpalette()[:765])
        q.append(img)
    q[0].save(path, save_all=True, append_images=q[1:], duration=ms, loop=0, disposal=2, transparency=0)


# ---------- hand-drawn props (1:1 pixel art, black outline like the sprites) ----------
INK = (13, 10, 8, 255)


def glyph(rows, colors):
    """Drawing from rows of text: each character is a colour from `colors`, '.' is transparent."""
    im = Image.new("RGBA", (len(rows[0]), len(rows)))
    for y, r in enumerate(rows):
        for x, ch in enumerate(r):
            if ch != ".":
                im.putpixel((x, y), colors[ch])
    return im


def outlined(layer):
    """Adds a 1 px outline around the drawing."""
    a = np.array(layer); m = a[..., 3] > 0
    ring = ndimage.binary_dilation(m, np.ones((3, 3))) & ~m
    a[ring] = INK
    return Image.fromarray(a)


NOTE = glyph(["....#..", "....##.", "....#.#", "....#..", "..###..", ".####..", ".###..."],
             {"#": (232, 184, 80, 255)})
NOTE2 = glyph(["..#####", "..#...#", "..#...#", "###.###", "###.###", "##..##."], {"#": (232, 184, 80, 255)})


def px_art(g):
    """1 px drawing with outline, scaled up to sprite resolution (K px per pixel)."""
    p = Image.new("RGBA", (g.width + 2, g.height + 2)); p.alpha_composite(g, (1, 1)); p = outlined(p)
    return p.resize((p.width * K, p.height * K), Image.NEAREST)


def breathe(f, s):
    """The figure stretches s px upward from the feet (breathing, swaying)."""
    b = f.getbbox()
    if not s or not b:
        return f
    body = f.crop(b); c = Image.new("RGBA", f.size)
    body = body.resize((body.width, body.height + s), Image.LANCZOS)
    c.alpha_composite(hard_alpha(body), (b[0], b[3] - body.height))
    return c


def bard(fr):
    """Jester playing: sways to the beat and notes float from the lute toward the party."""
    base = fr[6]
    W = base.width
    bx = base.getbbox()[2]  # jester's right edge = the lute's pegbox
    sx, sy = bx - 10 * K, 44 * K
    n1, n2 = px_art(NOTE), px_art(NOTE2)
    N, LIFE = 36, 12  # loop frames and each note's lifetime: one in the air at a time, no piles
    notes = [(0, n1, 1.8), (12, n2, 1.1), (24, n1, 2.4)]  # (start, drawing, x drift)
    out = []
    for t in range(N):
        beat = abs(np.sin(np.pi * 4 * t / N))  # 4 beats per bar
        tilt = 4 * np.sin(2 * np.pi * t / N)  # rocks side to side, pivoting on the feet
        c = breathe(base, round(3 * K * beat))
        c = hard_alpha(c.rotate(tilt, resample=Image.BICUBIC, center=(W / 2, OUT_H - 1)))
        for t0, g, drift in notes:
            age = (t - t0) % N
            if age < LIFE:  # rises and drifts toward the party, wavering
                x = sx + round((age * drift + 5 * np.sin(age / 2)) * K)
                y = sy - round(age * 3.2 * K)
                if 0 <= x < W - g.width and y >= 0:
                    c.alpha_composite(g, (x, y))
        out.append(c)
    return out, 90


PROPS = {"bufon": ("lute", bard)}  # work GIF with a prop


def build(cid):
    d = CUSTOM / cid
    sheet = key_black(rgba(d / "sheet.png"), **CHARS[cid].get("key", {}))  # e.g. {"peel": 0}
    fr, sheet_sc, raw = poses(sheet, CHARS[cid].get("rows", 2))
    for i, im in enumerate(fr):
        im.save(d / f"frame{i}.png")
    for name, (idx, ms) in ((k, v) for k, v in CHARS[cid].items() if k not in ("sleep_in_sheet", "sleep_pose", "sleep_erase", "sleep_squash", "smooth", "rows", "key", "fades")):
        pick = []
        for i in idx:
            if isinstance(i, str):  # "bobN": pose N lowered 2 px (bob)
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
    if "sleep_in_sheet" in CHARS[cid]:  # sleeping inside the sheet itself (bottom-right quadrant)
        h, w = sheet.shape[:2]
        crop = sheet[h // 2:, w * 3 // 4:].copy()
        x0, y0, x1, y1 = CHARS[cid]["sleep_in_sheet"]; crop[y0:y1, x0:x1, 3] = 0
        Image.fromarray(crop).save(d / "sleep-src.png")
        save_gif(d / "sleep.gif", sleeping(d / "sleep-src.png", fr[0].size, sheet_sc), 220)
    elif "sleep_pose" in CHARS[cid]:  # sleeping = a sheet pose as-is (no own z's)
        crop = raw[CHARS[cid]["sleep_pose"]].copy()
        if "sleep_erase" in CHARS[cid]:  # box (crop px) with the drawing's baked-in z's
            x0, y0, x1, y1 = CHARS[cid]["sleep_erase"]; crop[y0:y1, x0:x1, 3] = 0
        if "sleep_squash" in CHARS[cid]:  # (from, factor): squashes the bottom = legs tucked, lying down
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
