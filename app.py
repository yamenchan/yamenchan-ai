import os, math, re, requests
from flask import Flask, request, render_template_string

app = Flask(__name__)
API_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"

THEMES = {
    "家事": ["家事 便利グッズ", "掃除 便利グッズ", "キッチン 時短 便利"],
    "収納": ["収納 便利グッズ", "収納 アイデア", "省スペース 収納"],
    "子育て": ["育児 便利グッズ", "子供 便利グッズ", "ベビー 便利グッズ"],
    "季節": ["季節 便利グッズ", "秋 便利グッズ", "冬 便利グッズ"],
    "便利グッズ": ["暮らし 便利グッズ", "時短 便利グッズ", "アイデア商品 便利"],
}
POSITIVE = ["収納","ラック","ケース","ホルダー","スタンド","掃除","キッチン","洗濯","時短",
            "便利","省スペース","整理","ボックス","フック","ワゴン","マット","ベビー","キッズ",
            "子供","育児","水切り","ゴミ","ブラシ","ハンガー","タオル","シート","カバー"]
NEGATIVE = ["アロマ","精油","香水","サプリ","コスメ","化粧","食品","お菓子","肉","魚","米",
            "酒","ワイン","ビール","ジュエリー","ピアス","ネックレス"]

def env(n): return os.environ.get(n, "").strip()
def clamp(v,a,b): return max(a,min(b,v))

def relevance(name, keyword):
    text=(name or "").lower()
    query_terms=[x for x in re.split(r"\s+",keyword.lower()) if x]
    q=sum(7 for t in query_terms if t in text)
    p=sum(3 for t in POSITIVE if t in text)
    n=sum(12 for t in NEGATIVE if t in text)
    return q+p-n

def score(item, keyword):
    rc=int(item.get("reviewCount") or 0)
    ra=float(item.get("reviewAverage") or 0)
    ar=float(item.get("affiliateRate") or 0)
    price=int(item.get("itemPrice") or 0)
    rel=relevance(item.get("itemName",""), keyword)
    review=clamp(math.log10(rc+1)/4*32,0,32)
    rating=clamp((ra-3.5)/1.5*23,0,23)
    aff=clamp(ar/10*12,0,12)
    price_pts=13 if 1000<=price<=8000 else (9 if 500<=price<=15000 else 4)
    rel_pts=clamp(rel,0,20)
    return round(review+rating+aff+price_pts+rel_pts,1)

def normalize_items(data):
    rows=data.get("items")
    if rows is None: rows=data.get("Items",[])
    out=[]
    if isinstance(rows,list):
        for r in rows:
            if isinstance(r,dict) and isinstance(r.get("Item"),dict): out.append(r["Item"])
            elif isinstance(r,dict) and isinstance(r.get("item"),dict): out.append(r["item"])
            elif isinstance(r,dict): out.append(r)
    return out

def search_api(keyword, hits=20):
    aid, key, aff = env("RAKUTEN_APPLICATION_ID"), env("RAKUTEN_ACCESS_KEY"), env("RAKUTEN_AFFILIATE_ID")
    if not aid or not key: raise RuntimeError("楽天API環境変数が不足しています。")
    params={"applicationId":aid,"accessKey":key,"keyword":keyword,"format":"json","formatVersion":2,
            "hits":hits,"sort":"-reviewCount","availability":1,"imageFlag":1,"carrier":2,"field":0}
    if aff: params["affiliateId"]=aff
    r=requests.get(API_URL,params=params,timeout=20)
    try: data=r.json()
    except Exception: raise RuntimeError(f"楽天API HTTP {r.status_code}: JSON応答ではありません")
    if r.status_code!=200:
        raise RuntimeError(f"楽天API HTTP {r.status_code}: {data.get('error_description') or data.get('error') or '詳細不明'}")
    return normalize_items(data)

def image_url(item):
    imgs=item.get("mediumImageUrls") or []
    if imgs:
        x=imgs[0]
        return x.get("imageUrl","") if isinstance(x,dict) else str(x)
    return ""

def short(s,n):
    s=re.sub(r"\s+"," ",s or "").strip()
    return s if len(s)<=n else s[:n]+"…"

