# 診断(2026-11-25、その 7: 25日 00Z を狙う回を 5 つ)
# 診断(2026-11-25、その 6): VWS を手元で計算し直すため、24日 12Z の回 +12h(25日 00Z)の UKMET の風(全部の気圧面)を
#   北緯 24〜39°・東経 120〜141° で切り出して out/uv_box.npz に(公開の UKMET の値だけ)
import os, sys, tempfile, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
os.makedirs("out", exist_ok=True)
for run, lead in [("20261124T1200Z", 12), ("20261124T0600Z", 18), ("20261124T0000Z", 24), ("20261123T1800Z", 30), ("20261123T1200Z", 36)]:
    def get(nm, w):
        p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, nm), p); r = ub.cut(p, True); os.remove(p); return r
    try:
        with tempfile.TemporaryDirectory() as w:
            lat, lon, T, _, _ = get(ub.FILES["T"], w); S, uS = get(ub.FILES["S"], w)[2:4]; D = get(ub.FILES["D"], w)[2]
    except Exception as e: print("取れない", run, e); continue
    Skt = S*ub.KT if uS.strip().lower() not in ("kt", "knots", "knot") else S
    rad = np.deg2rad(D); U, V = -Skt*np.sin(rad), -Skt*np.cos(rad)
    y = (lat >= 24) & (lat <= 39); x = (lon >= 120) & (lon <= 141)
    np.savez_compressed(f"out/uv_{run[:11]}.npz", lat=lat[y], lon=lon[x], P=np.array(ub.LEVELS_HPA, float), U=U[:, y][:, :, x].astype("f4"), V=V[:, y][:, :, x].astype("f4"), T=T[:, y][:, :, x].astype("f4"))
    print("回", run, "+%d" % lead, flush=True)
