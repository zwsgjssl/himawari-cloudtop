#!/usr/bin/env python3
# ひまわりの観測から雲頂の高さ(FL)を日本付近の格子にして Cloudflare の KV に置く(公開リポジトリの GitHub Actions から 30 分ごと)。
# v165 公開リポジトリ用にこのファイルだけで動くようにした(公開リポジトリの Actions は時間の制限なし)。
#   このリポジトリには NOAA の公開データを切り出すこのプログラムと Actions の設定だけを置く(Map 本体・経路のデータは非公開リポジトリのまま)。
#   Cloudflare の鍵は GitHub の Secrets(CF_API_TOKEN・CF_ACCOUNT_ID・CF_KV_WX_ID)。公開リポジトリでも Secrets は見えない。
#
#
# データ: NOAA の公開データ noaa-himawari9(AWS、アカウント不要)の AHI-L2-FLDK-Clouds の AHI-CHGT(雲頂高度。NOAA Enterprise の ACHA。
#   ひまわり 9 号の全球 2km、10 分ごと。1 ファイル約 700MB)。その中の雲頂の気圧(CldTopPres、hPa)を FL(ISA の気圧高度)に直す。
#   気圧が無ければ雲頂の高さ(CldTopHght、m)を ft に直す(この場合は海面からの高さで、FL とは少しずれる)。
#   格子: ひまわりの全球 5500×5500(静止衛星の投影。衛星直下 140.7°E、CFAC/LFAC 20466275、COFF/LOFF 2750.5 = satpy の ahi_l2_nc と同じ)。
#   ファイル内の Latitude/Longitude と、こちらで計算した位置が合うかを数点で確かめてログに出す。
# 出力(KV): hima/<時刻 YYYYMMDDTHHMMZ> = uint8 [ny][nx](北緯 20〜50・東経 118〜152、0.05° おき、南から北・西から東)。
#   値 = FL ÷ 2(1〜250 = FL2〜500)、0 = 雲なし、255 = 欠け(衛星の外・データなし)。6 時間で消える。
#   hima:meta = { grid, times:[{ t, key }](新しい順に 4 つまで), src } を最後に書く
# 環境変数: CF_API_TOKEN・CF_ACCOUNT_ID・CF_KV_WX_ID(ukmo.yml と同じ)。試験用: HIMA_S3_BASE、--dry-run フォルダ、--file ローカルの nc
import argparse, datetime as dt, json, math, os, re, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import requests

UA = {"User-Agent": "approach-planner-wx/1.0 (personal, non-commercial)"}
def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

class KV:
    """Cloudflare の KV(WX)。--dry-run ならフォルダに書く"""
    def __init__(self, dry=None):
        self.dry = dry
        if dry: os.makedirs(dry, exist_ok=True); return
        acc, ns, tok = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_KV_WX_ID"), os.environ.get("CF_API_TOKEN")
        if not (acc and ns and tok): raise SystemExit("CF_ACCOUNT_ID / CF_KV_WX_ID / CF_API_TOKEN が未設定です(GitHub の Secrets に登録)")
        base = os.environ.get("CF_API_BASE", "https://api.cloudflare.com/client/v4").rstrip("/")
        self.url = f"{base}/accounts/{acc}/storage/kv/namespaces/{ns}/values/"
        self.h = {**UA, "Authorization": "Bearer " + tok}
    def _f(self, key): return os.path.join(self.dry, key.replace("/", "__"))
    def get(self, key):
        if self.dry: return open(self._f(key), "rb").read() if os.path.exists(self._f(key)) else None
        r = requests.get(self.url + requests.utils.quote(key, safe=""), headers=self.h, timeout=60)
        if r.status_code == 404: return None
        r.raise_for_status(); return r.content
    def put(self, key, data, ttl=None):
        if self.dry: open(self._f(key), "wb").write(data); return
        for attempt in range(4):
            r = requests.put(self.url + requests.utils.quote(key, safe=""), params={"expiration_ttl": ttl} if ttl else None,
                             headers={**self.h, "Content-Type": "application/octet-stream"}, data=data, timeout=300)
            if r.ok: return
            if attempt == 3: raise RuntimeError(f"KV に書けません({key}): HTTP {r.status_code} {r.text[:300]}")
            time.sleep(3 + attempt * 5)

S3 = os.environ.get("HIMA_S3_BASE", "https://noaa-himawari9.s3.amazonaws.com").rstrip("/")
PREFIX = "AHI-L2-FLDK-Clouds"
LAT0, LAT1, LON0, LON1, D = 20.0, 50.0, 118.0, 152.0, 0.05
TTL = 6 * 3600
KEEP = 4   # 30 分ごとの 4 つ(2 時間ぶん)
SUB_LON, CFAC, LFAC, COFF, LOFF = 140.7, 20466275, 20466275, 2750.5, 2750.5