def threads_drafts(item, owned, experience=""):
    name=short(item.get("itemName","この商品"),32)
    if owned and experience.strip():
        exp=experience.strip()
        return [
            f"これ、もっと早く使えばよかった😂\n\n{name}\n{exp}\n\nこういう『ちょっとラクになるもの』、みんな何使ってる？🐾",
            f"毎回ちょっと面倒だったことが、これでラクになった。\n\n{name}\n{exp}\n\n同じことで困ってる人いる？",
            f"こういう小さな便利グッズが一番助かるかも。\n\n{name}\n{exp}\n\nみんなの買ってよかった便利グッズも知りたい🐾"
        ]
    return [
        f"え、これ知らなかった😂\n\n{name}\n毎日のちょっとした面倒を減らせそうで気になる。\n\nこれ使ったことある人いる？🐾",
        f"これ毎回やるの、地味に面倒じゃない？\n\n{name}\nこういう方法でラクにできるならかなり気になる。\n\nみんなはどうしてる？",
        f"面倒くさいを減らせそうなもの見つけた。\n\n{name}\nこういう『ひと手間を減らす系』の便利グッズ、よさそう。\n\n似たもの使ってる人いたら感想知りたい🐾"
    ]

def room_draft(item, owned, experience=""):
    name=short(item.get("itemName","商品"),60)
    price=int(item.get("itemPrice") or 0)
    ra=float(item.get("reviewAverage") or 0); rc=int(item.get("reviewCount") or 0)
    if owned and experience.strip():
        lead=f"実際に使っているアイテム🐾\n{experience.strip()}"
    else:
        lead="暮らしの面倒をちょっと減らしてくれそうで気になったアイテム🐾"
    return f"{lead}\n\n{name}\n価格：{price:,}円 / ★{ra:.1f}（{rc:,}件）\n\n#便利グッズ #暮らしをラクに #家事ラク #楽天ROOM"

