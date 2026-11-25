# 診断(2026-11-25、その 5: 750・650・550 も入れた本当の 50hPa おきを足す)
# 診断(2026-11-25、その 4: 格子の値も out/ に npz で。手元で会社の図に重ねる)
# 診断(2026-11-25、その 3): ユーザー「会社の断面図がどの層をとってるのか調べて」(HND→GMP・HND→TSA、valid 25日 00Z)
#   会社の図と同じ向き(左 = 行き先、右 = 羽田)・縦は ISA の高さで、VWS 6・9・12 の線を層の取り方と回を変えて描く(図は out/ に)
#   会社の飛行計画の風は前の回の UKMET(PROG 欄)なので、24日 12Z・06Z、23日 12Z の回も描く
import os, sys, tempfile, numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
plt.rcParams["font.family"] = "Noto Sans CJK JP"
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
P = np.array(ub.LEVELS_HPA, float); PLs = list(P)
def ft(p): return (1 - (p/1013.25)**0.190284)*145366.45
RT = {"GMP": ((37.558, 126.791), (35.553, 139.781)), "TSA": ((25.069, 121.552), (35.553, 139.781))}
SETS = {"25面(Map)": PLs, "50hPa": [1000, 950, 900, 850, 800, 700, 600, 500, 450, 400, 350, 300, 250, 200, 150],
        "GSM風": [1000, 975, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300, 250, 200, 150], "主な面": [1000, 925, 850, 700, 500, 400, 300, 250, 200, 150], "全50hPa": [1000, 950, 900, 850, 800, 750, 700, 650, 600, 550, 500, 450, 400, 350, 300, 250, 200, 150]}
RUNS = [("20261124T1200Z", 12)]
N = 61; ZG = np.arange(5000, 45001, 250)
def get(run, lead, nm, w):
    p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, lead, nm), p); r = ub.cut(p, True); os.remove(p); return r
DATA = {}
with tempfile.TemporaryDirectory() as w:
    for run, lead in RUNS:
        try:
            if not ub.exists(ub.key_of(run, lead, ub.FILES["S"]))[0]: print("無い", run, lead); continue
            lat, lon, T, _, _ = get(run, lead, ub.FILES["T"], w); S, uS = get(run, lead, ub.FILES["S"], w)[2:4]; D = get(run, lead, ub.FILES["D"], w)[2]
        except Exception as e: print("取れない", run, e); continue
        Skt = S*ub.KT if uS.strip().lower() not in ("kt", "knots", "knot") else S
        rad = np.deg2rad(D); DATA[run] = (lat, lon, -Skt*np.sin(rad), -Skt*np.cos(rad)); print("回", run, "+%d" % lead, flush=True)
def section(run, rt, lv):
    lat, lon, U, V = DATA[run]; A, B = RT[rt]; g = np.full((len(ZG), N), np.nan)
    ix = [PLs.index(p) for p in lv]
    for k in range(N):
        la = A[0] + (B[0] - A[0])*k/(N - 1); lo = A[1] + (B[1] - A[1])*k/(N - 1)
        y = int(np.argmin(abs(lat - la))); x = int(np.argmin(abs(lon - lo)))
        z = [(ft(P[i]) + ft(P[j]))/2 for i, j in zip(ix[:-1], ix[1:])]
        v = [np.hypot(U[j, y, x] - U[i, y, x], V[j, y, x] - V[i, y, x])/((ft(P[j]) - ft(P[i]))/1000) for i, j in zip(ix[:-1], ix[1:])]
        g[:, k] = np.interp(ZG, z, v, left=np.nan, right=np.nan)
    return g
os.makedirs("out", exist_ok=True)
for rt in RT:
    panels = [(r, s) for r in [x[0] for x in RUNS] if r in DATA for s in SETS]
    fig, axs = plt.subplots(1, len(panels), figsize=(5.5*len(panels), 4.2), squeeze=False)
    for ax, (run, sn) in zip(axs.flat, panels):
        g = section(run, rt, SETS[sn]); X = np.linspace(0, 1, N)
        ax.set_facecolor("black"); ax.contour(X, ZG/100, g, levels=[6, 9, 12], colors=["#7bed2a", "#ffd400", "#ff7a00"], linewidths=1.6)
        ax.set_ylim(0, 450); ax.set_yticks(range(0, 451, 50)); ax.grid(color="#444", lw=.5); ax.set_xticks([0, 1]); ax.set_xticklabels([rt, "RJTT"])
        ax.set_title(f"{run[6:8]}日{run[9:11]}Z の回・{sn}  6以上 {np.nanmean(g >= 6)*100:.0f}%・最大 {np.nanmax(g):.1f}", fontsize=10)
        print(rt, run, sn, "6以上 %.0f%%  9以上 %.0f%%  最大 %.1f" % (np.nanmean(g >= 6)*100, np.nanmean(g >= 9)*100, np.nanmax(g)))
    fig.tight_layout(); fig.savefig(f"out/vws_{rt}.png", dpi=70); plt.close(fig)
np.savez_compressed("out/vws_grids.npz", ZG=ZG, **{f"{rt}_{i}": section("20261124T1200Z", rt, SETS[sn]) for rt in RT for i, sn in enumerate(SETS)})
print("図: out/vws_GMP.png・out/vws_TSA.png(左 = 行き先、右 = 羽田、縦 = FL)")