def latest_files(hours=3):
    """新しい順に (時刻, キー)。v165 毎時 00 分と 30 分の観測"""
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    now = now.replace(minute=0 if now.minute < 30 else 30)
    out = []
    for i in range(hours * 2):
        t = now - dt.timedelta(minutes=30 * i)
        pre = f"{PREFIX}/{t:%Y/%m/%d/%H%M}/"
        r = requests.get(S3 + "/", params={"list-type": "2", "prefix": pre}, headers=UA, timeout=60); r.raise_for_status()
        ks = re.findall(r"<Key>([^<]*AHI-CHGT[^<]*\.nc)</Key>", r.text)
        if ks: out.append((t, sorted(ks)[-1]))
        if out: break   # 一番新しいものだけ要る
    return out

def download(key, path, parts=8):
    h = requests.head(f"{S3}/{key}", headers=UA, timeout=60)
    if h.status_code != 200: raise RuntimeError(f"ファイルがありません HTTP {h.status_code}: {key}")
    size = int(h.headers["Content-Length"]); step = -(-size // parts)
    with open(path, "wb") as f: f.truncate(size)
    def part(i):
        a, b = i * step, min(size, (i + 1) * step) - 1
        if a > b: return 0
        for attempt in range(4):
            try:
                r = requests.get(f"{S3}/{key}", headers={**UA, "Range": f"bytes={a}-{b}"}, timeout=300)
                data = r.content if r.status_code == 206 else r.content[a:b + 1]
                if len(data) != b - a + 1: raise RuntimeError("長さが合いません")
                with open(path, "r+b") as f: f.seek(a); f.write(data)
                return len(data)
            except Exception:
                if attempt == 3: raise
                time.sleep(2 + attempt * 3)
    with ThreadPoolExecutor(parts) as ex: return sum(ex.map(part, range(parts)))

def geos_linecol(lat, lon):
    """緯度経度 → ひまわり全球 2km の (行, 列)(0 から。北が 0)。CGMS LRIT/HRIT の正規化静止投影"""
    la, lo = np.deg2rad(lat), np.deg2rad(lon - SUB_LON)
    c_lat = np.arctan(0.993305616 * np.tan(la))
    rl = 6356.7523 / np.sqrt(1 - 0.00669438444 * np.cos(c_lat) ** 2)
    r1 = 42164.0 - rl * np.cos(c_lat) * np.cos(lo); r2 = -rl * np.cos(c_lat) * np.sin(lo); r3 = rl * np.sin(c_lat)
    rn = np.sqrt(r1 ** 2 + r2 ** 2 + r3 ** 2)
    x = np.rad2deg(np.arctan(-r2 / r1)); y = np.rad2deg(np.arcsin(-r3 / rn))
    col = COFF + x * 2.0 ** -16 * CFAC; line = LOFF + y * 2.0 ** -16 * LFAC
    return line - 1, col - 1   # 1 から → 0 から

def read_var(h5, name, r0, r1, c0, c1):
    v = h5[name]; a = v[r0:r1, c0:c1].astype("f8")
    fill = v.attrs.get("_FillValue"); sf = v.attrs.get("scale_factor"); ao = v.attrs.get("add_offset")
    if fill is not None: a = np.where(a == np.asarray(fill).ravel()[0], np.nan, a)
    if sf is not None: a = a * float(np.asarray(sf).ravel()[0])
    if ao is not None: a = a + float(np.asarray(ao).ravel()[0])
    vr = v.attrs.get("valid_range")
    if vr is not None and sf is None:
        vr = np.asarray(vr).ravel(); a = np.where((a < vr[0]) | (a > vr[1]), np.nan, a)
    return a, (v.attrs.get("units", b"") or b"")

def pick(names, *pats):
    for p in pats:
        for n in names:
            if re.search(p, n, re.I): return n
    return None

def build(path):
    import h5py
    with h5py.File(path, "r") as h5:
        names = [k for k in h5.keys()]
        log("変数: " + ", ".join(f"{k}{tuple(h5[k].shape)}" for k in names if hasattr(h5[k], "shape"))[:1500])
        vp = pick(names, r"^CldTopPres$", r"TopPres"); vh = pick(names, r"^CldTopHght$", r"TopH(e)?(i)?ght")
        if not vp and not vh: raise RuntimeError("雲頂の気圧・高さの変数が見つかりません")
        shape = h5[vp or vh].shape
        if tuple(shape) != (5500, 5500): raise RuntimeError(f"格子が 5500×5500 ではありません: {shape}")
        lats = LAT0 + D * np.arange(int(round((LAT1 - LAT0) / D)) + 1); lons = LON0 + D * np.arange(int(round((LON1 - LON0) / D)) + 1)
        LO, LA = np.meshgrid(lons, lats)
        ln, cl = geos_linecol(LA, LO)
        ok = np.isfinite(ln) & np.isfinite(cl)
        li, ci = np.rint(ln).astype(int), np.rint(cl).astype(int)
        r0, r1 = int(li[ok].min()), int(li[ok].max()) + 1; c0, c1 = int(ci[ok].min()), int(ci[ok].max()) + 1
        r0, c0 = max(0, r0), max(0, c0); r1, c1 = min(5500, r1), min(5500, c1)
        log(f"日本付近 = 行 {r0}〜{r1}・列 {c0}〜{c1}")
        # 位置の確かめ: ファイルの Latitude/Longitude と比べる
        vlat, vlon = pick(names, r"^Latitude$", r"^lat"), pick(names, r"^Longitude$", r"^lon")
        if vlat and vlon and h5[vlat].shape == shape:
            errs = []
            for la, lo in [(20.5, 118.5), (49.5, 151.5), (35.55, 139.78), (33.59, 130.45), (43.0, 141.4)]:
                a, b = geos_linecol(np.array(la), np.array(lo)); a, b = int(round(float(a))), int(round(float(b)))
                fla, flo = float(read_var(h5, vlat, a, a + 1, b, b + 1)[0][0, 0]), float(read_var(h5, vlon, a, a + 1, b, b + 1)[0][0, 0])
                errs.append(max(abs(fla - la), abs(flo - lo)))
            log("位置の確かめ(ファイルの緯度経度との差、度): " + " ".join(f"{e:.3f}" for e in errs))
            if max(errs) > 0.1: raise RuntimeError("位置が合いません(投影の想定違い)。ログの変数一覧を見て直す")
        else: log("Latitude/Longitude が無いので位置の確かめは省略")
        if vp:
            P, u = read_var(h5, vp, r0, r1, c0, c1)
            if np.nanmax(P) > 2000: P = P / 100.0   # Pa → hPa
            FL = 145366.45 * (1 - (np.clip(P, 50, 1100) / 1013.25) ** 0.190284) / 100; src = f"{vp}(気圧 → FL)"
        else:
            Hm, u = read_var(h5, vh, r0, r1, c0, c1)
            if np.nanmax(Hm) < 100: Hm = Hm * 1000.0   # km → m
            FL = Hm * 3.28084 / 100; src = f"{vh}(高さ → ft。FL とは少しずれる)"
        # 雲なし: 雲頂の値が無い(NaN)所。衛星の外は 255
        sub = FL[np.clip(li - r0, 0, r1 - r0 - 1), np.clip(ci - c0, 0, c1 - c0 - 1)]
        out = np.where(~ok, 255, np.where(np.isfinite(sub), np.clip(np.rint(sub / 2), 1, 250), 0)).astype("u1")
        cov = float(np.mean((out > 0) & (out < 255)))
        q = sub[np.isfinite(sub)]
        log(f"雲頂 {src}: 雲のある割合 {cov*100:.0f}%" + (f"、FL 50/90/99% {np.percentile(q, 50):.0f}/{np.percentile(q, 90):.0f}/{np.percentile(q, 99):.0f}" if q.size else ""))
        if q.size and not (0 < np.percentile(q, 50) < 500): raise RuntimeError("雲頂の値がおかしい")
        return out, {"lat0": LAT0, "dlat": D, "ny": len(lats), "lon0": LON0, "dlon": D, "nx": len(lons)}, src

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", default="", help="KV に書かず、このフォルダに出す(試験用)")
    ap.add_argument("--file", default="", help="ローカルの AHI-CHGT の nc を使う(試験用)")
    ap.add_argument("--time", default="", help="--file の観測時刻 YYYYMMDDTHHMMZ")
    a = ap.parse_args()
    kv = KV(a.dry_run or None)
    old = kv.get("hima:meta"); old = json.loads(old) if old else None
    have = {x["t"] for x in (old or {}).get("times", [])}
    t0 = time.time()
    if a.file:
        tt = dt.datetime.strptime(a.time, "%Y%m%dT%H%MZ"); arr, grid, src = build(a.file)
    else:
        fs = latest_files()
        if not fs: log("ひまわりの雲頂のファイルが見つかりません"); return
        tt, key = fs[0]
        if f"{tt:%Y-%m-%dT%H:%MZ}" in have: log(f"{tt:%H:%MZ} はもうあります。何もしません"); return
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "chgt.nc"); n = download(key, p)
            log(f"取得 {key.split('/')[-1]} {n/1e6:.0f}MB {time.time()-t0:.0f}秒")
            arr, grid, src = build(p)
    t = f"{tt:%Y-%m-%dT%H:%MZ}"; k = f"hima/{tt:%Y%m%dT%H%MZ}"
    kv.put(k, arr.tobytes(), TTL)
    times = [{"t": t, "key": k}] + [x for x in (old or {}).get("times", []) if x["t"] != t]
    times = sorted(times, key=lambda x: x["t"], reverse=True)[:KEEP]
    kv.put("hima:meta", json.dumps({"grid": grid, "times": times, "src": src, "enc": "uint8 FL/2、0 = 雲なし、255 = 欠け",
                                    "attribution": "Himawari-9 / NOAA Enterprise Cloud Height (AHI-CHGT, NOAA Open Data Dissemination)"}, ensure_ascii=False).encode("utf-8"))
    log(f"できました: {t}、{len(arr.tobytes())/1e3:.0f}KB、{time.time()-t0:.0f}秒")

if __name__ == "__main__":
    main()
