#!/usr/bin/env python3
# v211 ユーザー「FXJP の①の色塗りとか相当温位の部分から結構ズレてる。もう少し正確な色塗りをできない?」
#   定時の解析(Claude)が図に印(marks)を付けるときの道具。ずれの一番の原因は、大きな図(例 FXJP106 2048×2545)を Read で見ると
#   縮小されて表示され、縮小した絵の上で座標を読むこと。この道具は 元の画素のまま(1:1)の切り抜きに、元の図の座標の目盛りを描く。
#
# 使い方(図は /tmp/nwp/<id>.png、印は ai.json の marks と同じ形の JSON):
#   python3 tools/nwp_mark.py grid  <図.png> <x0> <y0> [幅 高さ] [-o 出力.png]
#       元の画素のまま 幅×高さ(既定 700×700、最大 900)を切り抜き、50px ごとの細い線・100px ごとの太い線と、元の図の x・y の数字を描く。
#       → これを Read で見て、線・記号の本当の座標を読む(縮小されないので 1 画素の精度で読める)。
#   python3 tools/nwp_mark.py overview <図.png> [-o 出力.png]
#       図全体を縮小し、200px ごとの目盛り(元の図の座標)を描く。どこを grid で切り抜くか決める用。
#   python3 tools/nwp_mark.py check <図.png> <marks.json> [-o 出力の頭]
#       印を Map と同じように(半透明の色・縁取り・番号)描く。全体(縮小)と、印ごとに 元の画素のままの拡大(余白 60px・目盛りつき)を出す。
#       → 1 つずつ Read で見て、印が線・帯・記号の本当の位置に重なっているか確かめる。
#   python3 tools/nwp_mark.py band <半幅px> x1,y1 x2,y2 …
#       曲がった帯(相当温位の集中帯・シアーの帯など)の真ん中の線の点と半幅から、帯を囲む poly の pts(JSON)を出す。
#       線の束の真ん中を 10〜20 点でなぞり、半幅は束の太さの半分(多くは 10〜20px)。折れ曲がり・北東への続きも点を足してなぞる。
#   python3 tools/nwp_mark.py snap <図.png> x1,y1 x2,y2 … [-o 確認.png]
#       v217 ユーザーが FXJP854 に手で塗った見本(線の束そのものだけを細くなぞる)に合わせる道具。集中帯・シアーの帯は band ではなくこれを使う。
#       束の真ん中あたりを 20〜40px おきの点でおおまかになぞる(±25px ずれていてよい)と、各点で直角方向に図の黒い線を数え、
#       間隔 5px 以内で並ぶ 3 本以上の線のかたまり(= 束)の外側の線にぴったり沿う poly の pts(JSON)を出す。
#       S 字・折り返しは、曲がりに沿って点を細かく(10〜20px おき)置く。隣の枝に飛ばないよう、折り返しの内側を通らない。
#       -o を付けると、図に重ねた 3 倍の確認画像を出す。必ず Read で見て、束からはみ出し・束の取りこぼしが無いか確かめる。
import argparse, json, math, os, sys
from PIL import Image, ImageDraw, ImageFont

COL = {"front": (220, 60, 60), "jet": (230, 150, 0), "cat": (200, 0, 120), "trough": (120, 70, 20), "cold": (40, 110, 230),
       "warm": (230, 90, 30), "moist": (20, 160, 90), "cb": (150, 0, 200), "low": (200, 0, 0), "high": (0, 90, 200), "other": (90, 90, 90)}

def font(sz):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(p): return ImageFont.truetype(p, sz)
    return ImageFont.load_default()

