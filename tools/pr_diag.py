# 診断(2026-11-14 ユーザー「島根の北のエコーをほとんど予想できていない・那覇の北西は場所がずれている」)
# 気象庁の高解像度降水ナウキャストの実況(hrpns)と UKMET の precipitation_rate(Map の降水と同じ)を並べて描く
import os, sys, io, math, json, datetime as dt, tempfile
import numpy as np, requests
from PIL import Image
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
UA = {"User-Agent": "skai-pr-diag/1.0"}; NOWC = "https://www.jma.go.jp/bosai/jmatile/data/nowc"
PAL = [((242,242,255),0.5),((160,210,255),3),((33,140,255),7.5),((0,65,255),15),((250,245,0),25),((255,153,0),40),((255,40,0),65),((180,0,104),100)]
Z = 6
def t2ll(x, y): n = 2**Z; return math.degrees(math.atan(math.sinh(math.pi*(1 - 2*y/n)))), x/n*360 - 180
def ll2t(la, lo): n = 2**Z; return (lo + 180)/360*n, (1 - math.log(math.tan(math.radians(la)) + 1/math.cos(math.radians(la)))/math.pi)/2*n
def radar(bt, vt, box):
    la0, la1, lo0, lo1 = box; x0, y0 = ll2t(la1, lo0); x1, y1 = ll2t(la0, lo1)
    tiles = {}; seen = {}
    for tx in range(int(x0), int(x1) + 1):
        for ty in range(int(y0), int(y1) + 1):
            r = requests.get(f"{NOWC}/{bt}/none/{vt}/surf/hrpns/{Z}/{tx}/{ty}.png", headers=UA, timeout=30)
            if r.status_code != 200: print("tile", tx, ty, r.status_code); continue
            im = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA")); tiles[(tx, ty)] = im
            for c in map(tuple, im.reshape(-1, 4)[::7]):
                if c[3] > 0: seen[c[:3]] = seen.get(c[:3], 0) + 1
    print("色", sorted(seen.items(), key=lambda kv: -kv[1])[:12])
    LA = np.arange(la0, la1, 0.02); LO = np.arange(lo0, lo1, 0.02); out = np.zeros((len(LA), len(LO)))
    cols = np.array([p[0] for p in PAL], float); vals = np.array([p[1] for p in PAL])
    for j, la in enumerate(LA):
        for i, lo in enumerate(LO):
            fx, fy = ll2t(la, lo); t = tiles.get((int(fx), int(fy)))
            if t is None: continue
            c = t[min(255, int((fy % 1)*256)), min(255, int((fx % 1)*256))]
            if c[3] == 0: continue
            out[j, i] = vals[np.argmin(((cols - c[:3])**2).sum(1))]
    return LA, LO, out
def main():
    tt = requests.get(NOWC + "/targetTimes_N1.json", headers=UA, timeout=30).json()
    obs = sorted([e for e in tt if e["basetime"] == e["validtime"]], key=lambda e: e["validtime"])
    print("実況", obs[0]["validtime"], "〜", obs[-1]["validtime"])
    runs = [r for r in ub.list_runs(2) if ub.exists(ub.key_of(r, 6, ub.FILES["RH"]))[0]][:2]; print("回", runs)
    boxes = {"shimane": (33.0, 38.5, 129.0, 136.0), "naha": (24.0, 30.0, 122.0, 130.0)}
    lat = lon = None; U = {}
    with tempfile.TemporaryDirectory() as w:
        for run in runs:
            r0 = dt.datetime.strptime(run, "%Y%m%dT%H%MZ")
            for v in ("00", "03"):
                V = dt.datetime(2026, 11, 14, int(v)); lead = int((V - r0).total_seconds()//3600)
                if lead < 0 or lead % 3: continue
                p = os.path.join(w, "p"); ub.download(ub.key_of(run, lead, "precipitation_rate"), p); lat, lon, a, u, _ = ub.cut(p, False)
                U[(run, v)] = np.nan_to_num(ub.pr_mmh(a, u)); print(run, v, lead, u, float(U[(run, v)].max()))
    picks = []
    for want in ("20261114000000", obs[-1]["validtime"]):
        e = min(obs, key=lambda e: abs(int(e["validtime"]) - int(want))); picks.append(e)
    os.makedirs("out", exist_ok=True)
    cmap = ListedColormap(["#ffffff", "#e8eaff", "#a0d2ff", "#218cff", "#0041ff", "#fff500", "#ff9900", "#ff2800", "#b40068"]); norm = BoundaryNorm([0, 0.1, 1, 5, 10, 20, 30, 50, 80, 999], 9)
    coast = json.load(open(os.path.join(os.path.dirname(__file__), "coast_sat.json"))) if os.path.exists(os.path.join(os.path.dirname(__file__), "coast_sat.json")) else None
    for name, box in boxes.items():
        R = [(e["validtime"], radar(e["basetime"], e["validtime"], box)) for e in picks]
        panels = [("JMA " + vt[8:12] + "Z", g) for vt, g in R] + [(f"UK {run[6:8]}{run[9:11]}Z run, {v}Z", (lat, lon, A)) for (run, v), A in U.items()]
        fig, ax = plt.subplots(1, len(panels), figsize=(4.2*len(panels), 4.6))
        for k, (tl, (LA, LO, A)) in enumerate(panels):
            yi = (LA >= box[0]) & (LA <= box[1]); xi = (LO >= box[2]) & (LO <= box[3]); S = A[np.ix_(yi, xi)]
            ax[k].pcolormesh(LO[xi], LA[yi], S, cmap=cmap, norm=norm, shading="nearest"); ax[k].set_title(tl, fontsize=9); ax[k].set_aspect(1/math.cos(math.radians((box[0]+box[1])/2)))
            if coast:
                for ring in (coast if isinstance(coast, list) else coast.get("rings", [])):
                    try: q = np.array(ring, float); ax[k].plot(q[:, 0], q[:, 1], "k-", lw=.4)
                    except Exception: pass
                ax[k].set_xlim(box[2], box[3]); ax[k].set_ylim(box[0], box[1])
            print(name, tl, "max %.1f  >=0.1: %.1f%%  >=1: %.1f%%  >=5: %.1f%%" % (S.max(), (S >= .1).mean()*100, (S >= 1).mean()*100, (S >= 5).mean()*100))
            if S.sum() > 0:
                W = np.where(S >= 1, S, 0) if (S >= 1).any() else S; Y, X = np.meshgrid(LA[yi], LO[xi], indexing="ij")
                print("   重心(>=1mm/h) %.2fN %.2fE" % ((W*Y).sum()/W.sum(), (W*X).sum()/W.sum()))
        fig.tight_layout(); fig.savefig(f"out/{name}.png", dpi=90); plt.close(fig)
if __name__ == "__main__": main()
