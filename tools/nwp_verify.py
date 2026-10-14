#!/usr/bin/env python3
# v206 事後検証(ユーザー「(実際との答え合わせ)いいね!赤外やレーダーも既に取得済みのデータだから使えるね」)
#   Claude の定時の解析が、前の回の予想(nwp_ai/history/<初期時刻>.json の claims)が当たったかを、実際の観測の記録(ブランチ nwp-obs の obs/*.json、tools/obs_build.py)で確かめる道具。
#   結果は Markdown で標準出力に(Claude が読んで解析と lessons.md に生かす)。--json で同じ内容を JSON にも
#   claims の形: [{"id":"c1","kind":"cb|cat|icing|front|low|wind|jet|other","text":"…","box":[南の緯度,北の緯度,西の経度,東の経度],"fl":[下,上](無ければ null),"from":"YYYY-MM-DDTHH:MMZ","to":"…"}]
#   判定(目安。観測が無い所は「分からない」と書く):
#     cb    … 当たり = その範囲・時間に 雷 1 回以上 / レーダー 20mm/h 以上 / 赤外 215K 以下 のどれか。どれも無ければ外れ
#     cat   … 当たり = 福岡 FIR の SIGMET(TURB)か PIREP の MOD 以上の揺れ(範囲・時間・高さが重なる)。無ければ「報告なし」(当たり外れは決めない)
#     icing … 同じく SIGMET(ICE)か PIREP の MOD 以上の着氷
#     それ以外 … 範囲の空港の METAR の目立った物(雷・強風)を並べるだけ
#   予想に無かった事: 前の回のどの claim にも入らない 雷の多い升(1 時間 10 回以上)・SIGMET・PIREP の MOD 以上
import argparse, datetime as dt, glob, json, os, re

def T(s): return dt.datetime.strptime(s.replace("-", "").replace(":", "")[:13], "%Y%m%dT%H%M")
def ep(v):
    """SIGMET の時刻(秒・ミリ秒・ISO 文字列)→ datetime"""
    if v is None: return None
    if isinstance(v, (int, float)): return dt.datetime.utcfromtimestamp(v / 1000 if v > 1e11 else v)
    try: return dt.datetime.fromisoformat(str(v).replace("Z", "")).replace(tzinfo=None)
    except ValueError: return None
def fl(v):
    if v in (None, ""): return None
    try: v = float(v)
    except (TypeError, ValueError): return None
    return int(round(v / 100 if v > 1000 else v))