PAGE=r"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>やめんちゃん AI v2</title><style>
:root{--bg:#f6f1e8;--card:#fffdf8;--ink:#3e342d;--sub:#75675d;--line:#e5d9cc;--accent:#8a6b52}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Yu Gothic",sans-serif}
.wrap{max-width:760px;margin:auto;padding:20px 14px 70px}h1{font-size:29px;margin:8px 0 4px}.tag{color:var(--sub);margin:0 0 18px}
.panel,.card{background:var(--card);border:1px solid var(--line);border-radius:19px;padding:14px;margin:13px 0;box-shadow:0 4px 18px #00000008}
.themes{display:flex;gap:7px;overflow:auto;padding-bottom:5px}.theme{white-space:nowrap;text-decoration:none;color:var(--ink);border:1px solid var(--line);padding:9px 13px;border-radius:999px;background:white}.theme.on{background:var(--ink);color:white}
input,textarea,select,button{width:100%;font:inherit;border:1px solid var(--line);border-radius:12px;padding:11px;background:white}button{background:var(--ink);color:white;font-weight:700;border:0}
.row{display:grid;grid-template-columns:1fr auto;gap:8px}.row button{width:auto}.top{display:flex;gap:11px}.pic{width:92px;height:92px;object-fit:cover;border-radius:12px;background:#eee}.meta{flex:1;min-width:0}.name{font-weight:700;line-height:1.45}.small{font-size:13px;color:var(--sub);line-height:1.55}.score{display:inline-block;background:#efe2d3;padding:4px 8px;border-radius:999px;font-size:12px;font-weight:700;margin-bottom:4px}
details{margin-top:10px}summary{font-weight:700;cursor:pointer}.draft{white-space:pre-wrap;background:#f7f2eb;padding:11px;border-radius:11px;margin:8px 0;font-size:14px;line-height:1.6}
a.buy{display:inline-block;background:var(--accent);color:white;text-decoration:none;padding:9px 12px;border-radius:10px;font-size:13px;font-weight:700}.error{background:#fff0ef;border:1px solid #efc1bd;padding:12px;border-radius:12px}
label{font-size:13px;color:var(--sub)}.ownbox{margin-top:10px;padding-top:10px;border-top:1px solid var(--line)}
@media(max-width:520px){.pic{width:82px;height:82px}.row{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<h1>やめんちゃん AI 🐾</h1><p class="tag">面倒くさいを、ちょっとラクに。今日の投稿候補を発掘。</p>
<div class="panel"><div class="themes">
{% for t in themes %}<a class="theme {% if t==theme %}on{% endif %}" href="/?theme={{t}}">{{t}}</a>{% endfor %}
</div><form method="get" style="margin-top:10px"><input type="hidden" name="theme" value="{{theme}}">
<div class="row"><input name="q" value="{{q}}" placeholder="自由検索：例 水切り 便利"><button>検索</button></div></form>
<p class="small">テーマを選ぶと関連キーワードを複数検索して候補をまとめます。スコアは楽天の売上データではなく、関連度・レビュー・評価・価格帯・料率による独自指標です。</p></div>
{% if error %}<div class="error">{{error}}</div>{% endif %}
{% if items %}<p class="small"><b>今日の候補 TOP {{items|length}}</b>　※同一商品を整理して表示</p>{% endif %}
{% for x in items %}<div class="card"><div class="top">
{% if x.image %}<img class="pic" src="{{x.image}}" alt="">{% endif %}<div class="meta"><span class="score">候補スコア {{x.score}}/100</span>
<div class="name">{{x.itemName}}</div><div class="small">{{"{:,}".format(x.itemPrice)}}円 ・ ★{{x.reviewAverage}}（{{"{:,}".format(x.reviewCount)}}件）・ 料率{{x.affiliateRate}}%</div></div></div>
<details><summary>投稿文を作る</summary><div class="ownbox">
<form method="post"><input type="hidden" name="payload" value="{{x.idx}}">
<label>この商品は？</label><select name="owned"><option value="no">🔵 持っていない</option><option value="yes">🟢 持っている</option></select>
<label>持っている場合：実際に使って感じたこと</label><textarea name="experience" rows="3" placeholder="例：汚れてもサッと拭けて、掃除がかなりラク"></textarea>
<button style="margin-top:8px">文案を表示</button></form>
{% if selected==x.idx %}{% for d in drafts %}<div class="draft">{{d}}</div>{% endfor %}<div class="draft">{{room}}</div>{% endif %}
</div></details><div style="margin-top:10px"><a class="buy" href="{{x.url}}" target="_blank" rel="noopener">楽天で確認</a></div></div>{% endfor %}
</div></body></html>"""

def collect(theme, custom=""):
    keywords=[custom] if custom else THEMES.get(theme, THEMES["便利グッズ"])
    pool={}
    for kw in keywords:
        for item in search_api(kw,20):
            name=item.get("itemName","")
            rel=relevance(name,kw)
            if rel < 0: continue
            key=item.get("itemCode") or item.get("itemUrl") or name
            s=score(item,kw)
            if key not in pool or s>pool[key][1]: pool[key]=(item,s)
    ranked=sorted(pool.values(),key=lambda z:z[1],reverse=True)[:10]
    return ranked

@app.route("/",methods=["GET","POST"])
def home():
    theme=request.values.get("theme","便利グッズ")
    if theme not in THEMES: theme="便利グッズ"
    q=request.values.get("q","").strip()
    error=None; cards=[]; selected=-1; drafts=[]; room=""
    try:
        ranked=collect(theme,q)
        for i,(item,s) in enumerate(ranked):
            cards.append({"idx":i,"itemName":item.get("itemName",""),"itemPrice":int(item.get("itemPrice") or 0),
              "reviewAverage":float(item.get("reviewAverage") or 0),"reviewCount":int(item.get("reviewCount") or 0),
              "affiliateRate":float(item.get("affiliateRate") or 0),"image":image_url(item),"score":s,
              "url":item.get("affiliateUrl") or item.get("itemUrl") or "#","raw":item})
        if request.method=="POST":
            selected=int(request.form.get("payload","-1"))
            if 0<=selected<len(cards):
                owned=request.form.get("owned")=="yes"; exp=request.form.get("experience","")
                if owned and not exp.strip():
                    drafts=["🟢「持っている」を選んだ場合は、実際に感じたことを入力してください。架空の使用感は作りません。"]
                    room=""
                else:
                    drafts=threads_drafts(cards[selected]["raw"],owned,exp)
                    room="ROOM案\n"+room_draft(cards[selected]["raw"],owned,exp)
    except Exception as e: error=str(e)
    return render_template_string(PAGE,themes=THEMES.keys(),theme=theme,q=q,items=cards,error=error,selected=selected,drafts=drafts,room=room)

@app.route("/health")
def health(): return {"status":"ok","version":"v2"}

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
