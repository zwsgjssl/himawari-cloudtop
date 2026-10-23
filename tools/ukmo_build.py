#!/usr/bin/env python3
# UKMET(英国気象局 Met Office の全球モデル 10km)の上空の気温・風と圏界面を、日本付近だけ切り出して Cloudflare の KV に置く。
#   GitHub Actions(.github/workflows/ukmo.yml)から動かす。起動は Cloudflare の定期実行(worker/ukmo.js)が GitHub の API で行う。
#   v190 公開リポジトリ(zwsgjssl/himawari-cloudtop)へ移した(公開リポジトリの Actions は時間の制限なし)。中身は前と同じ。Met Office の公開データを切り出すだけで、鍵は GitHub の Secrets。
#
# データ: AWS の公開データ met-office-atmospheric-model-data(eu-west-2、アカウント不要)。
#   global-deterministic-10km/<回>/<対象時刻>-PT0024H00M-temperature_on_pressure_levels.nc のように、予報時刻ごと・変数ごとに 1 ファイル(全部の気圧面入り)。
#   1 ファイル 150〜230MB。必要な予報時刻のファイルだけを分割して並行に取り(HTTP の Range)、切り出したら消す。
#   ライセンス: CC BY-SA 4.0、© Crown copyright, Met Office(図に出典を表示すること)。無料・サポートなし。
#
# KV に置くもの(キーは ukmo/<回>/<予報時刻>。48 時間で自動で消える。2 つ前の回はこのスクリプトが消す):
#   int16 の並び(リトルエンディアン): [層 25][気温・東西風・南北風 3][緯度 ny][経度 nx] のあとに 圏界面の気圧 [ny][nx]
#   気温 = ℃×10、風 = kt×10(東西風は東向き +、南北風は北向き +)、圏界面 = hPa×10、欠け = -32768
#   最後に ukmo:meta(JSON。回・格子・層・予報時刻とキーの一覧)を書く。worker はこれを見て新しい回に切り替える
#   湿度(キーは ukmo/<回>/<予報時刻>/rh): uint8 の [層 25][緯度 ny][経度 nx]、%(0℃ 未満は氷に対する値)、255 = 欠け(v138、VSD の雲)
#   揺れの指標(キーは ukmo/<回>/<予報時刻>/ix): int16 の [層 25][TI1 1][緯度 ny][経度 nx](v151 から TI1 だけ。前は TI1・TI2・NCSU1・EKI・CCAT の 5 つ)
#     TI1 = VWS×DEF、TI2 = VWS×(DEF−DIV)(Ellrod & Knapp 1992。単位 1e-7 s⁻² の ×10、0〜3276)
#     EKI = TI1 + max(0.1×(発散の 6 時間の変化、1e-6 s⁻¹ 単位), 0)(Ellrod-Knox。Knox ほか 2006)
#     NCSU1 = max(u∂u/∂x + v∂v/∂y, 0)×|∇ζ| / max(Ri, 1e-5)(Kaplan ほか 2006。単位 s⁻³ を log10 にして ×1000。0 以下は -32767)
#     どれもその気圧面で。鉛直の差(VWS・Ri)は上下の気圧面、水平の微分は格子の中心差分。
#   KV の容量(無料 1GB)を超えないよう、新しい回を書いたら 2 つ前の回のキーを消す(ukmo:prev に前の回のキーを覚えておく)
#
# 環境変数: CF_API_TOKEN(KV の編集権限)、CF_ACCOUNT_ID、CF_KV_WX_ID(KV の ID)。
#   試験用: UKMO_S3_BASE(S3 の代わり)、CF_API_BASE(Cloudflare API の代わり)、--dry-run(KV に書かずフォルダに出す)
import argparse, datetime as dt, gzip, json, os, re, shutil, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import requests

S3 = os.environ.get("UKMO_S3_BASE", "https://met-office-atmospheric-model-data.s3.eu-west-2.amazonaws.com").rstrip("/")
PREFIX = "global-deterministic-10km"
LEVELS_HPA = [1000, 975, 950, 925, 900, 850, 800, 750, 700, 650, 600, 550, 500, 450,
              400, 375, 350, 325, 300, 275, 250, 225, 200, 175, 150]   # 地上付近から FL443 まで 25 層(上空は 25hPa おき)。
