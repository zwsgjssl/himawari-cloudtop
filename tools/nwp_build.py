#!/usr/bin/env python3
# v194 気象庁の数値予報天気図(PDF)を画像(PNG)にして Cloudflare の KV に置く(公開リポジトリの GitHub Actions)。
#   ユーザー「ここらへんの図は重ねなくていいかも!個別にみたい!それぞれ、解析のポイントをポップアップで見れると助かる」
#   「(ポイントは決まったガイド)に加えて(その回の図の解説)も claude api 使ってできたりする!?」
#
# 図: https://www.jma.go.jp/bosai/numericmap/data/nwpmap/<名前>_00.pdf・_12.pdf(00UTC・12UTC の回。同じ名前で上書きされる)
#   AUPQ35(300・500hPa 解析)・AUPQ78(700・850hPa 解析)・AUPA20(圏界面・200hPa ジェット)・AUPA25(250hPa)
#   FUPA252・FUPA302・FUPA502(250・300・500hPa 24 時間予想)・FXJP854(850hPa 相当温位・風 12〜48 時間予想)
#   _00 と _12 のうち更新(Last-Modified)が新しい方を使う。回(初期時刻)は Last-Modified の前の 00/12UTC
#
# 出力(KV): nwp:latest = [見出しの長さ 4 バイト(ビッグエンディアン)][見出し JSON][PNG を並べたもの]
#   見出し = { charts:[{ id, title, lm(気象庁の Last-Modified), base(初期時刻 ISO), valid(説明), w, h, bytes }], parts:{ id:[位置, 長さ] },
#             ai:{ base, model, at, summary, charts:{ id:解説 } }(ANTHROPIC_API_KEY があるときだけ)、src, attribution }
#   1 回の実行で書くのは多くて 1 回(どれかの図が新しくなったときだけ)。KV の無料枠(書き込み 1 日 1,000 回)をほとんど使わない
#   AI の解説は、全部の図の初期時刻がそろったときに、その回について 1 回だけ作る(同じ回で作り直さない = API の料金を抑える)
#
# v195 ユーザー「claude に絶対の信頼を置いてる」「チャットに自動で送って解析してもらうとか」→ Claude のスケジュール実行(定時のタスク)が解説を書く:
#   (1) このスクリプトが図を nwp_img/(<id>.png と charts.json)にも出し、Actions がブランチ nwp-img に置く(最新 1 回分だけ。履歴は増やさない)
#   (2) Claude のスケジュール実行が 1 日 2 回 nwp-img の図を読み、main の nwp_ai/ai.json に解説を書く(高層天気図ごとの解析 + 全体の総括)
#   (3) 次の実行でこのスクリプトが nwp_ai/ai.json を読み、図と同じ回の解説なら KV の見出しの ai に入れる
#   ANTHROPIC_API_KEY があるときの Claude API の道も残す(ai.json が無い・古いときだけ使う)
# v201 ユーザー「どうせだから(地上の)ASAS と FSAS もいれて総合的に解析しよう。全国航空気象解説報や FBJP を答え合わせに使うのはどう?」
#   (1) 地上天気図: 気象庁 bosai の天気図(日本周辺・白黒。Map が地図に重ねているのと同じ物)の最新の実況(SPAS)・24 時間予想(FSAS24)・48 時間予想(FSAS48)を
#       charts に足す(grp "sfc"。高層の図は grp "upper")。初期時刻は図ごと(高層の図とそろわなくてよい。AI の解説を待つ判定は高層の図だけで)
#   (2) 答え合わせの資料: FBJP(国内悪天予想図)と全国航空気象解説報(国内空域 qyya82・福岡FIR qyya83)を nwp_img/ref_<id>.png に(KV には置かない)。
#       スケジュール実行は先に図だけで解析し、そのあとこれと照らし合わせて ai.json の check に書く
#   (3) 図や資料が変わったかは、前の nwp-img の charts.json(--prev)と比べる
# 環境変数: CF_API_TOKEN・CF_ACCOUNT_ID・CF_KV_WX_ID(himawari と同じ)、ANTHROPIC_API_KEY(任意)・ANTHROPIC_MODEL(任意、既定 claude-sonnet-5-5)
#   試験用: NWP_BASE(図の置き場所の代わり)、ANTHROPIC_BASE、--dry-run フォルダ
import argparse, base64, datetime as dt, email.utils, io, json, os, subprocess, sys, tempfile, time
import requests

