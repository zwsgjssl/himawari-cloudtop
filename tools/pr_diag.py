import io, json, requests, numpy as np
from PIL import Image
UA = {"User-Agent": "skai-pr-diag/1.0"}; B = "https://www.jma.go.jp/bosai/jmatile/data/rasrf"
tt = requests.get(B + "/targetTimes.json", headers=UA, timeout=30).json()
I = [e for e in tt if e["member"] == "immed"]; print(json.dumps(I))
N = sorted([e for e in tt if e["basetime"].endswith("0000") and e["member"] == "none" and len(e["elements"]) > 5], key=lambda e: e["basetime"])
b = N[-1]["basetime"]; print("none 毎時", b, sorted(e["validtime"][8:12] for e in tt if e["basetime"] == b and e["member"] == "none"))
for e in sorted(I, key=lambda e: e["validtime"]):
    for z in (6,):
        u = f"{B}/{e['basetime']}/immed/{e['validtime']}/surf/rasrf/{z}/55/25.png"; r = requests.get(u, headers=UA, timeout=30)
        try:
            im = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA")).reshape(-1, 4); s = {}
            for c in map(tuple, im[im[:, 3] > 0][:, :3].tolist()): s[c] = s.get(c, 0) + 1
            print(e["validtime"], r.status_code, sorted(s.items(), key=lambda kv: -kv[1])[:10])
        except Exception as x: print(e["validtime"], r.status_code, r.content[:80])