# VSD の縦軸は FL450 まで。125hPa(約 FL490)より上は図の外で、圏界面は UKMET 自身の値(pressure_at_tropopause)を使うので要らない
LEADS = [0, 3, 6, 9, 12, 15, 18, 21]                                                # 予報時刻(時間)。回が出るのは約 5.5 時間後なので、次の回までの 12 時間先を覆う。
# v140 0 時間(解析)も入れる: 今の 1 つ前の時刻(3 時間前)も見られるように(ユーザー「UKMET は現在の 1 つ前の時間も取れるように」)
# v143 24 時間はやめた(ユーザー「3 時間前から 9 時間後まででいい」)。回が届くのは回の 5.5〜6 時間後、次の回まで 6 時間なので、今 −3h 〜 +9h に要るのは 0〜21 時間
LAT0, LAT1, LON0, LON1 = 20.0, 50.0, 118.0, 152.0                                     # 日本付近(MSM の範囲より少し広く)
FILES = {"T": "temperature_on_pressure_levels", "S": "wind_speed_on_pressure_levels",
         "D": "wind_direction_on_pressure_levels", "TP": "pressure_at_tropopause",
         "RH": "relative_humidity_on_pressure_levels"}   # v138 雲(湿度から推定)
NODATA = -32768
KT = 1.0 / 0.514444
TTL = 48 * 3600
UA = {"User-Agent": "approach-planner-wx/1.0 (personal, non-commercial)"}

def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

def key_of(run, lead, name):
    """ファイル名の先頭は「回」ではなく予報の対象時刻(例 12Z の回の 24 時間先 → 20261009T1200Z/20261010T1200Z-PT0024H00M-…)"""
    valid = (dt.datetime.strptime(run, "%Y%m%dT%H%MZ") + dt.timedelta(hours=lead)).strftime("%Y%m%dT%H%MZ")
    return f"{PREFIX}/{run}/{valid}-PT{lead:04d}H00M-{name}.nc"

# ---- S3(公開バケット)----
def s3req(method, url, **kw):
    """2026-10-23 一覧・HEAD が S3 の一時的な Read timeout で落ちた(05:46Z の回)→ 4 回までやり直す"""
    for attempt in range(4):
        try:
            r = requests.request(method, url, headers=UA, timeout=60, **kw)
            if r.status_code >= 500: raise RuntimeError(f"HTTP {r.status_code}")
            return r
        except Exception as e:
            if attempt == 3: raise
            log(f"S3 {method} やり直し {attempt+1}: {e}"); time.sleep(5 + attempt*10)

def list_runs(days=3):
    """新しい順の回の一覧(例 20261010T0000Z)。直近 days 日だけ"""
    after = f"{PREFIX}/{(dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=days)).strftime('%Y%m%dT0000Z')}"
    runs, token = [], None
    while True:
        q = {"list-type": "2", "delimiter": "/", "prefix": PREFIX + "/", "start-after": after}
        if token: q["continuation-token"] = token
        r = s3req("GET", S3 + "/", params=q); r.raise_for_status()
        runs += re.findall(rf"<Prefix>{PREFIX}/(\d{{8}}T\d{{4}}Z)/</Prefix>", r.text)
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", r.text)
        if not m: break
        token = m.group(1)
    return sorted(set(runs), reverse=True)

def exists(key):
    r = s3req("HEAD", f"{S3}/{key}")
    return r.status_code == 200, int(r.headers.get("Content-Length") or 0)

def run_ready(run):
    """その回の、使う予報時刻のうち一番先(24 時間)の 4 ファイルが揃っているか"""
    return all(exists(key_of(run, LEADS[-1], f))[0] for f in FILES.values())