BASE = os.environ.get("NWP_BASE", "https://www.jma.go.jp/bosai/numericmap/data/nwpmap/").rstrip("/") + "/"
UA = {"User-Agent": "approach-planner-wx/1.0 (personal, non-commercial)"}
LATEST = "nwp:latest"
WM_BASE = os.environ.get("WM_BASE", "https://www.jma.go.jp/bosai/weather_map/data/").rstrip("/") + "/"
AIR_BASE = os.environ.get("AIRINFO_BASE", "https://www.data.jma.go.jp/airinfo/data/pict/").rstrip("/") + "/"
# 地上天気図(list.json の near_monochrome の now・ft24・ft48)
# v202 ユーザー「48 時間先まで見なくていいよ!」→ FSAS48 はやめた
SFC = [("spas", "now", "SPAS 地上 実況(日本周辺)", 0), ("fsas24", "ft24", "FSAS24 地上 24時間予想", 24)]
# v202 ユーザー「FXJP も入れようか」→ 国内航空路 6・12 時間予想断面図(airinfo の fxjp106_<初期時刻>.png。3 時間ごと、初期時刻の約 2.5 時間後に出る)。
#   8 つの初期時刻のうち更新(Last-Modified)が一番新しい物。色付きの図なのでそのまま(灰色にしない)
XS_HOURS = ("00", "03", "06", "09", "12", "15", "18", "21")
# 答え合わせの資料(気象庁の予報官が作った物)
REFS = [("fbjp", "fbjp/fbjp.png", "FBJP 国内悪天予想図"), ("cmnt_air", "ajpn_cmnt/qyya82.png", "全国航空気象解説報(国内空域)"),
        ("cmnt_fir", "ajpn_cmnt/qyya83.png", "全国航空気象解説報(福岡FIR)")]
DPI = 130   # PDF(約 845×726pt)→ 約 1525×1310px。文字が読めて、1 枚 数百 KB
# (id, ファイルの名前, 表題, 予想の時間(解析は 0。FXJP854 は 12〜48 の 4 枚))
CHARTS = [
    ("aupq35", "aupq35", "AUPQ35 300・500hPa 解析", 0),
    ("aupq78", "aupq78", "AUPQ78 700・850hPa 解析", 0),
    ("aupa20", "aupa20", "AUPA20 圏界面・200hPa ジェット 解析", 0),
    ("aupa25", "aupa25", "AUPA25 250hPa 解析", 0),
    # v223 ユーザー「aupn30 いらないね」→ AUPQ35 上段(300hPa)と被るので外した
    ("fupa252", "fupa252", "FUPA252 250hPa 24時間予想", 24),
    ("fupa302", "fupa302", "FUPA302 300hPa 24時間予想", 24),
    ("fupa502", "fupa502", "FUPA502 500hPa 24時間予想", 24),
    ("fxjp854", "fxjp854", "FXJP854 850hPa 相当温位・風 12〜48時間予想", -1),
    # v203 ユーザー「AXJP も追加」→ 高層断面図の解析(東経 130 度・140 度)。2 枚を縦につないで 1 枚に(社内の表示「AXJP130/140」と同じ)
    ("axjp", ("axjp130", "axjp140"), "AXJP130/140 高層断面図 解析(130°E・140°E)", 0),
]
# v203 ユーザー「社内のシステムの表示順が ASAS FSAS AUPQ78 AUPQ35 AUPN30 AUPA25 AUPA20 FUPA502 FUPA302 FUPA252 AXJP130/140 FXJP106/112 だから、その順番で」
#   (FXJP854 は社内の一覧に無いので最後)
ORDER = ["spas", "fsas24", "aupq78", "aupq35", "aupa25", "aupa20", "fupa502", "fupa302", "fupa252", "axjp", "fxjp106", "fxjp854"]

def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)

