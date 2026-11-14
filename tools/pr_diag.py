# 診断: FGEN の塗りすぎを減らす案の比べ。日本付近(30〜42N・128〜146E、FL240〜390 の気圧面)で、しきい値ごとの面積 %。
#   そのまま / 5×5 点(約 50km)の平均でならす / 9×9 点(約 90km)、と昨日の揺れ(GUSRO 付近 FL236〜251、11〜12Z)の値
import os, sys, tempfile, datetime as dt, numpy as np
from numpy.lib.stride_tricks import sliding_window_view as swv
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
R = 6371e3; P = np.array(ub.LEVELS_HPA, float); LA, LO = 35.6624, 139.1370
def get(run, lead, name, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, name), p); return ub.cut(p, True)
def box(F, n): return np.nanmean(swv(np.pad(F, n//2, mode="edge"), (n, n)), axis=(-1, -2))
TH_ = [1, 1.5, 2, 3, 4, 5, 6]
def fg_of(run, lead, w):
    lat, lon, T, _, _ = get(run, lead, ub.FILES["T"], w); S, uS = get(run, lead, ub.FILES["S"], w)[2:4]; D = get(run, lead, ub.FILES["D"], w)[2]
    TK = T if np.nanmean(T) > 150 else T + 273.15
    Sms = S/ub.KT if uS.strip().lower() in ("kt", "knots", "knot") else S
    rad = np.deg2rad(D); U, V = -Sms*np.sin(rad), -Sms*np.cos(rad)
    dlat = np.deg2rad(lat[1] - lat[0]); dlon = np.deg2rad(lon[1] - lon[0]); cl = np.cos(np.deg2rad(lat))[None, :, None]
    ddx = lambda F: np.gradient(F, axis=2)/(R*cl*dlon); ddy = lambda F: np.gradient(F, axis=1)/(R*dlat)
    TH = TK*(1000/P[:, None, None])**0.2857; tx, ty = ddx(TH), ddy(TH)
    return lat, lon, -(tx*tx*ddx(U) + tx*ty*(ddx(V) + ddy(U)) + ty*ty*ddy(V))/(np.hypot(tx, ty) + 1e-12)*1.08e9
ks = [k for k, p in enumerate(P) if 200 <= p <= 400]
with tempfile.TemporaryDirectory() as w:
    cases = [("昨日 14日12Z(揺れの日)", "20261114T0600Z", 6)]
    run = next(r for r in ub.list_runs() if ub.run_ready(r)); t0 = dt.datetime.strptime(run, "%Y%m%dT%H%MZ")
    for h in (12, 15, 18, 21):
        cases.append((f"今日 {(t0 + dt.timedelta(hours=h)):%d日%H}Z(日本 {(t0 + dt.timedelta(hours=h+9)):%H}時)", run, h))
    for nm, rn, ld in cases:
        lat, lon, FG = fg_of(rn, ld, w); dom = np.ix_((lat >= 30) & (lat <= 42), (lon >= 128) & (lon <= 146))
        j = int(np.argmin(abs(lat - LA))); i = int(np.argmin(abs(lon - LO)))
        print(f"== {nm}  面積 %(しきい値 {' / '.join(map(str, TH_))})")
        for lab, n in (("そのまま", 1), ("50km でならす", 5), ("90km でならす", 9)):
            Fs = np.stack([box(FG[k], n) if n > 1 else FG[k] for k in ks]); A = Fs[(slice(None),) + dom].ravel()
            g = [np.nanmax(Fs[ks.index(k)][j-3:j+4, i-3:i+4]) for k in (P.tolist().index(400), P.tolist().index(375))]
            print(f"  {lab:<10} " + " ".join(f"{100*(A >= t).mean():5.1f}" for t in TH_) + f"   GUSRO 400/375hPa 周り30km最大 {g[0]:.1f}/{g[1]:.1f}")