def cells(b):
    s, n, w, e = b; return [f"{i},{j}" for i in range(int(s // 1), int(-(-n // 1))) for j in range(int(w // 1), int(-(-e // 1)))]
def inbox(b, lat, lon): return lat is not None and lon is not None and b[0] <= float(lat) <= b[1] and b[2] <= float(lon) <= b[3]
def fl_ok(c, lo, hi, pad=20):
    if not c.get("fl") or (lo is None and hi is None): return True
    lo = lo if lo is not None else 0; hi = hi if hi is not None else 600
    return lo <= c["fl"][1] + pad and hi >= c["fl"][0] - pad
SEV = re.compile(r"MOD|SEV|EXTRM", re.I)

def load_obs(d):
    out = []
    for f in sorted(glob.glob(os.path.join(d, "obs", "*.json"))):
        day = os.path.basename(f)[:8]
        for hh, r in json.load(open(f, encoding="utf-8")).get("hours", {}).items():
            out.append((dt.datetime.strptime(day + hh[:2], "%Y%m%d%H"), r))
    return sorted(out, key=lambda x: x[0])

def sig_box(s):
    c = s.get("coords") or []
    pts = [(p.get("lat"), p.get("lon")) for p in c if isinstance(p, dict)] if c and isinstance(c[0], dict) else [tuple(p[:2]) for p in c if isinstance(p, (list, tuple))]
    pts = [(float(a), float(b)) for a, b in pts if a is not None and b is not None]
    if not pts: return None
    return [min(p[0] for p in pts), max(p[0] for p in pts), min(p[1] for p in pts), max(p[1] for p in pts)]
def overlap(a, b): return a and b and a[0] <= b[1] and a[1] >= b[0] and a[2] <= b[3] and a[3] >= b[2]

def sigmets(obs):
    seen, out = set(), []
    for _, r in obs:
        for s in r.get("sigmet") or []:
            k = (s.get("seriesId"), s.get("validTimeFrom"), s.get("hazard"))
            if k in seen: continue
            seen.add(k); out.append(s)
    return out
def pireps(obs):
    seen, out = set(), []
    for _, r in obs:
        for p in r.get("pirep") or []:
            k = p.get("rawOb") or json.dumps(p, sort_keys=True)
            if k in seen: continue
            seen.add(k); out.append(p)
    return out

# v207 UKMET の解析(T+0)。ジェット・シアー・圏界面・着氷層の「実際に近い姿」(モデルの値で、観測そのものではない)
def load_ukmo(d):
    out = []
    for f in sorted(glob.glob(os.path.join(d, "ukmo", "*.json"))):
        try: u = json.load(open(f, encoding="utf-8"))
        except Exception: continue
        if u.get("t0") and u["t0"].get("t"): out.append((T(u["t0"]["t"]), u["t0"]))
    return out
def pct(vals, q):
    v = sorted(vals); return v[min(len(v) - 1, int(len(v) * q))] if v else 0
# 2026-10-14 本物で確かめ: 10km の格子・25hPa の層の厚さだと TI1・シアーの値が大きく出る(升の 90 パーセンタイルの中央値が TI1 6・シアー 5.4kt/1000ft)。
#   決まったしきい値ではなく、その時刻の日本付近全体の中での順位で見る: 上位 10% = 根拠あり、上位 3% = 強い
def uk_th(r):
    ti, vw = list((r.get("ti1") or {}).values()), list((r.get("vws") or {}).values())
    return {"ti90": pct(ti, .9), "vw90": pct(vw, .9), "ti97": pct(ti, .97), "vw97": pct(vw, .97)}
def uk_box(c, recs):
    """claim の範囲・時間にある UKMET 解析の まとめ文と (最大シアー, 最大 TI1)"""
    f0, f1 = T(c["from"]), T(c["to"]); cs = set(cells(c["box"])); lines, hit = [], False
    for t, r in recs:
        if not (f0 - dt.timedelta(hours=3) <= t <= f1 + dt.timedelta(hours=3)): continue
        jet = [v for k, v in (r.get("jet") or {}).items() if k in cs and fl_ok(c, v[1], v[1])]
        vw = max([v for k, v in (r.get("vws") or {}).items() if k in cs] or [0]); ti = max([v for k, v in (r.get("ti1") or {}).items() if k in cs] or [0])
        tr = [v for k, v in (r.get("trop") or {}).items() if k in cs]; ic = [v for k, v in (r.get("ice") or {}).items() if k in cs]
        j = max(jet, key=lambda x: x[0]) if jet else None
        if not j and not vw and not ti and not ic: continue
        lines.append(f"UKMET 解析 {t:%d日%HZ}: " + (f"最大風速 {j[0]}kt(FL{j[1]})・" if j else "") + f"鉛直シアー最大 {vw}kt/1000ft・TI1 最大 {ti}"
                     + (f"・圏界面 FL{min(tr)}〜{max(tr)}" if tr else "") + (f"・着氷しやすい層 FL{min(x[0] for x in ic)}〜{max(x[1] for x in ic)}" if ic else ""))
        th = uk_th(r)
        if ti >= th["ti90"] or vw >= th["vw90"]: hit = True
        lines[-1] += f"(この時刻の上位 10% の目安: TI1 {th['ti90']}・シアー {th['vw90']})"
    return lines, hit

def judge(c, obs, SG, PR, UK=()):
    f0, f1 = T(c["from"]), T(c["to"]); b = c["box"]; cs = set(cells(b))
    hrs = [(h, r) for h, r in obs if f0 < h <= f1 + dt.timedelta(hours=1)]
    if not hrs: return "観測の記録なし(分からない)", []
    ltg = sum(v for h, r in hrs for k, v in ((r.get("ltg") or {}).get("box") or {}).items() if k in cs)
    rmx = max([v for h, r in hrs for k, v in ((r.get("rad") or {}).get("max") or {}).items() if k in cs] or [0])
    irm = min([v for h, r in hrs for k, v in ((r.get("irmin") or {}).get("box") or {}).items() if k in cs] or [999])
    ctp = max([v for h, r in hrs for k, v in ((r.get("ctop") or {}).get("box") or {}).items() if k in cs] or [0])
    info = [f"雷 {ltg} 回・レーダー最大 段階{rmx}" + (f"(20mm/h 以上)" if rmx >= 5 else "") + (f"・赤外最低 {irm}K" if irm < 999 else "") + (f"・雲頂最高 FL{ctp}" if ctp else "")]
    sg = [s for s in SG if overlap(sig_box(s), b) and (ep(s.get("validTimeFrom")) or f0) <= f1 and (ep(s.get("validTimeTo")) or f1) >= f0 and fl_ok(c, fl(s.get("base")), fl(s.get("top")))]
    pr = [p for p in PR if inbox(b, p.get("lat"), p.get("lon")) and (ep(p.get("obsTime")) or f0) >= f0 - dt.timedelta(hours=1) and (ep(p.get("obsTime")) or f1) <= f1 + dt.timedelta(hours=1)
          and fl_ok(c, fl(p.get("fltLvl")), fl(p.get("fltLvl")))]
    for s in sg: info.append(f"SIGMET {s.get('hazard')} {s.get('qualifier') or ''} FL{fl(s.get('base'))}〜{fl(s.get('top'))}: {str(s.get('rawSigmet') or '')[:120]}")
    for p in pr:
        if p.get("tbInt1") or p.get("icgInt1"): info.append(f"PIREP {p.get('obsTime')} FL{fl(p.get('fltLvl'))} {p.get('acType') or ''} 揺れ {p.get('tbInt1') or '-'} 着氷 {p.get('icgInt1') or '-'}")
    ul, uhit = uk_box(c, UK)
    if c.get("kind") != "cb": info += ul   # CB は雷・レーダー・赤外で決める
    k = c.get("kind")
    if k == "cb":
        v = "当たり" if (ltg >= 1 or rmx >= 5 or irm <= 215) else "外れ(雷・強い雨・冷たい雲頂なし)"
    elif k == "cat":
        hit = any("TURB" in str(s.get("hazard", "")).upper() for s in sg) or any(SEV.search(str(p.get("tbInt1") or "")) for p in pr)
        v = "当たり(SIGMET・PIREP)" if hit else "報告なし(当たり外れは決めない)"
        if not hit and ul: v += "・UKMET 解析では " + ("根拠あり(シアーか TI1 が日本付近の上位 10%)" if uhit else "根拠が弱い(シアー・TI1 が日本付近の上位 10% に入らない)")
    elif k == "icing":
        hit = any("ICE" in str(s.get("hazard", "")).upper() for s in sg) or any(SEV.search(str(p.get("icgInt1") or "")) for p in pr)
        v = "当たり(SIGMET・PIREP)" if hit else "報告なし(当たり外れは決めない)"
    else:
        v = "参考"
        for h, r in hrs:
            for m in r.get("metar") or []:
                if inbox(b, m.get("lat"), m.get("lon")) and (re.search(r"TS|\+RA|SQ", str(m.get("wx") or "")) or (m.get("wgst") or 0) >= 25 or (m.get("wspd") or 0) >= 25):
                    info.append(f"METAR {m.get('raw')}")
    return v, list(dict.fromkeys(info))   # 同じ行は 1 つに

def unforecast(claims, obs, SG, PR, t0, t1, UK=()):
    out = []
    for t, r in UK:   # v207 UKMET 解析で強いシアー(TI1 がその時刻の日本付近の上位 3%、シアーも上位 10%)なのに CAT の予想の外
        if not (t0 < t <= t1): continue
        n = 0; th = uk_th(r)
        for k in sorted(set(r.get("ti1") or {}) | set(r.get("vws") or {})):
            ti, vw = (r.get("ti1") or {}).get(k, 0), (r.get("vws") or {}).get(k, 0)
            if not (ti >= th["ti97"] and vw >= th["vw90"]): continue   # TI1 が上位 3% でシアーも上位 10%
            la, lo = map(int, k.split(","))
            if any(c.get("kind") == "cat" and inbox(c["box"], la + .5, lo + .5) for c in claims): continue
            j = (r.get("jet") or {}).get(k)
            if n < 8: out.append(f"UKMET 解析 {t:%d日%HZ} 北緯{la}〜{la+1}・東経{lo}〜{lo+1}: TI1 {ti}・シアー {vw}kt/1000ft" + (f"・最大風速 {j[0]}kt(FL{j[1]})" if j else "") + " が CAT の予想の外")
            n += 1
        if n > 8: out.append(f"(ほかに {n - 8} 升)")
    cb = [c for c in claims if c.get("kind") == "cb"]
    for h, r in obs:
        if not (t0 < h <= t1): continue
        for k, v in ((r.get("ltg") or {}).get("box") or {}).items():
            if v < 10: continue
            la, lo = map(int, k.split(","))
            if not any(inbox(c["box"], la + .5, lo + .5) and T(c["from"]) < h <= T(c["to"]) + dt.timedelta(hours=1) for c in cb):
                out.append(f"{h:%d日%HZ} 雷 {v} 回(北緯{la}〜{la+1}・東経{lo}〜{lo+1})が CB の予想の外")
    for s in SG:
        hz = str(s.get("hazard", "")).upper(); kind = "cat" if "TURB" in hz else "icing" if "ICE" in hz else "cb" if "TS" in hz else None
        a, b = ep(s.get("validTimeFrom")), ep(s.get("validTimeTo"))
        if not kind or (a and a > t1) or (b and b < t0): continue
        if not any(c.get("kind") == kind and overlap(sig_box(s), c["box"]) for c in claims):
            out.append(f"SIGMET {hz} FL{fl(s.get('base'))}〜{fl(s.get('top'))} が予想の外: {str(s.get('rawSigmet') or '')[:120]}")
    for p in PR:
        t = ep(p.get("obsTime"))
        if not t or not (t0 < t <= t1): continue
        for kind, key in (("cat", "tbInt1"), ("icing", "icgInt1")):
            if SEV.search(str(p.get(key) or "")) and not any(c.get("kind") == kind and inbox(c["box"], p.get("lat"), p.get("lon")) for c in claims):
                out.append(f"PIREP {t:%d日%H%MZ} FL{fl(p.get('fltLvl'))} {'揺れ' if kind == 'cat' else '着氷'} {p.get(key)}(北緯{p.get('lat')}・東経{p.get('lon')})が予想の外")
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--obs", required=True, help="ブランチ nwp-obs の中身のフォルダ")
    ap.add_argument("--hist", required=True, help="nwp_ai/history(前の回の ai.json)")
    ap.add_argument("--base", default="", help="今の回(これより前の回を確かめる)")
    ap.add_argument("--hours", type=int, default=48, help="何時間前の回まで")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    obs = load_obs(a.obs); SG, PR = sigmets(obs), pireps(obs); UK = load_ukmo(a.obs)
    now = obs[-1][0] if obs else dt.datetime.utcnow()
    print(f"# 事後検証(観測の記録 {len(obs)} 時間分、{obs[0][0]:%d日%HZ}〜{now:%d日%HZ})" if obs else "# 事後検証(観測の記録がありません)")
    res = []
    for f in sorted(glob.glob(os.path.join(a.hist, "*.json")), reverse=True):
        h = json.load(open(f, encoding="utf-8")); b = h.get("base")
        if not b or b == a.base or (now - T(b)).total_seconds() > a.hours * 3600: continue
        cl = [c for c in h.get("claims") or [] if isinstance(c, dict) and c.get("box") and c.get("from") and c.get("to")]
        print(f"\n## 初期 {b} の回(claims {len(cl)})")
        r = {"base": b, "claims": [], "unforecast": []}
        for c in cl:
            if T(c["from"]) > now: print(f"- {c.get('id')} {c.get('kind')}: まだ先({c['from']}〜)"); continue
            v, info = judge(c, obs, SG, PR, UK)
            print(f"- {c.get('id')} {c.get('kind')} 「{c.get('text', '')[:80]}」 {c['from'][8:13]}〜{c['to'][8:13]} → **{v}**")
            for x in info: print(f"    - {x}")
            r["claims"].append({"id": c.get("id"), "kind": c.get("kind"), "verdict": v, "info": info})
        u = unforecast(cl, obs, SG, PR, T(b), min(now, T(b) + dt.timedelta(hours=24)), UK)
        if u:
            print("- 予想に無かった事:"); [print(f"    - {x}") for x in u[:30]]
        r["unforecast"] = u; res.append(r)
    if not res: print("\n確かめられる前の回がありません(nwp_ai/history に claims のある回が無い)")
    if a.json: json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