class KV:
    """Cloudflare の KV(WX)。--dry-run ならフォルダに書く"""
    def __init__(self, dry=None):
        self.dry = dry
        if dry: os.makedirs(dry, exist_ok=True); return
        acc, ns, tok = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_KV_WX_ID"), os.environ.get("CF_API_TOKEN")
        if not (acc and ns and tok): raise SystemExit("CF_ACCOUNT_ID / CF_KV_WX_ID / CF_API_TOKEN が未設定です(GitHub の Secrets に登録)")
        base = os.environ.get("CF_API_BASE", "https://api.cloudflare.com/client/v4").rstrip("/")
        self.url = f"{base}/accounts/{acc}/storage/kv/namespaces/{ns}/values/"
        self.h = {**UA, "Authorization": "Bearer " + tok}
    def _f(self, key): return os.path.join(self.dry, key.replace("/", "__"))
    def get(self, key):
        if self.dry: return open(self._f(key), "rb").read() if os.path.exists(self._f(key)) else None
        r = requests.get(self.url + requests.utils.quote(key, safe=""), headers=self.h, timeout=60)
        if r.status_code == 404: return None
        r.raise_for_status(); return r.content
    def put(self, key, data):
        if self.dry: open(self._f(key), "wb").write(data); return
        for attempt in range(4):
            r = requests.put(self.url + requests.utils.quote(key, safe=""), headers={**self.h, "Content-Type": "application/octet-stream"}, data=data, timeout=300)
            if r.ok: return
            if attempt == 3: raise RuntimeError(f"KV に書けません({key}): HTTP {r.status_code} {r.text[:300]}")
            time.sleep(3 + attempt * 5)

def pack(head, parts):
    offs, body = {}, bytearray()
    for n, b in parts.items(): offs[n] = [len(body), len(b)]; body += b
    hj = json.dumps(dict(head, parts=offs), ensure_ascii=False).encode("utf-8")
    return len(hj).to_bytes(4, "big") + hj + bytes(body)

def unpack(blob):
    n = int.from_bytes(blob[:4], "big"); head = json.loads(blob[4:4 + n].decode("utf-8")); body = blob[4 + n:]
    parts = {k: body[o:o + l] for k, (o, l) in head.pop("parts", {}).items()}
    return head, parts

def lm_of(name):
    """_00・_12 の Last-Modified を調べて新しい方 (url, lm 文字列, datetime, 回 "00"/"12")。無ければ None"""
    best = None
    for run in ("00", "12"):
        url = f"{BASE}{name}_{run}.pdf"
        try: r = requests.head(url, headers=UA, timeout=30, allow_redirects=True)
        except requests.RequestException as e: log(f"  {name}_{run}: {e}"); continue
        lm = r.headers.get("Last-Modified")
        if not r.ok or not lm: log(f"  {name}_{run}: HTTP {r.status_code}"); continue
        t = email.utils.parsedate_to_datetime(lm).astimezone(dt.timezone.utc).replace(tzinfo=None)
        if not best or t > best[2]: best = (url, lm, t, run)
    return best

def base_of(t, run):
    """更新時刻 t と回("00"/"12")→ 初期時刻(t より前の、その時の 00 か 12UTC)"""
    b = t.replace(hour=int(run), minute=0, second=0, microsecond=0)
    if b > t: b -= dt.timedelta(days=1)
    return b

def gray4(im):
    """グレーの画像 → 16 段階の灰色の PNG(4 ビット)"""
    q = im.point(lambda v: round(v / 255 * 15) * 17).quantize(colors=16, method=2)
    bio = io.BytesIO(); q.save(bio, "PNG", optimize=True, bits=4)
    return bio.getvalue()

def sfc_charts(have):
    """地上天気図の最新(実況・24h・48h)。[(chart, png か None)]。png が None = 前のまま"""
    import re
    from PIL import Image
    try:
        r = requests.get(WM_BASE + "list.json", headers=UA, timeout=30); r.raise_for_status(); L = r.json().get("near_monochrome") or {}
    except Exception as e: log(f"地上天気図の一覧: {e}"); return [(have[c[0]], None) for c in SFC if c[0] in have]
    out = []
    for cid, key, title, fh in SFC:
        names = [n for n in (L.get(key) or []) if re.match(r"^\d{14}_0_Z__C_010000_\d{14}_MET_CHT_JCI(spas|fsas24|fsas48)_[A-Za-z0-9_]+\.png$", n)]
        if not names:
            if cid in have: out.append((have[cid], None))
            continue
        name = max(names, key=lambda n: (n.split("_")[6], n[:14]))   # 初期(解析)時刻が新しい物。同じなら後に出た物
        if cid in have and have[cid].get("lm") == name: out.append((have[cid], None)); continue
        png = None
        for d in ("png/", ""):
            try:
                g = requests.get(WM_BASE + d + name, headers=UA, timeout=60)
                if g.ok: png = g.content; break
            except requests.RequestException as e: log(f"{cid}: {e}")
        if not png:
            log(f"{cid}: 取れませんでした {name}")
            if cid in have: out.append((have[cid], None))
            continue
        im = Image.open(io.BytesIO(png)).convert("L"); b = gray4(im)
        base = dt.datetime.strptime(name.split("_")[6], "%Y%m%d%H%M%S")
        f = lambda x: x.strftime("%d日%H") + "Z"
        valid = f"{f(base)} 実況" if fh == 0 else f"{f(base + dt.timedelta(hours=fh))} 予想(初期 {f(base)})"
        c = {"id": cid, "grp": "sfc", "title": title, "lm": name, "base": base.strftime("%Y-%m-%dT%H:%MZ"), "valid": valid, "w": im.width, "h": im.height, "bytes": len(b)}
        log(f"{cid}: {name} → {im.width}×{im.height} {len(b)/1e3:.0f}KB({valid})")
        out.append((c, b))
    return out

