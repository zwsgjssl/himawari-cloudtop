#!/usr/bin/env python3
# v1 定時の Claude の解析が「CAT の出やすい雲のパターン・水蒸気の暗域・山岳波」を見るための、ひまわりの赤外(B13)と水蒸気(B08)の画像。
#   ユーザー「(気象庁の衛星画像の解析の本の第 3 章)全部進めて」2026-10-19。
#   ブランチ nwp-obs の sat/ に、毎時(正時の観測)の 2 枚を PNG で置く(新しい 6 時間分だけ)。KV には置かない(Map の WX保存の大きさは変わらない)。
#   データ: NOAA の公開データ noaa-himawari9 の AHI-L1b-FLDK(HSD、R20 = 2km)。tools/himawari_build.py の取得・投影をそのまま使う。
#   図: 北緯 20〜50°・東経 118〜152° を 0.04° おきの正距円筒(緯度経度がそのまま縦横。左上 = 50N 118E)。5° ごとの経緯線と海岸線(Natural Earth 1:50m)。
#     赤外: 冷たい(高い雲)ほど白。300K = 黒 → 200K = 白。
#     水蒸気: 上・中層が湿っているほど白、乾いている(暗域・下降流)ほど黒。255K = 黒 → 215K = 白。
# 使い方: python3 tools/sat_build.py --dir nwp_obs/sat [--keep 6] [--file-b13 … --file-b08 … --time YYYYMMDDTHHMMZ(試験用)]
import argparse, datetime as dt, json, os, re, sys, tempfile, time
import numpy as np
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import himawari_build as hb

LAT0, LAT1, LON0, LON1, D = 20.0, 50.0, 118.0, 152.0, 0.04
BANDS = {"B13": ("ir", 300.0, 200.0, "IR B13 10.4um (cold = white)"),
         "B08": ("wv", 255.0, 215.0, "WV B08 6.2um (moist = white, dry = dark)")}
log = hb.log

def grid():
    lats = LAT1 - D * np.arange(int(round((LAT1 - LAT0) / D)) + 1)   # 北から南(画像の上から下)
    lons = LON0 + D * np.arange(int(round((LON1 - LON0) / D)) + 1)
    return lats, lons

def latest(hours=3):
    """正時の観測で、B13・B08 の日本付近の帯がそろった一番新しい物 (時刻, {band:[キー]})"""
    segs = hb.ir_segments()
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    for i in range(hours + 1):
        t = now - dt.timedelta(hours=i); pre = f"{hb.L1B}/{t:%Y/%m/%d/%H%M}/"
        r = requests.get(hb.S3 + "/", params={"list-type": "2", "prefix": pre}, headers=hb.UA, timeout=60); r.raise_for_status()
        out = {}
        for b in BANDS:
            have = {int(sg): k for k, sg in re.findall(rf"<Key>([^<]*_{b}_FLDK_R20_S(\d\d)10\.DAT(?:\.bz2)?)</Key>", r.text)}
            if all(sg in have for sg in segs): out[b] = [have[sg] for sg in segs]
        if len(out) == len(BANDS): return t, out
    return None

def unbz(p):
    if not p.endswith(".bz2"): return p
    import bz2
    q = p[:-4]
    with bz2.open(p, "rb") as f, open(q, "wb") as g:
        while True:
            b = f.read(1 << 22)
            if not b: break
            g.write(b)
    os.remove(p); return q

def read_band(band, paths):
    """HSD の帯 → この図の格子の温度 K(欠けは nan)"""
    import warnings
    from satpy import Scene
    files = [unbz(p) for p in paths]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        scn = Scene(reader="ahi_hsd", filenames=files); scn.load([band])
        d = scn[band]; area = d.attrs["area"]
        lats, lons = grid(); LO, LA = np.meshgrid(lons, lats)
        col, row = area.get_array_indices_from_lonlat(LO, LA)
        ok = ~np.ma.getmaskarray(col) & ~np.ma.getmaskarray(row)
        col = np.ma.filled(col, 0).astype(int); row = np.ma.filled(row, 0).astype(int)
        r0, r1, c0, c1 = int(row[ok].min()), int(row[ok].max()) + 1, int(col[ok].min()), int(col[ok].max()) + 1
        sub = np.asarray(d[r0:r1, c0:c1].values, dtype="f4")
    K = sub[np.clip(row - r0, 0, r1 - r0 - 1), np.clip(col - c0, 0, c1 - c0 - 1)]
    K = np.where(ok, K, np.nan)
    q = K[np.isfinite(K)]
    if q.size < 0.5 * K.size: raise RuntimeError(f"{band} の値が足りません({q.size}/{K.size})")
    p = np.percentile(q, [1, 50, 99]); log(f"{band} の温度 K 1/50/99%: {p[0]:.0f}/{p[1]:.0f}/{p[2]:.0f}")
    if not (180 < p[1] < 320): raise RuntimeError(f"{band} の温度がおかしい")
    return K