def ticks(d, x0, y0, w, h, step, big, F):
    """切り抜きの上に元の図の座標の目盛り(x0, y0 = 切り抜きの左上の元の座標)"""
    for X in range((x0 // step + 1) * step if x0 % step else x0, x0 + w, step):
        b = X % big == 0; d.line([(X - x0, 0), (X - x0, h)], fill=(0, 140, 255, 200 if b else 110), width=2 if b else 1)
        if b: d.text((X - x0 + 2, 2), str(X), fill=(0, 90, 220, 255), font=F); d.text((X - x0 + 2, h - 18), str(X), fill=(0, 90, 220, 255), font=F)
    for Y in range((y0 // step + 1) * step if y0 % step else y0, y0 + h, step):
        b = Y % big == 0; d.line([(0, Y - y0), (w, Y - y0)], fill=(0, 140, 255, 200 if b else 110), width=2 if b else 1)
        if b: d.text((2, Y - y0 + 2), str(Y), fill=(0, 90, 220, 255), font=F); d.text((w - 46, Y - y0 + 2), str(Y), fill=(0, 90, 220, 255), font=F)

def grid(img, x0, y0, w, h, out):
    im = Image.open(img).convert("RGB"); W, H = im.size
    w, h = min(w, 900), min(h, 900); x0 = max(0, min(x0, W - w)); y0 = max(0, min(y0, H - h))
    c = im.crop((x0, y0, x0 + w, y0 + h)).convert("RGBA"); ov = Image.new("RGBA", c.size, (0, 0, 0, 0))
    ticks(ImageDraw.Draw(ov), x0, y0, c.width, c.height, 50, 100, font(13))
    Image.alpha_composite(c, ov).convert("RGB").save(out); print(f"{out}: 元の図の x {x0}〜{x0 + c.width}, y {y0}〜{y0 + c.height}(1:1)")

def overview(img, out):
    im = Image.open(img).convert("RGBA"); W, H = im.size; ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ticks(ImageDraw.Draw(ov), 0, 0, W, H, 200, 200, font(max(14, W // 60)))
    s = min(1.0, 1100 / max(W, H)); r = Image.alpha_composite(im, ov).convert("RGB")
    r.resize((int(W * s), int(H * s)), Image.LANCZOS).save(out); print(f"{out}: 全体 {W}×{H} を {s:.2f} 倍(目盛りの数字は元の図の座標)")

def draw_marks(im, marks, F):
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    for m in marks:
        c = COL.get(m.get("kind"), COL["other"]); fill = c + (70,); edge = c + (255,); sh = m.get("shape")
        if sh == "ellipse":
            cx, cy, rx, ry, rot = m["cx"], m["cy"], m["rx"], m["ry"], math.radians(m.get("rot") or 0)
            pts = [(cx + rx * math.cos(t) * math.cos(rot) - ry * math.sin(t) * math.sin(rot), cy + rx * math.cos(t) * math.sin(rot) + ry * math.sin(t) * math.cos(rot))
                   for t in [i * 2 * math.pi / 72 for i in range(72)]]
            d.polygon(pts, fill=fill, outline=edge, width=3); lx, ly = cx, cy
        elif sh == "poly":
            pts = [tuple(p) for p in m["pts"]]; d.polygon(pts, fill=fill, outline=edge, width=3)
            lx, ly = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        else:
            pts = [tuple(p) for p in m["pts"]]; d.line(pts, fill=c + (170,), width=10, joint="curve"); lx, ly = pts[0]
        d.ellipse([lx - 13, ly - 13, lx + 13, ly + 13], fill=(255, 255, 255, 230), outline=edge, width=2)
        d.text((lx - 6, ly - 9), str(m.get("n", "")), fill=edge, font=F)
    return Image.alpha_composite(im, ov)

def band(w, pts):
    L, R = [], []
    for i, (x, y) in enumerate(pts):
        a, b = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]; dx, dy = b[0] - a[0], b[1] - a[1]; n = math.hypot(dx, dy) or 1
        nx, ny = -dy / n, dx / n; L.append([round(x + nx * w), round(y + ny * w)]); R.append([round(x - nx * w), round(y - ny * w)])
    return L + R[::-1]

def _bil(g, xs, ys):
    import numpy as np
    H, W = g.shape; xs = np.clip(xs, 0, W - 1.001); ys = np.clip(ys, 0, H - 1.001); x0 = xs.astype(int); y0 = ys.astype(int); fx = xs - x0; fy = ys - y0
    return (g[y0, x0] * (1 - fx) * (1 - fy) + g[y0, x0 + 1] * fx * (1 - fy) + g[y0 + 1, x0] * (1 - fx) * fy + g[y0 + 1, x0 + 1] * fx * fy)

def _smooth(v, s):
    import numpy as np
    k = np.exp(-0.5 * (np.arange(-3 * s, 3 * s + 1) / s) ** 2); k /= k.sum(); p = np.pad(v, (len(k) // 2,), mode="edge"); return np.convolve(p, k, mode="valid")

def _rdp(pts, eps):
    import numpy as np
    if len(pts) < 3: return pts
    a, b = pts[0], pts[-1]; d = b - a; n = np.hypot(*d) or 1
    dist = np.abs(d[0] * (pts[:, 1] - a[1]) - d[1] * (pts[:, 0] - a[0])) / n; i = int(dist.argmax())
    if dist[i] > eps: return np.vstack([_rdp(pts[:i + 1], eps)[:-1], _rdp(pts[i:], eps)])
    return np.array([a, b])

def snap(img, pts, R=32, gap=5, thr=90, pad=3, minlines=3):
    """v217 おおまかな真ん中の線 → 線の束(間隔 gap px 以内で並ぶ minlines 本以上の黒い線)の外側に沿う poly。
       ユーザーの手塗りの見本(FXJP854 15日00Z の T12・T36)で調整: thr 90・gap 5・pad 3"""
    import numpy as np
    g = np.asarray(Image.open(img).convert("L")).astype(float)
    P = []
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 3))
        P += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n)]
    P = np.array(P + [tuple(pts[-1])], float); P[:, 0] = _smooth(P[:, 0], 2); P[:, 1] = _smooth(P[:, 1], 2)
    T = np.gradient(P, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-9; N = np.stack([-T[:, 1], T[:, 0]], 1)
    ts = np.arange(-R, R + 0.01, 0.5); lo = np.full(len(P), np.nan); hi = np.full(len(P), np.nan)
    for i, (p, n) in enumerate(zip(P, N)):
        d = _bil(g, p[0] + ts * n[0], p[1] + ts * n[1]) < thr; rr = []; j = 0
        while j < len(d):
            if d[j]:
                k = j
                while k < len(d) and d[k]: k += 1
                rr.append((ts[j], ts[k - 1])); j = k
            else: j += 1
        if not rr: continue
        cl = [[rr[0]]]
        for r in rr[1:]: cl[-1].append(r) if r[0] - cl[-1][-1][1] <= gap else cl.append([r])
        b = max(cl, key=lambda c: len(c) - abs((c[0][0] + c[-1][1]) / 2) / 8)
        if len(b) >= minlines: lo[i] = b[0][0] - pad; hi[i] = b[-1][1] + pad
    ok = ~np.isnan(lo); idx = np.arange(len(P))
    if ok.sum() < 2: sys.exit("束が見つからない: 点が線の束から離れすぎていないか確かめる")
    lo = np.interp(idx, idx[ok], lo[ok]); hi = np.interp(idx, idx[ok], hi[ok])
    med = lambda v: np.array([np.median(v[max(0, i - 4):i + 5]) for i in range(len(v))])
    lo = _smooth(med(lo), 4); hi = _smooth(med(hi), 4)
    poly = np.vstack([_rdp(P + N * lo[:, None], 1.2), _rdp((P + N * hi[:, None])[::-1], 1.2)])
    out = [[int(round(x)), int(round(y))] for x, y in poly]
    print(f"束を見つけた点の割合 {ok.mean():.0%}(低いときは点を束の真ん中へ寄せる)", file=sys.stderr)
    return out

def snap_preview(img, poly, out):
    im = Image.open(img).convert("RGBA"); r = draw_marks(im, [{"n": "", "kind": "front", "shape": "poly", "pts": poly}], font(18))
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]; x0, y0 = max(0, min(xs) - 40), max(0, min(ys) - 40); x1, y1 = min(im.width, max(xs) + 40), min(im.height, max(ys) + 40)
    c = r.crop((x0, y0, x1, y1)); ov = Image.new("RGBA", c.size, (0, 0, 0, 0)); ticks(ImageDraw.Draw(ov), x0, y0, c.width, c.height, 50, 100, font(13))
    c = Image.alpha_composite(c, ov); z = min(3.0, 1400 / max(c.size)); c.resize((int(c.width * z), int(c.height * z)), Image.LANCZOS).convert("RGB").save(out)
    print(f"{out}: 確認画像({z:.1f} 倍)", file=sys.stderr)

def bbox(m):
    if m.get("shape") == "ellipse":
        r = max(m["rx"], m["ry"]); return m["cx"] - r, m["cy"] - r, m["cx"] + r, m["cy"] + r
    xs = [p[0] for p in m["pts"]]; ys = [p[1] for p in m["pts"]]; return min(xs), min(ys), max(xs), max(ys)

def check(img, mfile, head):
    im = Image.open(img).convert("RGBA"); W, H = im.size
    marks = json.load(open(mfile, encoding="utf-8")); marks = marks.get("marks", marks) if isinstance(marks, dict) else marks
    r = draw_marks(im, marks, font(18)); s = min(1.0, 1100 / max(W, H))
    r.convert("RGB").resize((int(W * s), int(H * s)), Image.LANCZOS).save(head + "_all.png"); print(f"{head}_all.png: 全体(縮小 {s:.2f})")
    for m in marks:
        x0, y0, x1, y1 = bbox(m); x0, y0 = int(max(0, x0 - 60)), int(max(0, y0 - 60)); x1, y1 = int(min(W, x1 + 60)), int(min(H, y1 + 60))
        c = r.crop((x0, y0, x1, y1)); ov = Image.new("RGBA", c.size, (0, 0, 0, 0)); ticks(ImageDraw.Draw(ov), x0, y0, c.width, c.height, 50, 100, font(13))
        c = Image.alpha_composite(c, ov)
        z = 900 / max(c.size)   # v212 小さい印は 2〜3 倍に拡大(曲がり角で束がはみ出していないか見えるように)。大きい印は 900px に縮める
        z = min(3.0, z) if z > 1 else z
        if abs(z - 1) > 0.05: c = c.resize((int(c.width * z), int(c.height * z)), Image.LANCZOS)
        f = f"{head}_{m.get('n', 0)}.png"; c.convert("RGB").save(f); print(f"{f}: 印 {m.get('n')}({m.get('label', '')})x {x0}〜{x1}, y {y0}〜{y1}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    g = sp.add_parser("grid"); g.add_argument("img"); g.add_argument("x0", type=int); g.add_argument("y0", type=int)
    g.add_argument("w", type=int, nargs="?", default=700); g.add_argument("h", type=int, nargs="?", default=700); g.add_argument("-o", default="")
    o = sp.add_parser("overview"); o.add_argument("img"); o.add_argument("-o", default="")
    c = sp.add_parser("check"); c.add_argument("img"); c.add_argument("marks"); c.add_argument("-o", default="")
    sn = sp.add_parser("snap"); sn.add_argument("img"); sn.add_argument("pts", nargs="+"); sn.add_argument("-o", default="")
    b = sp.add_parser("band"); b.add_argument("w", type=float); b.add_argument("pts", nargs="+")
    a = ap.parse_args()
    if a.cmd == "band": print(json.dumps(band(a.w, [tuple(float(v) for v in p.split(",")) for p in a.pts]))); sys.exit()
    if a.cmd == "snap":
        poly = snap(a.img, [tuple(float(v) for v in p.split(",")) for p in a.pts]); print(json.dumps(poly))
        if a.o: snap_preview(a.img, poly, a.o)
        sys.exit()
    base = os.path.splitext(a.img)[0]
    if a.cmd == "grid": grid(a.img, a.x0, a.y0, a.w, a.h, a.o or f"{base}_g{a.x0}_{a.y0}.png")
    elif a.cmd == "overview": overview(a.img, a.o or f"{base}_ov.png")
    else: check(a.img, a.marks, a.o or f"{base}_chk")
