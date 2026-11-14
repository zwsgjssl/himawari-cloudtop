# 診断: 降水短時間予報(rasrf)の時刻の一覧とタイルの色
import io, json, requests, numpy as np
from PIL import Image
UA = {"User-Agent": "skai-pr-diag/1.0"}; B = "https://www.jma.go.jp/bosai/jmatile/data/rasrf"
tt = requests.get(B + "/targetTimes.json", headers=UA, timeout=30).json()
print("件数", len(tt)); print(json.dumps(tt[:3])); 
bs = sorted({e["basetime"] for e in tt}); print("basetime", bs[-5:], len(bs))
nb = bs[-1]; L = sorted([e for e in tt if e["basetime"] == nb], key=lambda e: e["validtime"]); print("最新回", nb, [ (e["validtime"], e.get("member"), e.get("elements")) for e in L])
for e in L[:1] + L[5:6]:
    for z in (5, 6, 7):
        x, y = {5: (27, 12), 6: (55, 25), 7: (110, 50)}[z]
        u = f"{B}/{e['basetime']}/{e.get('member','none')}/{e['validtime']}/surf/rasrf/{z}/{x}/{y}.png"
        r = requests.get(u, headers=UA, timeout=30); print(z, r.status_code, len(r.content), u[len(B):])
        if r.status_code == 200:
            im = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA")).reshape(-1, 4); s = {}
            for c in map(tuple, im[im[:, 3] > 0][:, :3].tolist()): s[c] = s.get(c, 0) + 1
            print("   色", sorted(s.items(), key=lambda kv: -kv[1])[:12])