def xs_chart(have):
    """国内航空路の断面図(FXJP106)の最新。(chart, png か None) か None"""
    best = None
    for hh in XS_HOURS:
        url = f"{AIR_BASE}nwp/fxjp106_{hh}.png"
        try: r = requests.head(url, headers=UA, timeout=30, allow_redirects=True)
        except requests.RequestException as e: log(f"  fxjp106_{hh}: {e}"); continue
        lm = r.headers.get("Last-Modified")
        if not r.ok or not lm: continue
        t = email.utils.parsedate_to_datetime(lm).astimezone(dt.timezone.utc).replace(tzinfo=None)
        if not best or t > best[2]: best = (url, lm, t, hh)
    if not best: log("fxjp106: 見つかりません"); return (have["fxjp106"], None) if "fxjp106" in have else None
    url, lm, t, hh = best
    if "fxjp106" in have and have["fxjp106"].get("lm") == lm: return have["fxjp106"], None
    try:
        r = requests.get(url, headers=UA, timeout=60); r.raise_for_status()
        if not r.content.startswith(b"\x89PNG"): raise ValueError("PNG ではありません")
    except Exception as e:
        log(f"fxjp106: 取れませんでした {e}"); return (have["fxjp106"], None) if "fxjp106" in have else None
    from PIL import Image
    im = Image.open(io.BytesIO(r.content))
    base = base_of(t, hh); f = lambda x: x.strftime("%d日%H") + "Z"
    c = {"id": "fxjp106", "grp": "xs", "title": "FXJP106 国内航空路 6・12時間予想断面図", "lm": lm, "base": base.strftime("%Y-%m-%dT%H:%MZ"),
         "valid": f"初期 {f(base)}(+6h {f(base + dt.timedelta(hours=6))}・+12h {f(base + dt.timedelta(hours=12))})", "w": im.width, "h": im.height, "bytes": len(r.content)}
    log(f"fxjp106: {lm} → {im.width}×{im.height} {len(r.content)/1e3:.0f}KB({c['valid']})")
    return c, r.content

def get_refs():
    """答え合わせの資料。[(ref, png)](取れなかった物は入れない)"""
    out = []
    for rid, path, title in REFS:
        try:
            r = requests.get(AIR_BASE + path, headers=UA, timeout=60); r.raise_for_status()
            if not r.content.startswith(b"\x89PNG"): raise ValueError("PNG ではありません")
        except Exception as e: log(f"{rid}: 取れませんでした {e}"); continue
        lm = r.headers.get("Last-Modified") or ""
        t = email.utils.parsedate_to_datetime(lm).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ") if lm else ""
        out.append(({"id": rid, "title": title, "lm": lm, "at": t, "file": f"ref_{rid}.png", "src": AIR_BASE + path, "bytes": len(r.content)}, r.content))
        log(f"{rid}: {lm} {len(r.content)/1e3:.0f}KB")
    return out

def render(pdf_bytes):
    """PDF → グレーの PNG(pdftoppm)。(png, 幅, 高さ)"""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "a.pdf"); open(p, "wb").write(pdf_bytes)
        subprocess.run(["pdftoppm", "-r", str(DPI), "-gray", "-png", "-singlefile", p, os.path.join(tmp, "o")], check=True)
        from PIL import Image
        im = Image.open(os.path.join(tmp, "o.png")).convert("L")
    # 16 段階の灰色(4 ビットの PNG)にして小さく(pdftoppm のままの半分くらい。線と字はそのまま読める)
    return gray4(im), im.width, im.height

