# 診断(2026-11-25): ユーザー「同じ UKMET の valid 00Z で HND→GMP の断面図。いつも会社の断面図より VWS が少し強い。確認して」
#   羽田〜金浦の直線(Map の断面図と同じ)で、25日 00Z(24日 12Z の回 +12h)の VWS(kt/1000ft)を、層の取り方を変えて比べる
#   a = Map と同じ(UKMET の 25 面、隣どうしの面の間、厚さは ISA)
#   b = 主な気圧面だけ(1000・925・850・700・500・400・300・250・200・150)。会社の断面図の縦軸の線と同じ面
#   c = 50hPa おき程度
#   d = a と同じ面で、厚さを気温から(層の本当の厚さ)
import os, sys, tempfile, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
P = np.array(ub.LEVELS_HPA, float); PLs = list(P)
def ft(p): return (1 - (p/1013.25)**0.190284)*145366.45
A, B = (35.553, 139.781), (37.558, 126.791); N = 41
PTS = [(A[0] + (B[0] - A[0])*k/(N - 1), A[1] + (B[1] - A[1])*k/(N - 1)) for k in range(N)]
def get(run, lead, nm, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, nm), p); r = ub.cut(p, True); os.remove(p); return r
run = "20261124T1200Z"; lead = 12
if not ub.exists(ub.key_of(run, lead, ub.FILES["T"]))[0]: print("回が無い", run); sys.exit()
with tempfile.TemporaryDirectory() as w:
    lat, lon, T, _, _ = get(run, lead, ub.FILES["T"], w); S, uS = get(run, lead, ub.FILES["S"], w)[2:4]; D = get(run, lead, ub.FILES["D"], w)[2]
Tk = T if np.nanmean(T) > 150 else T + 273.15
Skt = S*ub.KT if uS.strip().lower() not in ("kt", "knots", "knot") else S
rad = np.deg2rad(D); U, V = -Skt*np.sin(rad), -Skt*np.cos(rad)
print("回", run, "+%dh" % lead, "風の単位", uS)
cols = []
for la, lo in PTS:
    y = int(np.argmin(abs(lat - la))); x = int(np.argmin(abs(lon - lo))); cols.append((U[:, y, x], V[:, y, x], Tk[:, y, x]))
SETS = {"a": PLs, "b": [1000, 925, 850, 700, 500, 400, 300, 250, 200, 150], "c": [1000, 950, 900, 850, 800, 700, 600, 500, 450, 400, 350, 300, 250, 200, 150]}
FLR = list(range(450, 40, -10))
def prof(c, lv, hyps=False):
    ix = [PLs.index(p) for p in lv if p in PLs and p >= 150]
    zs, vs = [], []
    for i, j in zip(ix[:-1], ix[1:]):
        if hyps: dz = 287.05*(c[2][i] + c[2][j])/2/9.80665*np.log(P[i]/P[j])*3.28084
        else: dz = ft(P[j]) - ft(P[i])
        zm = (ft(P[i]) + ft(P[j]))/2
        if zm < 5000: continue
        zs.append(zm); vs.append(np.hypot(c[0][j] - c[0][i], c[1][j] - c[1][i])/(dz/1000))
    return np.array(zs), np.array(vs)
def grid(kind):
    g = np.full((len(FLR), N), np.nan)
    for k, c in enumerate(cols):
        z, v = prof(c, SETS["a" if kind == "d" else kind], kind == "d")
        g[:, k] = np.interp([f*100 for f in FLR], z, v, left=np.nan, right=np.nan)
    return g
def ch(v): return " " if np.isnan(v) else "." if v < 6 else "6" if v < 9 else "9" if v < 12 else "C"
G = {k: grid(k) for k in "abcd"}
print("左 = 羽田、右 = 金浦(%d 点、約 %dNM おき)。 . <6  6 = 6〜9  9 = 9〜12  C = 12 以上" % (N, round(669/(N - 1))))
for k, name in [("a", "Map と同じ(25 面)"), ("d", "25 面・厚さを気温から"), ("c", "50hPa おき程度"), ("b", "主な面だけ(会社の図の縦軸の面)")]:
    g = G[k]; print("\n[%s] %s  6以上の割合 %.0f%%  9以上 %.0f%%  最大 %.1f" % (k, name, np.nanmean(g >= 6)*100, np.nanmean(g >= 9)*100, np.nanmax(g)))
    for r, f in enumerate(FLR):
        if f % 20 == 10 and f < 440: continue
        print("FL%03d %s" % (f, "".join(ch(v) for v in g[r])))
print("\n層ごと(羽田〜金浦の平均・最大)")
for kind in "ab":
    L = SETS[kind]
    for p0, p1 in zip(L[:-1], L[1:]):
        if p0 > 700: continue
        i0, i1 = PLs.index(p0), PLs.index(p1)
        vv = [np.hypot(c[0][i1] - c[0][i0], c[1][i1] - c[1][i0])/((ft(p1) - ft(p0))/1000) for c in cols]
        print("  %s %4d-%4d hPa(FL%03.0f〜%03.0f、厚さ %4.0fft) 平均 %4.1f 最大 %4.1f" % (kind, p0, p1, ft(p0)/100, ft(p1)/100, ft(p1) - ft(p0), np.mean(vv), np.max(vv)))