def render(K, band, t, path):
    """温度 → 灰色の画像 + 経緯線・海岸線・題名"""
    from PIL import Image, ImageDraw
    name, warm, cold, title = BANDS[band]
    g = np.clip((warm - K) / (warm - cold), 0, 1)
    if band == "B08": g = g ** 0.8   # 暗域と明域の境目(バウンダリー)が見やすいように少し明るく
    a = np.where(np.isfinite(K), np.rint(g * 255), 0).astype("u1")
    im = Image.fromarray(a, "L").convert("RGB"); dr = ImageDraw.Draw(im)
    H, W = a.shape
    def xy(lon, lat): return ((lon - LON0) / D, (LAT1 - lat) / D)
    for lat in range(25, 50, 5):
        y = xy(LON0, lat)[1]; dr.line([(0, y), (W, y)], fill=(90, 90, 160), width=1); dr.text((3, y + 2), f"{lat}N", fill=(255, 220, 0))
    for lon in range(120, 152, 5):
        x = xy(lon, LAT1)[0]; dr.line([(x, 0), (x, H)], fill=(90, 90, 160), width=1); dr.text((x + 3, H - 14), f"{lon}E", fill=(255, 220, 0))
    try:
        C = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "coast_sat.json")))
        for r in C["rings"]: dr.line([xy(lo, la) for lo, la in r], fill=(255, 210, 0), width=1)
    except Exception as e: log(f"海岸線が描けません: {e}")
    dr.rectangle([0, 0, 400, 16], fill=(0, 0, 0)); dr.text((4, 3), f"Himawari-9 {title}  {t:%Y-%m-%d %H:%MZ}", fill=(255, 255, 255))
    im = im.quantize(colors=200, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    im.save(path, optimize=True)
    log(f"{os.path.basename(path)} {im.size} {os.path.getsize(path)/1e3:.0f}KB")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True); ap.add_argument("--keep", type=int, default=6)
    ap.add_argument("--file-b13", nargs="*"); ap.add_argument("--file-b08", nargs="*"); ap.add_argument("--time")
    a = ap.parse_args(); os.makedirs(a.dir, exist_ok=True); t0 = time.time()
    if a.file_b13 and a.file_b08:
        tt = dt.datetime.strptime(a.time, "%Y%m%dT%H%MZ"); files = {"B13": a.file_b13, "B08": a.file_b08}; tmp = None
    else:
        f = latest()
        if not f: log("正時の B13・B08 の帯がそろった観測が直近 3 時間にありません"); return
        tt, keys = f
        if all(os.path.exists(os.path.join(a.dir, f"{BANDS[b][0]}_{tt:%Y%m%dT%H%MZ}.png")) for b in BANDS):
            log(f"衛星画像 {tt:%H:%MZ} はもうあります"); return
        tmp = tempfile.mkdtemp(); files = {}
        for b, ks in keys.items():
            files[b] = []
            for k in ks:
                p = os.path.join(tmp, k.split("/")[-1]); hb.download(k, p, parts=4); files[b].append(p)
        log(f"取得 {sum(map(len, files.values()))} 個 {time.time()-t0:.0f}秒")
    try:
        for b, ps in files.items():
            render(read_band(b, ps), b, tt, os.path.join(a.dir, f"{BANDS[b][0]}_{tt:%Y%m%dT%H%MZ}.png"))
    finally:
        if tmp: import shutil; shutil.rmtree(tmp, ignore_errors=True)
    for pre in ("ir_", "wv_"):
        old = sorted(x for x in os.listdir(a.dir) if x.startswith(pre))
        for x in old[:-a.keep]: os.remove(os.path.join(a.dir, x))
    log(f"衛星画像 できました {tt:%Y-%m-%dT%H:%MZ}、{time.time()-t0:.0f}秒")

if __name__ == "__main__":
    main()