def valid_text(base, fh):
    f = lambda x: x.strftime("%d日%H") + "Z"
    if fh == 0: return f"{f(base)} 解析"
    if fh < 0: return f"初期 {f(base)}(+12〜+48h: {f(base + dt.timedelta(hours=12))}〜{f(base + dt.timedelta(hours=48))})"
    return f"{f(base + dt.timedelta(hours=fh))} 予想(初期 {f(base)})"

# ---- AI の解説(Claude API)----
AI_SYSTEM = """あなたは日本の国内線を飛ぶ旅客機の運航乗務員(ボーイング 787 の機長)のための航空気象の解析担当です。
渡す気象庁の数値予報天気図(高層の解析図・予想図、850hPa 相当温位)を読み、運航(巡航・上昇降下・出発到着)に役立つ要点を日本語で簡潔にまとめてください。
- 図から読み取れることだけを書き、読み取れないことは書かない。推測は「〜の可能性」と書く。
- 見るべき点: ジェット気流の位置・強さ(kt)・高度、等風速線の混み(CAT)、気圧の谷・寒冷渦・寒気(500hPa の気温)、圏界面の高さの変化、下層の湿り(湿数)と着氷の高さ、850hPa の相当温位の集中帯(前線)・暖湿気の流入、24 時間後の変化。
- 日本付近(特に本州・九州・北海道・沖縄の航空路)に関係することを優先する。
- 高度は FL で(850hPa≈FL050、700≈FL100、500≈FL180、300≈FL300、250≈FL340、200≈FL390)。
出力は次の JSON だけ(前後に何も付けない): {"summary": "全体の要点(3〜5 行、・で始まる箇条書き)", "charts": {"<図の id>": "その図の要点(2〜4 行、・で始まる箇条書き)", ...}}"""

def ai_explain(items):
    """items = [(id, title, png)]。{summary, charts} か None"""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: log("ANTHROPIC_API_KEY が無いので AI の解説は作りません"); return None
    model = os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5-5"   # Variables が空でも既定
    from PIL import Image
    content = []
    for cid, title, png in items:
        im = Image.open(io.BytesIO(png)).convert("L"); s = 1568 / max(im.size)
        if s < 1: im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        bio = io.BytesIO(); im.save(bio, "PNG", optimize=True)
        content.append({"type": "text", "text": f"図の id: {cid}({title})"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(bio.getvalue()).decode()}})
    content.append({"type": "text", "text": "上の図を読んで、指定の JSON で答えてください。charts のキーは図の id: " + ", ".join(i[0] for i in items)})
    url = os.environ.get("ANTHROPIC_BASE", "https://api.anthropic.com").rstrip("/") + "/v1/messages"
    r = requests.post(url, headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json={"model": model, "max_tokens": 4000, "system": AI_SYSTEM, "messages": [{"role": "user", "content": content}]}, timeout=300)
    if not r.ok: log(f"AI の解説: HTTP {r.status_code} {r.text[:300]}"); return None
    j = r.json(); txt = "".join(c.get("text", "") for c in j.get("content", []) if c.get("type") == "text").strip()
    if txt.startswith("```"): txt = txt.strip("`").split("\n", 1)[1] if "\n" in txt else txt
    try:
        a = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
    except Exception as e: log(f"AI の解説を読めません: {e} {txt[:300]}"); return None
    u = j.get("usage", {}); log(f"AI の解説 できました({model}、入力 {u.get('input_tokens')}・出力 {u.get('output_tokens')} トークン)")
    return {"model": model, "summary": str(a.get("summary", "")), "charts": {k: str(v) for k, v in (a.get("charts") or {}).items()}}

