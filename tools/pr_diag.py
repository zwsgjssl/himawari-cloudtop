# 診断(2026-11-24): ユーザー「ITM→HND で 9 時だと雲頂 350 くらいだけど、12 時にすると中層・高層の雲はほとんど消えてる。UKMET だと寒冷前線は 12 時には抜けきる予想？」
#   伊丹〜羽田の直線の 9 点で、24日 00〜15Z の雲頂(Map と同じ: rh_bytes の湿度で上から最初に雲の面)・中層と高層の雲の有無・850hPa の風と気温を出す
import os, sys, tempfile, datetime as dt, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
P = np.array(ub.LEVELS_HPA, float)
def fl_of(p): return (1 - (p/1013.25)**0.190284)*145366.45/100
FL = np.array([fl_of(p) for p in P]); A, B = (34.785, 135.438), (35.553, 139.781)
PTS = [(A[0] + (B[0] - A[0])*k/8, A[1] + (B[1] - A[1])*k/8) for k in range(9)]
def get(run, lead, nm, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, nm), p); r = ub.cut(p, True); os.remove(p); return r
run = next(r for r in ub.list_runs(2) if ub.exists(ub.key_of(r, 12, ub.FILES["RH"]))[0]); r0 = dt.datetime.strptime(run, "%Y%m%dT%H%MZ"); print("回", run)
with tempfile.TemporaryDirectory() as w:
    for vh in range(0, 18, 3):
        v = dt.datetime(2026, 11, 24, vh); lead = int((v - r0).total_seconds()//3600)
        if lead < 0: continue
        lat, lon, T, _, _ = get(run, lead, ub.FILES["T"], w); RH = get(run, lead, ub.FILES["RH"], w)[2]; S, uS = get(run, lead, ub.FILES["S"], w)[2:4]; D = get(run, lead, ub.FILES["D"], w)[2]
        Tc = T - 273.15 if np.nanmean(T) > 150 else T
        R = np.frombuffer(ub.rh_bytes(RH, Tc, lead)[0], dtype="u1").reshape(Tc.shape).astype("f4")
        cl = R >= np.where(Tc < -20, 96.25, 95.0); L85 = list(P).index(850)
        row = []
        for la, lo in PTS:
            y = int(np.argmin(abs(lat - la))); x = int(np.argmin(abs(lon - lo))); c = cl[:, y, x]
            top = max([FL[k] for k in range(len(P)) if c[k]], default=0)
            mid = any(c[k] for k in range(len(P)) if 100 <= FL[k] < 200); hi = any(c[k] for k in range(len(P)) if FL[k] >= 200)
            row.append(f"FL{top:3.0f}{'中' if mid else '・'}{'高' if hi else '・'} {D[L85, y, x]:3.0f}°{Tc[L85, y, x]:+3.0f}")
        print(f"{v:%d %HZ}({(v + dt.timedelta(hours=9)):%H}JST) +{lead:2d}h  ITM→HND: " + " | ".join(row))
print("各点 = 雲頂 FL・中層(FL100〜200)と高層(FL200 以上)に雲があるか・850hPa の風向と気温。点は伊丹から羽田へ 9 等分")
