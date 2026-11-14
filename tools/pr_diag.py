# 診断: FGEN(2 次元の前線形成関数)の単位と分布の確かめ。値は ℃/1000km/3h(= K m⁻¹ s⁻¹ × 1.08e10)。
#   日本付近(30〜42N・128〜146E)の各気圧面で 1・2・3 以上の面積 % と上位の分布、GUSRO の真上と周り 30km の最大
import os, sys, tempfile, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
LA, LO = 35.6624, 139.1370; R = 6371e3; P = np.array(ub.LEVELS_HPA, float)
def fl_of(p): return (1 - (p/1013.25)**0.190284)*145366.45/100
def get(run, lead, name, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, name), p); return ub.cut(p, True)
def run_case(run, lead, w):
    lat, lon, T, _, _ = get(run, lead, ub.FILES["T"], w); S, uS = get(run, lead, ub.FILES["S"], w)[2:4]; D = get(run, lead, ub.FILES["D"], w)[2]
    TK = T if np.nanmean(T) > 150 else T + 273.15
    Sms = S/ub.KT if uS.strip().lower() in ("kt", "knots", "knot") else S
    rad = np.deg2rad(D); U, V = -Sms*np.sin(rad), -Sms*np.cos(rad)
    dlat = np.deg2rad(abs(lat[1] - lat[0])); dlon = np.deg2rad(abs(lon[1] - lon[0])); sgn = 1 if lat[1] > lat[0] else -1
    coslat = np.cos(np.deg2rad(lat))[None, :, None]
    ddx = lambda F: np.gradient(F, axis=2)/(R*coslat*dlon); ddy = lambda F: sgn*np.gradient(F, axis=1)/(R*dlat)
    TH = TK*(1000/P[:, None, None])**0.2857; tx, ty = ddx(TH), ddy(TH)
    FG = -(tx*tx*ddx(U) + tx*ty*(ddx(V) + ddy(U)) + ty*ty*ddy(V))/(np.hypot(tx, ty) + 1e-12)*1.08e10
    j = int(np.argmin(abs(lat - LA))); i = int(np.argmin(abs(lon - LO))); dom = np.ix_((lat >= 30) & (lat <= 42), (lon >= 128) & (lon <= 146))
    print(f"== {run} +{lead}h  FGEN ℃/1000km/3h。面: GUSRO 真上/周り30km最大  日本付近 ≧1/≧2/≧3 の面積%  分布 50/90/99%")
    for k, p in enumerate(P):
        if p > 500 or p < 175: continue
        F = FG[k]; A = F[dom]
        print(f"  {p:4.0f}hPa FL{fl_of(p):03.0f}  {F[j,i]:5.2f}/{np.nanmax(F[j-3:j+4, i-3:i+4]):5.2f}   {100*(A>=1).mean():4.1f} {100*(A>=2).mean():4.1f} {100*(A>=3).mean():4.1f}   "
              + " ".join(f"{q:5.2f}" for q in np.nanpercentile(A, [50, 90, 99])))
with tempfile.TemporaryDirectory() as w:
    for run, lead in (("20261114T0600Z", 6),):
        try: run_case(run, lead, w)
        except Exception as e: print("失敗", run, lead, repr(e))