AI_FILE = "nwp_ai/ai.json"
def ai_from_file(base):
    """スケジュール実行が書いた解説(その回の物だけ)。無ければ None"""
    if not os.path.exists(AI_FILE): return None
    try: a = json.load(open(AI_FILE, encoding="utf-8"))
    except Exception as e: log(f"{AI_FILE} を読めません: {e}"); return None
    if a.get("base") != base: log(f"{AI_FILE} は別の回({a.get('base')})の解説です"); return None
    if not isinstance(a.get("charts"), dict) or not a.get("summary"): log(f"{AI_FILE} の形が違います"); return None
    out = {"base": base, "model": str(a.get("model") or "Claude(定時の解析)"), "at": str(a.get("at") or ""), "summary": str(a["summary"]),
           "charts": {k: str(v) for k, v in a["charts"].items()}}
    # v201 答え合わせ(FBJP・全国航空気象解説報との照合)と、解析に使った図の版(図ごとの lm。Map が印と図を結び付ける)
    if a.get("check"): out["check"] = str(a["check"])
    if isinstance(a.get("lm"), dict): out["lm"] = {str(k): str(v) for k, v in a["lm"].items()}
    if isinstance(a.get("refs"), list): out["refs"] = [str(x)[:80] for x in a["refs"][:6]]
    # v196 図に塗る印(解説の ①② と同じ番号)。形を確かめて、おかしい物は捨てる
    KINDS = {"front", "jet", "cat", "trough", "cold", "warm", "moist", "icing", "cb", "low", "high", "other"}
    def num(v): return float(v) if isinstance(v, (int, float)) and abs(v) < 1e5 else None
    marks = {}
    for cid, lst in (a.get("marks") or {}).items():
        if cid not in out["charts"] or not isinstance(lst, list): continue
        ok = []
        for m in lst[:12]:
            if not isinstance(m, dict): continue
            sh, kind = m.get("shape"), m.get("kind") if m.get("kind") in KINDS else "other"
            q = {"n": int(m["n"]) if isinstance(m.get("n"), int) else len(ok) + 1, "kind": kind, "label": str(m.get("label") or "")[:24], "shape": sh}
            if sh == "ellipse":
                v = [num(m.get(k)) for k in ("cx", "cy", "rx", "ry")]
                if None in v: continue
                q.update(cx=v[0], cy=v[1], rx=v[2], ry=v[3], rot=num(m.get("rot")) or 0)
            elif sh in ("poly", "line"):
                pts = [[num(p[0]), num(p[1])] for p in (m.get("pts") or []) if isinstance(p, list) and len(p) == 2]
                if len(pts) < 2 or any(None in p for p in pts): continue
                q["pts"] = pts[:60]
            else: continue
            ok.append(q)
        if ok: marks[cid] = ok
    if marks: out["marks"] = marks
    return out

