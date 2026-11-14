import io, json, requests, numpy as np
from PIL import Image
UA = {"User-Agent": "skai-pr-diag/1.0"}; B = "https://www.jma.go.jp/bosai/jmatile/data/rasrf"
tt = requests.get(B + "/targetTimes.json", headers=UA, timeout=30).json(); g = {}
for e in tt: g.setdefault((e["basetime"], e["member"]), []).append(e)
for (b, m), L in sorted(g.items()):
    L.sort(key=lambda e: e["validtime"]); print(b, m, len(L), L[0]["validtime"][8:12], "→", L[-1]["validtime"][8:12], sorted(set(sum([e["elements"] for e in L], []))))
b = max(k[0] for k in g if k[1] == "none"); L = sorted(g[(b, "none")], key=lambda e: e["validtime"])
for e in L[:7]:
    u = f"{B}/{b}/none/{e['validtime']}/surf/rasrf/6/55/25.png"; r = requests.get(u, headers=UA, timeout=30)
    im = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA")).reshape(-1, 4); s = {}
    for c in map(tuple, im[im[:, 3] > 0][:, :3].tolist()): s[c] = s.get(c, 0) + 1
    print(e["validtime"], r.status_code, sorted(s.items(), key=lambda kv: -kv[1])[:10])
