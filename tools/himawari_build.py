#!/usr/bin/env python3
# ひまわりの観測から雲頂の高さ(FL)・雲の種類・赤外の温度(v171)を日本付近の格子にして Cloudflare の KV に置く(公開リポジトリの GitHub Actions。v169 10 分ごと、Cloudflare の Worker から起動)。
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
#   v169 その後ろに同じ形でもう 1 枚、雲の種類(AHI-CPHS の CloudType を CT_CLASSES の番号に。0 = 雲なし、255 = 欠け)。取れなければ付けない。
#   hima:meta = { grid, layers:["fl"(, "type")], types:CT_CLASSES, times:[{ t, key }](新しい順に KEEP 個まで), src } を最後に書く
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
KEEP = 6   # v169 10 分ごとの 6 つ(1 時間ぶん)
SUB_LON, CFAC, LFAC, COFF, LOFF = 140.7, 20466275, 20466275, 2750.5, 2750.5

def latest_files(hours=6):
    """一番新しい観測の (時刻, 雲頂のキー, 雲の種類のキー or None)。v169 10 分ごと。
    雲頂(CHGT)と種類(CPHS)が両方そろった一番新しい回。種類だけまだの回しか無ければ、雲頂だけの一番新しい回"""
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    now = now.replace(minute=now.minute // 10 * 10)
    only_h, ih = None, 0
    for i in range(hours * 6):
        t = now - dt.timedelta(minutes=10 * i)
        pre = f"{PREFIX}/{t:%Y/%m/%d/%H%M}/"
        r = requests.get(S3 + "/", params={"list-type": "2", "prefix": pre}, headers=UA, timeout=60); r.raise_for_status()
        kh = sorted(re.findall(r"<Key>([^<]*AHI-CHGT[^<]*\.nc)</Key>", r.text)); kt = sorted(re.findall(r"<Key>([^<]*AHI-CPHS[^<]*\.nc)</Key>", r.text))
        # 雲頂だけの回より 20 分以内に古い回で両方そろっていれば、そちら(種類も見たいので)
        if kh and kt: return (t, kh[-1], kt[-1]) if not only_h or i - ih <= 2 else only_h
        if kh and not only_h: only_h, ih = (t, kh[-1], None), i
    return only_h

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
        return out, {"lat0": LAT0, "dlat": D, "ny": len(lats), "lon0": LON0, "dlon": D, "nx": len(lons)}, src, (li, ci, ok)

# v169 雲の種類。番号 = Map の CT_TBL と同じ並び(1 から)
CT_CLASSES = ["fog", "water", "supercooled", "mixed", "opaque_ice", "cirrus", "overlap", "overshoot", "other"]
# ファイルに flag_meanings が無いときの想定(NOAA Enterprise の雲の種類。未確認なのでログに値の数を出す)
CT_DEFAULT = ["clear", "probably_clear", "fog", "water", "supercooled_water", "mixed", "opaque_ice", "cirrus", "overlapping", "overshooting", "unknown", "dust", "smoke", "fire"]
def ct_class(name):
    n = name.lower()
    if "clear" in n: return 0
    for key, c in (("fog", 1), ("supercool", 3), ("water", 2), ("mixed", 4), ("opaque", 5), ("thick", 5), ("tice", 5), ("cirrus", 6), ("overlap", 7), ("multi", 7), ("overshoot", 8)):
        if key in n: return c
    return 9

def build_type(path, li, ci, ok):
    import h5py
    with h5py.File(path, "r") as h5:
        names = [k for k in h5.keys()]
        log("種類の変数: " + ", ".join(f"{k}{tuple(h5[k].shape)}" for k in names if hasattr(h5[k], "shape"))[:1200])
        vn = pick(names, r"^CloudType$", r"Cl(ou)?dType", r"Type")
        if not vn: raise RuntimeError("雲の種類の変数が見つかりません")
        v = h5[vn]
        if tuple(v.shape) != (5500, 5500): raise RuntimeError(f"雲の種類の格子が 5500×5500 ではありません: {v.shape}")
        fv = v.attrs.get("flag_values"); fm = v.attrs.get("flag_meanings"); fill = v.attrs.get("_FillValue")
        if isinstance(fm, bytes): fm = fm.decode()
        if fv is not None and fm:
            vals = [int(x) for x in np.asarray(fv).ravel()]; mean = str(fm).split()
        else:
            vals = list(range(len(CT_DEFAULT))); mean = CT_DEFAULT
        lut = np.full(256, 9, "u1")
        for a, m in zip(vals, mean):
            if 0 <= a < 256: lut[a] = ct_class(m)
        log("種類の対応: " + ", ".join(f"{a}={m}→{ct_class(m)}" for a, m in zip(vals, mean)) + (" (flag_meanings が無いので想定)" if fm is None else ""))
        r0, r1 = int(li[ok].min()), int(li[ok].max()) + 1; c0, c1 = int(ci[ok].min()), int(ci[ok].max()) + 1
        r0, c0 = max(0, r0), max(0, c0); r1, c1 = min(5500, r1), min(5500, c1)
        raw = v[r0:r1, c0:c1].astype("i8")
        sub = raw[np.clip(li - r0, 0, r1 - r0 - 1), np.clip(ci - c0, 0, c1 - c0 - 1)]
        bad = (sub < 0) | (sub > 255)
        if fill is not None: bad |= sub == int(np.asarray(fill).ravel()[0])
        out = np.where(~ok | bad, 255, lut[np.clip(sub, 0, 255)]).astype("u1")
        u, n = np.unique(sub[ok], return_counts=True)
        log("種類の値の数(元): " + " ".join(f"{a}:{b}" for a, b in zip(u.tolist(), n.tolist()))[:600])
        u, n = np.unique(out, return_counts=True)
        log("種類の値の数(まとめた後): " + " ".join(f"{a}:{b}" for a, b in zip(u.tolist(), n.tolist())))
        return out

# v171 ユーザー「(衛星の赤外を)jma から noaa に変更、温度で色もつけてほしい」
#   ひまわりの観測そのもの(L1b、HSD 形式)の B13(10.4µm)の明るさ温度を、日本付近 0.025° の格子に。読み込みと温度への換算は satpy(ahi_hsd)。
#   NOAA の noaa-himawari9 の AHI-L1b-FLDK/YYYY/MM/DD/HHMM/HS_H09_YYYYMMDD_HHMM_B13_FLDK_R20_S0110.DAT.bz2(全球を 10 の帯に分けたもの)のうち日本付近の帯だけ取る。
#   KV hima/ir/<時刻> = gzip(uint8 [ny][nx]、南から北・西から東。値 = 温度(K) − 150(1〜254)、255 = 欠け・宇宙)。hima:meta の ir(新しい順に IR_KEEP 個)・ir_grid
L1B = "AHI-L1b-FLDK"
IR_D, IR_KEEP = 0.025, 3

def ir_grid():
    lats = LAT0 + IR_D * np.arange(int(round((LAT1 - LAT0) / IR_D)) + 1); lons = LON0 + IR_D * np.arange(int(round((LON1 - LON0) / IR_D)) + 1)
    return lats, lons

def ir_segments():
    """日本付近が入っている帯(1〜10)。全球 5500 行を 550 行ずつ"""
    lats, lons = ir_grid(); LO, LA = np.meshgrid(lons, lats); ln, cl = geos_linecol(LA, LO)
    ok = np.isfinite(ln); return sorted({int(x) // 550 + 1 for x in (int(ln[ok].min()), int(ln[ok].max()))} | set(range(int(ln[ok].min()) // 550 + 1, int(ln[ok].max()) // 550 + 2)))

def latest_ir(hours=2):
    """日本付近の帯がそろった一番新しい観測の (時刻, [キー])"""
    segs = ir_segments()
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, second=0, microsecond=0); now = now.replace(minute=now.minute // 10 * 10)
    for i in range(hours * 6):
        t = now - dt.timedelta(minutes=10 * i); pre = f"{L1B}/{t:%Y/%m/%d/%H%M}/"
        r = requests.get(S3 + "/", params={"list-type": "2", "prefix": pre}, headers=UA, timeout=60); r.raise_for_status()
        ks = re.findall(r"<Key>([^<]*_B13_FLDK_R20_S(\d\d)10\.DAT(?:\.bz2)?)</Key>", r.text)
        have = {int(sg): k for k, sg in ks}
        if all(sg in have for sg in segs): return t, [have[sg] for sg in segs]
    return None

def build_ir(paths):
    """HSD の B13 の帯 → 日本付近 0.025° の uint8(温度 − 150)"""
    import bz2, warnings
    from satpy import Scene
    files = []
    for p in paths:
        if p.endswith(".bz2"):
            q = p[:-4]
            with bz2.open(p, "rb") as f, open(q, "wb") as g:
                while True:
                    b = f.read(1 << 22)
                    if not b: break
                    g.write(b)
            os.remove(p); p = q
        files.append(p)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        scn = Scene(reader="ahi_hsd", filenames=files); scn.load(["B13"])
        d = scn["B13"]; area = d.attrs["area"]
        lats, lons = ir_grid(); LO, LA = np.meshgrid(lons, lats)
        col, row = area.get_array_indices_from_lonlat(LO, LA)
        ok = ~np.ma.getmaskarray(col) & ~np.ma.getmaskarray(row)
        col = np.ma.filled(col, 0).astype(int); row = np.ma.filled(row, 0).astype(int)
        r0, r1, c0, c1 = int(row[ok].min()), int(row[ok].max()) + 1, int(col[ok].min()), int(col[ok].max()) + 1
        log(f"赤外 B13: 全体 {d.shape}、日本付近 = 行 {r0}〜{r1}・列 {c0}〜{c1}、衛星 {d.attrs.get('platform_name')} {d.attrs.get('start_time')}")
        sub = np.asarray(d[r0:r1, c0:c1].values, dtype="f4")
    K = sub[np.clip(row - r0, 0, r1 - r0 - 1), np.clip(col - c0, 0, c1 - c0 - 1)]
    out = np.where(ok & np.isfinite(K), np.clip(np.rint(K - 150), 1, 254), 255).astype("u1")
    q = K[ok & np.isfinite(K)]
    if q.size < 0.5 * K.size: raise RuntimeError(f"赤外の値が足りません({q.size}/{K.size})")
    p = np.percentile(q, [1, 50, 99]); log(f"赤外の温度 K 1/50/99%: {p[0]:.0f}/{p[1]:.0f}/{p[2]:.0f}")
    if not (200 < p[1] < 320): raise RuntimeError("赤外の温度がおかしい")
    return out, {"lat0": LAT0, "dlat": IR_D, "ny": len(lats), "lon0": LON0, "dlon": IR_D, "nx": len(lons)}

def do_ir(kv, meta, ir_files=None, ir_time=None):
    """赤外の最新を KV に。meta(hima:meta の dict)の ir・ir_grid を書き換える。変えたら True"""
    import gzip
    t0 = time.time()
    if ir_files: tt, paths = ir_time, list(ir_files); tmp = None
    else:
        f = latest_ir()
        if not f: raise RuntimeError("赤外(L1b B13)の日本付近の帯が直近 2 時間にそろっていません")
        tt, keys = f
        if any(x["t"] == f"{tt:%Y-%m-%dT%H:%MZ}" for x in meta.get("ir", [])): log(f"赤外 {tt:%H:%MZ} はもうあります"); return False
        tmp = tempfile.mkdtemp(); paths = []
        for k in keys:
            p = os.path.join(tmp, k.split("/")[-1]); n = download(k, p, parts=4); paths.append(p)
        log(f"赤外 取得 {len(keys)} 個 {time.time()-t0:.0f}秒")
    try: arr, grid = build_ir(paths)
    finally:
        if tmp: import shutil; shutil.rmtree(tmp, ignore_errors=True)
    t = f"{tt:%Y-%m-%dT%H:%MZ}"; k = f"hima/ir/{tt:%Y%m%dT%H%MZ}"
    z = gzip.compress(arr.tobytes(), 6); kv.put(k, z, TTL)
    meta["ir"] = sorted([{"t": t, "key": k}] + [x for x in meta.get("ir", []) if x["t"] != t], key=lambda x: x["t"], reverse=True)[:IR_KEEP]
    meta["ir_grid"] = grid; meta["ir_enc"] = "gzip(uint8 温度K−150、255 = 欠け)"
    log(f"赤外 できました: {t}、{len(z)/1e3:.0f}KB(gzip)、{time.time()-t0:.0f}秒")
    return True

def do_l2(kv, meta, a):
    """雲頂・雲の種類の最新を KV に。変えたら True"""
    t0 = time.time(); typ = None
    def add_type(p, pos):
        nonlocal typ
        try: typ = build_type(p, *pos)
        except Exception as e: log(f"雲の種類は作れませんでした(雲頂だけ置きます): {e}")
    if a.file:
        tt = dt.datetime.strptime(a.time, "%Y%m%dT%H%MZ"); arr, grid, src, pos = build(a.file)
        if a.type_file: add_type(a.type_file, pos)
    else:
        fs = latest_files()
        if not fs: raise RuntimeError("ひまわりの雲頂のファイルが直近 6 時間に見つかりません(NOAA の遅れ・止まり)")
        tt, key, tkey = fs
        old_t = {x["t"]: x for x in meta.get("times", [])}.get(f"{tt:%Y-%m-%dT%H:%MZ}")
        if old_t and (old_t.get("type") or not tkey): log(f"{tt:%H:%MZ} はもうあります。何もしません"); return False
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "chgt.nc"); n = download(key, p)
            log(f"取得 {key.split('/')[-1]} {n/1e6:.0f}MB {time.time()-t0:.0f}秒")
            arr, grid, src, pos = build(p); os.remove(p)
            if tkey:
                p2 = os.path.join(tmp, "cphs.nc"); n = download(tkey, p2)
                log(f"取得 {tkey.split('/')[-1]} {n/1e6:.0f}MB {time.time()-t0:.0f}秒")
                add_type(p2, pos)
            else: log("雲の種類(CPHS)はまだ出ていないので、雲頂だけ置きます")
    t = f"{tt:%Y-%m-%dT%H:%MZ}"; k = f"hima/{tt:%Y%m%dT%H%MZ}"
    kv.put(k, arr.tobytes() + (typ.tobytes() if typ is not None else b""), TTL)
    times = [{"t": t, "key": k, "type": typ is not None}] + [x for x in meta.get("times", []) if x["t"] != t]
    meta["times"] = sorted(times, key=lambda x: x["t"], reverse=True)[:KEEP]
    # layers は一番新しい回(Map が取るのは times[0])のもの
    meta.update({"grid": grid, "layers": ["fl", "type"] if typ is not None else ["fl"], "types": CT_CLASSES, "src": src, "enc": "uint8 FL/2、0 = 雲なし、255 = 欠け",
                 "attribution": "Himawari-9 / NOAA (AHI L1b, Enterprise Cloud Height・Phase/Type), NOAA Open Data Dissemination"})
    log(f"できました: {t}、{(arr.nbytes + (typ.nbytes if typ is not None else 0))/1e3:.0f}KB" + ("(雲頂 + 種類)" if typ is not None else "(雲頂だけ)") + f"、{time.time()-t0:.0f}秒")
    return True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", default="", help="KV に書かず、このフォルダに出す(試験用)")
    ap.add_argument("--file", default="", help="ローカルの AHI-CHGT の nc を使う(試験用)")
    ap.add_argument("--time", default="", help="--file・--ir-files の観測時刻 YYYYMMDDTHHMMZ")
    ap.add_argument("--type-file", default="", help="ローカルの AHI-CPHS の nc(試験用)")
    ap.add_argument("--ir-files", nargs="*", default=None, help="ローカルの HSD の B13 の帯(試験用)")
    ap.add_argument("--only", default="", help="l2 か ir だけ(試験用)")
    a = ap.parse_args()
    kv = KV(a.dry_run or None)
    old = kv.get("hima:meta"); meta = json.loads(old) if old else {}
    errs, changed = [], False
    # v171 雲頂・種類(L2)と赤外(L1b)は別々に。片方が失敗してももう片方は置く
    if a.only != "ir":
        try: changed |= do_l2(kv, meta, a)
        except Exception as e: errs.append(f"雲頂: {e}"); log(f"雲頂は作れませんでした: {e}")
    if a.only != "l2" and (a.ir_files is None or a.ir_files):
        try: changed |= do_ir(kv, meta, a.ir_files, dt.datetime.strptime(a.time, "%Y%m%dT%H%MZ") if a.ir_files else None)
        except Exception as e: errs.append(f"赤外: {e}"); log(f"赤外は作れませんでした: {e}")
    if changed and (meta.get("times") or meta.get("ir")):
        kv.put("hima:meta", json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    if errs: raise SystemExit("うまくいかなかったもの: " + " / ".join(errs))

if __name__ == "__main__":
    main()