def download(key, path, parts=8):
    """Range で分割して並行に取る(1 本より速い)"""
    ok, size = exists(key)
    if not ok: raise RuntimeError("ファイルがありません: " + key)
    step = max(1, -(-size // parts))
    with open(path, "wb") as f: f.truncate(size)
    def part(i):
        a, b = i*step, min(size, (i+1)*step) - 1
        if a > b: return 0
        for attempt in range(4):
            try:
                r = requests.get(f"{S3}/{key}", headers={**UA, "Range": f"bytes={a}-{b}"}, timeout=300)
                if r.status_code not in (200, 206): raise RuntimeError(f"HTTP {r.status_code}")
                data = r.content
                if r.status_code == 200: data = data[a:b+1]   # Range が効かない相手(試験用サーバーなど)
                if len(data) != b - a + 1: raise RuntimeError("長さが合いません")
                with open(path, "r+b") as f: f.seek(a); f.write(data)
                return len(data)
            except Exception as e:
                if attempt == 3: raise
                time.sleep(2 + attempt*3)
    with ThreadPoolExecutor(parts) as ex: got = sum(ex.map(part, range(parts)))
    return got

# ---- NetCDF から日本付近を切り出す ----
def main_var(ds):
    """データの本体の変数(次元がいちばん多いもの。座標・境界・格子定義は除く)"""
    cands = [v for v in ds.data_vars if ds[v].ndim >= 2 and not v.endswith("_bnds") and not v.endswith("_bounds")]
    if not cands: raise RuntimeError("データの変数が見つかりません: " + str(list(ds.data_vars)))
    return max(cands, key=lambda v: (ds[v].ndim, ds[v].size))

def dim_like(da, words):
    for d in da.dims:
        if any(w in d.lower() for w in words): return d
    return None

def cut(path, need_levels):
    """→ (lat 昇順, lon, data[L,ny,nx] または [ny,nx], 単位)"""
    import xarray as xr
    with xr.open_dataset(path, engine="h5netcdf", decode_times=False) as ds:
        name = main_var(ds); da = ds[name]
        la, lo, pr = dim_like(da, ["lat"]), dim_like(da, ["lon"]), dim_like(da, ["press"])
        if not la or not lo: raise RuntimeError(f"{name}: 緯度・経度の次元が見つかりません {da.dims}")
        for d in da.dims:   # 長さ 1 の時刻などは落とす
            if d not in (la, lo, pr) and da.sizes[d] == 1: da = da.isel({d: 0})
        lat = np.asarray(ds[la].values, dtype="f8"); lon = np.asarray(ds[lo].values, dtype="f8")
        lon = np.where(lon > 180, lon - 360, lon)
        yi = np.where((lat >= LAT0 - 1e-6) & (lat <= LAT1 + 1e-6))[0]; xi = np.where((lon >= LON0 - 1e-6) & (lon <= LON1 + 1e-6))[0]
        if not len(yi) or not len(xi): raise RuntimeError("日本付近の格子がありません")
        xi = xi[np.argsort(lon[xi])]
        sel = {la: yi, lo: xi}
        if need_levels:
            if not pr: raise RuntimeError(f"{name}: 気圧の次元が見つかりません {da.dims}")
            p = np.asarray(ds[pr].values, dtype="f8"); p_hpa = p/100 if p.max() > 2000 else p
            zi = []
            for L in LEVELS_HPA:
                k = int(np.argmin(np.abs(p_hpa - L)))
                if abs(p_hpa[k] - L) > 0.5: raise RuntimeError(f"{name}: {L}hPa がありません(ある面: {sorted(set(np.round(p_hpa).astype(int)))})")
                zi.append(k)
            sel[pr] = zi
            arr = da.isel(sel).transpose(pr, la, lo).values.astype("f8")
        else:
            arr = da.isel(sel).transpose(la, lo).values.astype("f8")
        units = str(da.attrs.get("units", ""))
        la_s, lo_s = lat[yi], lon[xi]
    order = np.argsort(la_s)   # 緯度は南から北へ
    return la_s[order], lo_s, (arr[..., order, :]), units, name

def q16(x, scale):
    y = np.round(np.asarray(x) * scale)
    y = np.where(np.isfinite(y), np.clip(y, -32767, 32767), NODATA)
    return y.astype("<i2")

R_EARTH = 6371000.0
def cat_indices(Tc, Ukt, Vkt, lat, dlat, dlon):
    """揺れの指標(各気圧面)。Tc ℃・U/V kt、[L,ny,nx] → TI1(1e-7 s⁻²)"""
    u, v = Ukt * 0.514444, Vkt * 0.514444
    p = np.array(LEVELS_HPA, dtype="f8")[:, None, None]
    TK = Tc + 273.15
    dzl = 29.2712 * (TK[:-1] + TK[1:]) / 2 * np.log(p[:-1] / p[1:])      # 隣の面との厚さ m(測高公式)
    z = np.concatenate([np.zeros_like(TK[:1]), np.cumsum(dzl, axis=0)])
    th = TK * (1000.0 / p) ** 0.2857
    L = TK.shape[0]; lo = np.r_[0, np.arange(L - 1)]; hi = np.r_[np.arange(1, L), L - 1]   # 上下の面(端は片側)
    # v2026-10-19 ユーザー「平面図で上の高度のほうが中間高度より TI1 小さい」(羽田〜花巻 FL350〜FL390 で LP〜MOD の日):
    #   前は 1 つ上と 1 つ下の面の差 → ジェットの芯の高さでは上下とも弱いので打ち消し合い、芯のすぐ下の強いシアーが消えていた。
    #   上・下の隣の面との差の大きい方にする(端は片側)。全体に 3 割ほど大きく出る(Map のしきい値も 10・16・22 に)
    sh = np.hypot(u[1:] - u[:-1], v[1:] - v[:-1]) / dzl                      # 隣どうしの層のシアー s⁻¹ [L-1]
    VWS = np.zeros_like(u); VWS[:-1] = sh; VWS[1:] = np.maximum(VWS[1:], sh)
    dy = R_EARTH * np.deg2rad(dlat); dx = (R_EARTH * np.cos(np.deg2rad(lat)) * np.deg2rad(dlon))[None, :, None]
    dudx, dudy = np.gradient(u, axis=2) / dx, np.gradient(u, axis=1) / dy
    dvdx, dvdy = np.gradient(v, axis=2) / dx, np.gradient(v, axis=1) / dy
    # v151 ユーザー「TI1 と Ri だけでいい」→ 指標は TI1 だけ計算する(TI2・NCSU1・EKI・CCAT はやめた。Ri は Map・worker が気温と風から出す)
    DEF = np.hypot(dudx - dvdy, dvdx + dudy)
    TI1 = VWS * DEF * 1e7
    return TI1

# ---- CCAT(v136、Claude が組み立てた合成 CAT 指標) ----
# 考え方(GTG と同じ枠組みを、UKMET 25 層と日本付近に合わせて小さく作り直したもの):
#   CAT の主な起こり方ごとに 1 つずつ指標を選び、それぞれを「EDR 相当」(m^(2/3) s⁻¹)に直してから、強いものを重く見る平均(2 乗平均)でまとめる。
#   v144 まとめ方を変えた: 各指標の z(いつもより何σ強いか)をソフトマックスでまとめ、その点数自体の気候値で標準化してから EDR の分布に当てはめる
#     (→ どの日も気候の上では EDR ≥0.15 が約 9%、≥0.22 が約 2%、≥0.34 が約 0.2% の割合。前は平均でならされて 0.15 にほとんど届かなかった)
#   ① シア不安定(ケルビン・ヘルムホルツ)… 1/Ri(上下の面の差。0.1 で頭打ち → 最大 10)
#   ② 前線帯の変形とシア ……………………… TI1(Met Office の比較で一番良かった。重み 1.5)
#   ③ 前線が強まっている所 ……………………… 水平の前線形成関数 F(Petterssen、+ だけ)
#   ④ 釣り合いの崩れ(ジェットの出口・急な曲がりで出る重力波)… ラグランジュのロスビー数 |DV/Dt|/(|f||V|)(DV/Dt = ∂V/∂t + V·∇V、∂V/∂t は前後 3 時間の差)
#   ⑤ 渦の強さの差と流れの急変 ………………… NCSU1
#   EDR への直し方(GTG と同じ): 各指標 D の ln D が対数正規(平均 μ、標準偏差 σ。気圧面ごと)だとして、ln EDR = −2.572 + 0.5067×(ln D − μ)/σ
#   (−2.572・0.5067 は GTG の論文の、実際の EDR の気候値の ln の平均と標準偏差)。μ・σ は過去の回の移動平均(KV の ukmo:clim、α = 0.1)
#   → 毎日の UKMET から自分で「いつもの値」を覚えて、いつもより強い所だけが EDR で大きく出る。D ≦ 0 は μ − 2σ(穏やか)とみなす。
#   しきい値の目安は NCAR の GTG と同じ 0.15(弱)・0.22(並)・0.34(強)。ただし実際の揺れ(PIREP・EDR)で確かめた値ではない。
CC_W = {"ri": 1.0, "ti1": 1.5, "fg": 1.0, "lro": 1.0, "nc": 1.0}
MU_E, SD_E, CC_ALPHA, CC_A = -2.572, 0.5067, 0.1, 2.0

def cc_components(cats, i):
    c = cats[i]; n = len(cats)
    a, b = (i - 1, i + 1) if 0 < i < n - 1 else ((0, 1) if i == 0 else (n - 2, n - 1))
    dt_ = (LEADS[b] - LEADS[a]) * 3600.0
    dudt, dvdt = (cats[b]["u"] - cats[a]["u"]) / dt_, (cats[b]["v"] - cats[a]["v"]) / dt_
    f = np.abs(2 * 7.292e-5 * np.sin(np.deg2rad(c["lat"])))[None, :, None]
    LRo = np.hypot(dudt + c["ADu"], dvdt + c["ADv"]) / (f * np.maximum(np.hypot(c["u"], c["v"]), 5.0))
    return {"ri": np.minimum(1.0 / np.maximum(c["Ri"], 0.1), 10.0) * (c["Ri"] > -1e9), "ti1": c["TI1"], "fg": np.maximum(c["FG"], 0), "lro": LRo, "nc": c["NC"]}

def cc_stats(comps_all, levels):
    """各指標・各気圧面の ln D の平均と標準偏差(D > 0 の点)"""
    out = {}
    for k in CC_W:
        mu, sd = [], []
        for L in range(len(LEVELS_HPA)):
            if L not in levels: mu.append(None); sd.append(None); continue
            x = np.concatenate([cm[k][L].ravel() for cm in comps_all]); x = x[np.isfinite(x) & (x > 0)]
            if x.size < 100: mu.append(None); sd.append(None); continue
            lx = np.log(x); mu.append(float(np.mean(lx))); sd.append(float(max(np.std(lx), 1e-3)))
        out[k] = {"mu": mu, "sd": sd}
    return out

def cc_blend(old, new):
    if not old: return new
    out = {}
    for k in new:
        o = old.get(k) or {"mu": [None] * len(LEVELS_HPA), "sd": [None] * len(LEVELS_HPA)}; m = {"mu": [], "sd": []}
        for L in range(len(LEVELS_HPA)):
            for q in ("mu", "sd"):
                a, b = o[q][L] if L < len(o[q]) else None, new[k][q][L]
                m[q].append(b if a is None else a if b is None else (1 - CC_ALPHA) * a + CC_ALPHA * b)
        out[k] = m
    return out

def cc_score(comps, clim):
    """v144 各指標を「いつもより何σ強いか」(z)にして、強いものを重く見るまとめ方(ソフトマックス: (1/a)·ln Σw·e^(a·z) / Σw、a = 2)。[L,ny,nx]"""
    num = None; den = None; A = CC_A
    for k, w in CC_W.items():
        mu = np.array([np.nan if v is None else v for v in clim[k]["mu"]])[:, None, None]
        sd = np.array([np.nan if v is None else v for v in clim[k]["sd"]])[:, None, None]
        D = comps[k]
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(D > 0, (np.log(np.maximum(D, 1e-30)) - mu) / sd, -2.0)
        z = np.clip(z, -4, 6); ok = np.isfinite(z)   # 気候値がまだ無い指標・面は、その面では使わない
        wn = np.where(ok, w, 0.0); t = np.where(ok, np.exp(A * z), 0.0)
        num = wn * t if num is None else num + wn * t; den = wn if den is None else den + wn
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, np.log(np.maximum(num, 1e-30) / np.where(den > 0, den, 1)) / A, np.nan)

def cc_zstats(S_all, levels):
    """まとめた点数の気圧面ごとの平均・標準偏差(対数にしない)"""
    mu, sd = [], []
    for L in range(len(LEVELS_HPA)):
        if L not in levels: mu.append(None); sd.append(None); continue
        x = np.concatenate([S[L].ravel() for S in S_all]); x = x[np.isfinite(x)]
        if x.size < 100: mu.append(None); sd.append(None); continue
        mu.append(float(np.mean(x))); sd.append(float(max(np.std(x), 1e-3)))
    return {"mu": mu, "sd": sd}

def cc_edr(S, cs):
    """まとめた点数 → その気候値で標準化 → EDR の気候の分布(対数正規)に当てはめる。0.01〜1"""
    mu = np.array([np.nan if v is None else v for v in cs["mu"]])[:, None, None]
    sd = np.array([np.nan if v is None else v for v in cs["sd"]])[:, None, None]
    with np.errstate(invalid="ignore"):
        return np.clip(np.exp(MU_E + SD_E * (S - mu) / sd), 0.01, 1.0)

# ---- v138 雲(VSD 用): 気圧面の相対湿度 ----
# 雲そのもの(cloud_amount_on_height_levels)は高さ 6km くらいまでしか無いので、全部の気圧面にある相対湿度から雲を推し量る(雲量は Map で Sundqvist の式)。
# 0℃ 未満は氷に対する湿度にそろえる: Met Office の値が水に対するものなら(-40℃ 以下で 99.9% 値が 95% 未満 = 氷の飽和に届いていない)、es_w/es_i を掛ける。
def rh_bytes(RH, Tc, lead):
    RH = np.asarray(RH, dtype="f8")
    if np.nanmax(RH) <= 1.5: RH = RH * 100.0           # 0〜1 で来たら %
    cold = Tc < -40
    p999 = float(np.nanpercentile(RH[cold], 99.9)) if np.any(cold) else 100.0
    # v2026-10-19 ユーザー「羽田千歳の断面図、赤外では雲が多いのに断面図は下層しか雲が無い」→ 18Z の回は 99.9% 値が 85.4% で「氷」と判定され、
    #   上層の雲(UKMET 自身の上層雲量 100% の所で RH 60〜75%)が消えていた。氷に対する値なら上層の雲の中は 100% 前後になるので、95% 未満なら水に対する値とみなす
    water = p999 < 95.0
    if water:
        esw = 6.112 * np.exp(17.67 * Tc / (Tc + 243.5)); esi = 6.112 * np.exp(22.46 * Tc / (Tc + 272.62))
        RH = np.where(Tc < 0, RH * esw / esi, RH)
    log(f"  PT{lead:02d} 湿度: -40℃ 以下の 99.9% 値 {p999:.0f}% → " + ("水に対する値とみなして 0℃ 未満を氷に対する値に直した" if water else "氷に対する値とみなした(そのまま)"))
    out = np.where(np.isfinite(RH), np.clip(np.round(RH), 0, 250), 255).astype("u1")
    return out.tobytes(), ("water" if water else "ice")

# ---- v145 雲頂(平面図用): 雲(雲量 50% 以上 = VSD と同じ Sundqvist で RH が 95%(-20℃ 以上)・96.25%(-20℃ 未満)以上)のある一番上の気圧面の FL ----
# int16 [ny][nx]、FL(0 = 雲なし)。キー ukmo/<回>/<時刻>/ct
def cloud_top(rhb, Tc):
    R = np.frombuffer(rhb, dtype="u1").reshape(Tc.shape).astype("f4")
    thr = np.where(Tc < -20, 96.25, 95.0)
    cl = (R >= thr) & (R != 255)
    L = Tc.shape[0]; idx = L - 1 - np.argmax(cl[::-1], axis=0)   # 上から見て最初に雲のある面
    has = cl.any(axis=0)
    fl = np.array([145366.45 * (1 - (p / 1013.25) ** 0.190284) / 100 for p in LEVELS_HPA])
    return np.where(has, np.round(fl[idx]), 0).astype("<i2").tobytes()

# ---- v144 端末に保存する用(オフライン): 元データ(気温・風・圏界面・湿度)を、精度を落とさずに小さくする ----
# 形: gzip( "UKO1" + uint32 nA + uint32 nB + uint32 nx + A' + B' )
#   A = KV の基本の並び(int16 [25][3][ny][nx] + 圏界面 [ny][nx])。行(東西 nx 点)ごとに隣との差にして(int16 で桁あふれは折り返し)、
#       下位バイトを全部 → 上位バイトを全部 の順に並べ替える(差は小さいので上位バイトがほぼ 0 か 255 になり、よく縮む)
#   B = 湿度 uint8 [25][ny][nx]。行ごとに隣との差(256 で折り返し)
#   Map は展開して元に戻すだけなので、値は KV と全く同じ
def off_bytes(buf, rhb, nx):
    a = np.frombuffer(buf, dtype="<i2").reshape(-1, nx)
    d = a.copy(); d[:, 1:] = (a[:, 1:].astype("i4") - a[:, :-1].astype("i4")).astype("<i2")
    by = d.view("u1").reshape(-1, 2)
    A = np.concatenate([by[:, 0], by[:, 1]]).tobytes()
    r = np.frombuffer(rhb, dtype="u1").reshape(-1, nx)
    e = r.copy(); e[:, 1:] = (r[:, 1:].astype("i2") - r[:, :-1].astype("i2")).astype("u1")
    head = b"UKO1" + np.array([a.size, r.size, nx], dtype="<u4").tobytes()
    return gzip.compress(head + A + e.tobytes(), compresslevel=9, mtime=0)

def q16log(x):
    with np.errstate(divide="ignore", invalid="ignore"):
        y = np.where(x > 0, np.round(np.log10(np.maximum(x, 1e-30)) * 1000), -32767)
    y = np.where(np.isfinite(x), np.clip(y, -32767, 32767), NODATA)
    return y.astype("<i2")

def build_slice(run, lead, work):
    """1 つの予報時刻 → (バイト列, 格子の情報)"""
    paths = {}
    def get(k):
        p = os.path.join(work, f"{k}.nc"); t0 = time.time()
        n = download(key_of(run, lead, FILES[k]), p)
        log(f"  PT{lead:02d} {FILES[k]}: {n/1e6:.0f}MB {time.time()-t0:.0f}秒")
        paths[k] = p
    with ThreadPoolExecutor(4) as ex: list(ex.map(get, FILES))
    lat, lon, T, uT, _ = cut(paths["T"], True)
    lat2, lon2, S, uS, _ = cut(paths["S"], True)
    lat3, lon3, D, _, _ = cut(paths["D"], True)
    lat4, lon4, TP, uTP, _ = cut(paths["TP"], False)
    lat5, lon5, RH, _, _ = cut(paths["RH"], True)
    for a, b in ((lat, lat2), (lat, lat3), (lat, lat4), (lat, lat5), (lon, lon2), (lon, lon3), (lon, lon4), (lon, lon5)):
        if a.shape != b.shape or np.max(np.abs(a - b)) > 1e-6: raise RuntimeError("ファイルごとに格子が違います")
    for p in paths.values(): os.remove(p)
    Tc = T - 273.15 if (uT.strip() in ("K", "kelvin") or np.nanmean(T) > 150) else T
    Skt = S * KT if uS.strip().lower() not in ("kt", "knots", "knot") else S
    rad = np.deg2rad(D)
    U, V = -Skt*np.sin(rad), -Skt*np.cos(rad)          # 風が吹いてくる向き → 東向き・北向きの成分
    TPh = TP/100 if np.nanmax(TP) > 2000 else TP        # Pa → hPa
    L, ny, nx = T.shape
    body = np.empty((L, 3, ny, nx), dtype="<i2")
    body[:, 0], body[:, 1], body[:, 2] = q16(Tc, 10), q16(U, 10), q16(V, 10)
    buf = body.tobytes() + q16(TPh, 10).tobytes()
    rhb, rh_mode = rh_bytes(RH, Tc, lead)
    ctb = cloud_top(rhb, Tc)
    dlat_, dlon_ = (lat[-1] - lat[0]) / (ny - 1), (lon[-1] - lon[0]) / (nx - 1)
    TI1 = cat_indices(Tc, U, V, lat, dlat_, dlon_)
    cat = {"TI1": TI1.astype("f4")}
    up = [i for i, P in enumerate(LEVELS_HPA) if 200 <= P <= 400]           # 巡航高度あたりの分布(しきい値を決めるための記録)
    pc = lambda a: " ".join(f"{q:.3g}" for q in np.nanpercentile(a[up], [50, 90, 99, 99.9]))
    log(f"  PT{lead:02d} 400〜200hPa の分布(50/90/99/99.9%) TI1 {pc(TI1)}")
    info = {"ny": int(ny), "nx": int(nx), "lat0": float(lat[0]), "lat1": float(lat[-1]), "lon0": float(lon[0]), "lon1": float(lon[-1]),
            "dlat": float((lat[-1] - lat[0])/(ny - 1)), "dlon": float((lon[-1] - lon[0])/(nx - 1)),
            "regular": bool(np.max(np.abs(np.diff(lat) - (lat[-1]-lat[0])/(ny-1))) < 1e-4 and np.max(np.abs(np.diff(lon) - (lon[-1]-lon[0])/(nx-1))) < 1e-4)}
    # 確かめ: 値の範囲(おかしければ止める)
    chk = {"T": (np.nanmin(Tc), np.nanmax(Tc)), "wind": float(np.nanmax(Skt)), "trop": (np.nanmin(TPh), np.nanmax(TPh))}
    if not (-100 < chk["T"][0] < chk["T"][1] < 55): raise RuntimeError(f"気温の範囲がおかしい {chk['T']}")   # 下層は夏に 40℃ 近くもある
    if not (0 < chk["wind"] < 400): raise RuntimeError(f"風速の範囲がおかしい {chk['wind']}")
    if not (30 < chk["trop"][0] <= chk["trop"][1] < 700): raise RuntimeError(f"圏界面の気圧の範囲がおかしい {chk['trop']}")
    log(f"  PT{lead:02d} 格子 {ny}x{nx} 気温 {chk['T'][0]:.1f}〜{chk['T'][1]:.1f}℃ 最大風 {chk['wind']:.0f}kt 圏界面 {chk['trop'][0]:.0f}〜{chk['trop'][1]:.0f}hPa → {len(buf)/1e6:.1f}MB")
    return buf, cat, info, rhb, ctb

# ---- Cloudflare KV ----
class KV:
    def __init__(self, dry=None):
        self.dry = dry
        if dry: os.makedirs(dry, exist_ok=True); return
        self.base = os.environ.get("CF_API_BASE", "https://api.cloudflare.com/client/v4").rstrip("/")
        acc, ns, tok = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_KV_WX_ID"), os.environ.get("CF_API_TOKEN")
        if not (acc and ns and tok): raise SystemExit("CF_ACCOUNT_ID / CF_KV_WX_ID / CF_API_TOKEN が未設定です(GitHub の Secrets に登録)")
        self.url = f"{self.base}/accounts/{acc}/storage/kv/namespaces/{ns}/values/"
        self.h = {**UA, "Authorization": "Bearer " + tok}
    def _f(self, key): return os.path.join(self.dry, key.replace("/", "__"))
    def get(self, key):
        if self.dry:
            return open(self._f(key), "rb").read() if os.path.exists(self._f(key)) else None
        r = requests.get(self.url + requests.utils.quote(key, safe=""), headers=self.h, timeout=60)
        if r.status_code == 404: return None
        r.raise_for_status(); return r.content
    def put(self, key, data, ttl=None):
        if self.dry:
            open(self._f(key), "wb").write(data); return
        for attempt in range(4):
            r = requests.put(self.url + requests.utils.quote(key, safe=""), params={"expiration_ttl": ttl} if ttl else None,
                             headers={**self.h, "Content-Type": "application/octet-stream"}, data=data, timeout=300)
            if r.ok: return
            if attempt == 3: raise RuntimeError(f"KV に書けません({key}): HTTP {r.status_code} {r.text[:300]}")
            time.sleep(3 + attempt*5)

    def delete(self, key):
        if self.dry:
            if os.path.exists(self._f(key)): os.remove(self._f(key))
            return
        r = requests.delete(self.url + requests.utils.quote(key, safe=""), headers=self.h, timeout=60)
        if not r.ok and r.status_code != 404: log(f"  KV のキーを消せません({key}): HTTP {r.status_code}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="", help="回(例 20261010T0000Z)。空なら揃っている一番新しい回")
    ap.add_argument("--force", action="store_true", help="KV にもう同じ回があっても作り直す")
    ap.add_argument("--dry-run", default="", help="KV に書かず、このフォルダに出す(試験用)")
    a = ap.parse_args()
    kv = KV(a.dry_run or None)
    run = a.run.strip()
    if not run:
        for r in list_runs():
            if run_ready(r): run = r; break
        if not run: log("揃っている回がありません"); return
    elif not run_ready(run): raise SystemExit(f"{run} はまだ揃っていません")
    old = kv.get("ukmo:meta"); old = json.loads(old) if old else None
    if old and old.get("run_id", "") >= run and not a.force:
        log(f"KV はもう {old.get('run_id')} です(新しい回なし)。何もしません"); return
    t_run = dt.datetime.strptime(run, "%Y%m%dT%H%MZ").replace(tzinfo=dt.timezone.utc)
    log(f"UKMET {run} を作ります(予報 {LEADS[0]}〜{LEADS[-1]} 時間、{len(LEVELS_HPA)} 層)")
    # v140 2 つ前の回は、書く前に消す(1 回分が約 300MB になったので、書いている間も KV の無料枠 1GB に収まるように。使っている 1 つ前の回は残す)
    prev = kv.get("ukmo:prev"); prev = json.loads(prev) if prev else []
    gone = [k for k in prev if k and f"/{run}/" not in k]
    for k in gone: kv.delete(k)
    if gone: log(f"2 つ前の回のキーを {len(gone)} 個消しました")
    work = tempfile.mkdtemp(prefix="ukmo_")
    slices, grid, t0 = [], None, time.time()
    try:
        bufs, cats, rhs, cts = [], [], [], []
        for lead in LEADS:
            buf, cat, info, rhb, ctb = build_slice(run, lead, work)
            if grid is None: grid = info
            elif any(abs(grid[k] - info[k]) > 1e-6 for k in ("lat0", "lon0", "dlat", "dlon")) or grid["ny"] != info["ny"] or grid["nx"] != info["nx"]:
                raise RuntimeError("予報時刻ごとに格子が違います")
            bufs.append(buf); cats.append(cat); rhs.append(rhb); cts.append(ctb)
        n = len(cats)
        for i, lead in enumerate(LEADS):
            c = cats[i]; L, ny, nx = c["TI1"].shape
            ix = np.empty((L, 1, ny, nx), dtype="<i2")   # v151 TI1 だけ([層][1][y][x])
            ix[:, 0] = q16(np.clip(c["TI1"], 0, 3276), 10)
            key = f"ukmo/{run}/{lead:03d}"; ixb = ix.tobytes()
            offb = off_bytes(bufs[i], rhs[i], nx)
            kv.put(key, bufs[i], TTL); kv.put(key + "/ix", ixb, TTL); kv.put(key + "/rh", rhs[i], TTL); kv.put(key + "/off", offb, TTL); kv.put(key + "/ct", cts[i], TTL)
            log(f"  PT{lead:02d} 端末保存用 {(len(bufs[i]) + len(rhs[i]))/1e6:.1f}MB → {len(offb)/1e6:.1f}MB(gzip)")
            slices.append({"lead": lead, "t": (t_run + dt.timedelta(hours=lead)).strftime("%Y-%m-%dT%H:%MZ"), "key": key, "ix": key + "/ix", "rh": key + "/rh", "off": key + "/off", "offBytes": len(offb), "ct": key + "/ct",
                           "bytes": len(bufs[i]) + len(ixb) + len(rhs[i]) + len(offb)})
            cats[i] = None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    meta = {"model": "ukmo", "name": "UKMET (Met Office Global 10km)", "run_id": run, "run": t_run.strftime("%Y-%m-%dT%H:%MZ"),
            "created": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%MZ"), "lv": LEVELS_HPA, "vars": ["T", "u", "v"],
            "scale": 10, "nodata": NODATA, "unit": {"T": "degC", "u": "kt", "v": "kt", "trop": "hPa"}, "trop": True,
            "ix": {"vars": ["ti1"], "enc": ["x10"], "unit": ["1e-7/s2"]},
            "off": {"fmt": "UKO1"}, "ct": {"enc": "int16 FL(0 = 雲なし)"},
            "rh": {"enc": "uint8 %(0〜250、255 = 欠け)", "ice": "0℃ 未満は氷に対する湿度"},
            "grid": grid, "slices": slices, "attribution": "Contains Met Office data © Crown copyright, Met Office (CC BY-SA 4.0)"}
    kv.put("ukmo:meta", json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    # 次に消すのは 1 つ前の回(いま KV の meta が指していた回)。消すのは次の回を書く前
    if old and old.get("run_id") != run:
        kv.put("ukmo:prev", json.dumps([k for s_ in old.get("slices", []) for k in (s_.get("key"), s_.get("ix"), s_.get("rh"), s_.get("off"), s_.get("ct")) if k]).encode("utf-8"))
    log(f"できました: {run}、{len(slices)} 時刻、合計 {sum(s['bytes'] for s in slices)/1e6:.0f}MB、{time.time()-t0:.0f}秒")

if __name__ == "__main__":
    main()