def write_img_dir(d, charts, parts, refs=()):
    """スケジュール実行が読む用に、図(PNG)・答え合わせの資料(ref_<id>.png)と一覧(charts.json)をフォルダに"""
    os.makedirs(d, exist_ok=True)
    for c in charts: open(os.path.join(d, c["id"] + ".png"), "wb").write(parts[c["id"]])
    for r, b in refs: open(os.path.join(d, r["file"]), "wb").write(b)
    json.dump({"charts": charts, "refs": [r for r, _ in refs], "made": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")},
              open(os.path.join(d, "charts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"{d}/ に図 {len(charts)} 枚・資料 {len(refs)} 枚と charts.json を出しました")

# v206 事後検証(ユーザー「1 いいね!」): 予想図(と解析図)の前の回を nwp_img/hist/<初期時刻>/<id>.png に 36 時間分残す。
#   Claude の定時の解析が、前の回の予想図と今の解析図を比べられるように(例: 24 時間前の FUPA502 と今の AUPQ35 下段)
HIST_H = 36
def keep_hist(d, prev_dir, charts):
    import shutil
    if not prev_dir or not os.path.isdir(prev_dir): return
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None); hd = os.path.join(d, "hist"); n = 0
    ok = lambda b: (now - dt.datetime.strptime(b, "%Y%m%dT%H%MZ")).total_seconds() <= HIST_H * 3600
    ph = os.path.join(prev_dir, "hist")
    if os.path.isdir(ph):   # 前の履歴(36 時間以内)
        for b in os.listdir(ph):
            try:
                if not ok(b): continue
            except ValueError: continue
            for fn in os.listdir(os.path.join(ph, b)):
                os.makedirs(os.path.join(hd, b), exist_ok=True); shutil.copyfile(os.path.join(ph, b, fn), os.path.join(hd, b, fn)); n += 1
    try: pc = json.load(open(os.path.join(prev_dir, "charts.json"), encoding="utf-8")).get("charts", [])
    except Exception: pc = []
    now_lm = {c["id"]: c.get("lm") for c in charts}
    for c in pc:   # 前の nwp-img の図のうち、今は新しくなった物
        src = os.path.join(prev_dir, c["id"] + ".png")
        if now_lm.get(c["id"]) == c.get("lm") or not os.path.exists(src): continue
        b = c["base"].replace("-", "").replace(":", "")
        try:
            if not ok(b): continue
        except ValueError: continue
        os.makedirs(os.path.join(hd, b), exist_ok=True); shutil.copyfile(src, os.path.join(hd, b, c["id"] + ".png")); n += 1
    if n: log(f"{hd}/ に前の回の図 {n} 枚")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img-dir", default="", help="図をこのフォルダにも出す(スケジュール実行が読む用。新しい図があったときだけ)")
    ap.add_argument("--img-always", action="store_true", help="新しい図が無くても --img-dir に出す(ブランチ nwp-img がまだ無いとき)")
    ap.add_argument("--dry-run", default="", help="KV に書かず、このフォルダに出す(試験用)")
    ap.add_argument("--force-ai", action="store_true", help="同じ回でも AI の解説を作り直す")
    ap.add_argument("--prev", default="", help="前の nwp-img の charts.json(図・資料が変わったかを比べる)")
    ap.add_argument("--prev-dir", default="", help="前の nwp-img の中身(前の回の図を hist/ に残す)")
    a = ap.parse_args()
    kv = KV(a.dry_run or None)
    old = kv.get(LATEST); head, parts_all = unpack(old) if old else ({}, {})
    # v209 ユーザー「新しいのが解析完了するまでは古いのを表示でいいや」→ KV の charts(Map が見る物)は Claude が解析した版の図のまま出し、
    #   新しく来た図は head["cur"](一番新しい図の一覧)と parts の "cur:<id>" に持っておく。解析(ai.lm)が追いついたら新しい図を出す(下の hold)
    pub = {c["id"]: c for c in head.get("charts", []) if c["id"] in parts_all}
    cur = {c["id"]: c for c in head.get("cur", head.get("charts", []))}
    parts = {}
    for k, c in cur.items():
        b = parts_all.get("cur:" + k) or (parts_all.get(k) if pub.get(k, {}).get("lm") == c.get("lm") else None)
        if b is not None: parts[k] = b
    have = {k: c for k, c in cur.items() if k in parts}
    charts, changed = [], False
    # v201 地上天気図(先に並べる)
    for c, b in sfc_charts(have):
        charts.append(c)
        if b is not None: parts[c["id"]] = b; changed = True
    # v202 国内航空路の断面図
    x = xs_chart(have)
    if x:
        charts.append(x[0])
        if x[1] is not None: parts["fxjp106"] = x[1]; changed = True
    for cid, name, title, fh in CHARTS:
        names = list(name) if isinstance(name, tuple) else [name]
        fs = [x for x in (lm_of(n) for n in names) if x]
        if not fs:
            if cid in have: charts.append(have[cid])
            continue
        f = max(fs, key=lambda x: x[2])   # 回は一番新しい物で
        url, lm, t, run = f
        lm = " | ".join(x[1] for x in fs) if len(names) > 1 else lm
        if cid in have and have[cid].get("lm") == lm: charts.append(have[cid]); continue
        try:
            if len(names) == 1:
                r = requests.get(url, headers=UA, timeout=120); r.raise_for_status()
                png, w, h = render(r.content)
            else:   # v203 何枚かを縦につなぐ(AXJP130・140)
                from PIL import Image
                ims = []
                for x in fs:
                    r = requests.get(x[0], headers=UA, timeout=120); r.raise_for_status()
                    ims.append(Image.open(io.BytesIO(render(r.content)[0])).convert("L"))
                w = max(i.width for i in ims); h = sum(i.height for i in ims)
                cv = Image.new("L", (w, h), 255); y = 0
                for i in ims: cv.paste(i, ((w - i.width) // 2, y)); y += i.height
                png = gray4(cv)
        except Exception as e:
            log(f"{cid}: 取れませんでした {e}")
            if cid in have: charts.append(have[cid])
            continue
        base = base_of(t, run)
        parts[cid] = png; changed = True
        charts.append({"id": cid, "grp": "upper", "title": title, "lm": lm, "base": base.strftime("%Y-%m-%dT%H:%MZ"), "valid": valid_text(base, fh), "w": w, "h": h, "bytes": len(png)})
        log(f"{cid}: {lm} → {w}×{h} {len(png)/1e3:.0f}KB({charts[-1]['valid']})")
    charts.sort(key=lambda c: ORDER.index(c["id"]) if c["id"] in ORDER else len(ORDER))   # v203 社内の表示順
    for k in list(parts):
        if not any(c["id"] == k for c in charts): parts.pop(k)
    # v201 答え合わせの資料。図か資料が前の nwp-img と違えば、フォルダに出し直す
    if a.img_dir and charts:
        refs = get_refs()
        try: prev = json.load(open(a.prev, encoding="utf-8")) if a.prev and os.path.exists(a.prev) else None
        except Exception: prev = None
        key = lambda L: sorted((x.get("id"), x.get("lm")) for x in (L or []))
        moved = prev is None or key(prev.get("charts")) != key(charts) or key(prev.get("refs")) != key([r for r, _ in refs])
        if changed or a.img_always or moved: write_img_dir(a.img_dir, charts, parts, refs); keep_hist(a.img_dir, a.prev_dir, charts)
    # AI の解説: 高層の図(grp upper)の初期時刻が全部同じとき。(1) スケジュール実行が書いた nwp_ai/ai.json(その回の物で、まだ取り込んでいなければ)(2) 無ければ Claude API(キーがあれば・回ごとに 1 回)
    ai = head.get("ai")
    bases = {c["base"] for c in charts if c.get("grp", "upper") == "upper"}   # v201 地上天気図は別の時刻でよい
    fa = ai_from_file(next(iter(bases))) if charts and len(bases) == 1 else None
    # v211 解説・印だけを手で直したとき(at が同じ)も取り込む: 中身のどこかが違えば取り込む(前は base・at・summary・check・lm だけを比べていて、charts・marks の直しが KV に入らなかった)
    if fa and (not ai or any(ai.get(k) != fa.get(k) for k in ("base", "at", "summary", "check", "lm", "charts", "marks", "refs", "model"))):
        ai = fa; changed = True; log(f"解説を取り込みました({AI_FILE}、{fa['base']}、{fa['model']})")
    elif fa: pass
    elif charts and len(bases) == 1 and os.environ.get("ANTHROPIC_API_KEY") and (a.force_ai or not ai or ai.get("base") != next(iter(bases))):
        try: x = ai_explain([(c["id"], c["title"], parts[c["id"]]) for c in charts if c.get("grp", "upper") == "upper"])
        except Exception as e: log(f"AI の解説: {e}"); x = None
        if x: ai = {**x, "base": next(iter(bases)), "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}; changed = True
    elif len(bases) > 1: log("図の初期時刻がそろっていないので、AI の解説は待ちます: " + ", ".join(sorted(bases)))
    # v209 出す図: 解説(ai.lm)がこの図の前の版を見て書かれていて、その版を今出しているなら、解析が追いつくまでその版のまま(newer = 新しい図の時刻)
    lm_ai = (ai or {}).get("lm") or {}
    out_c, out_p = [], {}
    for c in charts:
        want, p = lm_ai.get(c["id"]), pub.get(c["id"])
        if want and want != c.get("lm") and p and p.get("lm") == want:
            out_c.append(dict(p, newer=c.get("valid") or c.get("base") or "")); out_p[c["id"]] = parts_all[c["id"]]; out_p["cur:" + c["id"]] = parts[c["id"]]
        else:
            out_c.append(c); out_p[c["id"]] = parts[c["id"]]
    held = [c["id"] for c in out_c if c.get("newer")]
    if held: log("解析が追いつくまで前の図を出す: " + ", ".join(held))
    if not changed and [(c["id"], c.get("lm")) for c in out_c] == [(c["id"], c.get("lm")) for c in head.get("charts", [])]:
        log("新しい図はありません。何もしません"); return
    head = {"charts": out_c, "cur": charts, "ai": ai, "src": BASE, "attribution": "気象庁 数値予報天気図・地上天気図"}
    blob = pack(head, out_p)
    kv.put(LATEST, blob)
    log(f"KV {LATEST} に書きました({len(blob)/1e6:.2f}MB、{len(charts)} 図" + (f"、AI の解説 {ai['base']}" if ai else "") + ")")

if __name__ == "__main__":
    main()
