import os, math, re, requests, json, random, time, threading
from datetime import datetime
from flask import Flask, request, render_template_string

app = Flask(__name__)
API_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
API_LOCK = threading.Lock()
LAST_API_CALL = 0.0

def rakuten_get(url, params, timeout=15):
    global LAST_API_CALL
    with API_LOCK:
        wait = 1.05 - (time.monotonic() - LAST_API_CALL)
        if wait > 0:
            time.sleep(wait)
        r = requests.get(url, params=params, timeout=timeout)
        LAST_API_CALL = time.monotonic()
        return r

HISTORY_FILE = "/tmp/yamenchan_history.json"

def load_history():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_history(rows):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(rows[-100:], f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def recent_openings():
    rows=load_history()[-10:]
    return [r.get("opening","") for r in rows if r.get("opening")]

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
    review=clamp(math.log10(rc+1)/4*30,0,30)
    rating=clamp((ra-3.5)/1.5*22,0,22)
    aff=clamp(ar/10*10,0,10)
    price_pts=13 if 1000<=price<=8000 else (9 if 500<=price<=15000 else 4)
    rel_pts=clamp(rel,0,25)
    return round(review+rating+aff+price_pts+rel_pts,1)

def badge(item, keyword):
    rc=int(item.get("reviewCount") or 0)
    ra=float(item.get("reviewAverage") or 0)
    ar=float(item.get("affiliateRate") or 0)
    rel=relevance(item.get("itemName",""), keyword)
    if ar >= 5: return "高料率"
    if rc >= 1500 and ra >= 4.4: return "定番・高評価"
    if 30 <= rc <= 700 and ra >= 4.3 and rel >= 8: return "発見候補"
    if rc >= 300 and ra >= 4.5: return "高評価"
    return "注目候補"

def display_name(name):
    s=re.sub(r"【[^】]*】|\[[^\]]*\]"," ",name or "")
    s=re.sub(r"\s+"," ",s).strip()
    return short(s,38)

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

def search_api(keyword, hits=20, sort="-reviewCount"):
    aid, key, aff = env("RAKUTEN_APPLICATION_ID"), env("RAKUTEN_ACCESS_KEY"), env("RAKUTEN_AFFILIATE_ID")
    if not aid or not key: raise RuntimeError("楽天API環境変数が不足しています。")
    params={"applicationId":aid,"accessKey":key,"keyword":keyword,"format":"json","formatVersion":2,
            "hits":hits,"sort":sort,"availability":1,"imageFlag":1,"carrier":2,"field":0}
    if aff: params["affiliateId"]=aff
    r=rakuten_get(API_URL,params=params,timeout=20)
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

def product_context(title):
    t=title.lower()
    rules=[
      (["スプレーボトル","ボトルハンガー"],"掃除スプレー収納","掃除スプレーの置き場所","浮かせて収納"),
      (["水切り","ドレイン"],"水切りアイテム","洗った物の置き場所","水まわりをすっきり"),
      (["ハンガー","洗濯"],"洗濯アイテム","洗濯まわりのひと手間","洗濯をラクに"),
      (["絵本","本棚","ブック"],"本・絵本収納","本や絵本の散らかり","まとめて収納"),
      (["収納","ラック","ホルダー"],"収納アイテム","置き場所問題","すっきり収納"),
      (["掃除","クリーナー","ワイパー"],"掃除アイテム","掃除のひと手間","掃除をラクに"),
      (["ベビー","キッズ","子供","こども"],"子育てアイテム","子ども用品のひと手間","準備や片付けをラクに"),
      (["キッチン","台所"],"キッチンアイテム","キッチンの小さな面倒","家事をラクに"),
    ]
    for keys,label,pain,benefit in rules:
        if any(k.lower() in t for k in keys): return label,pain,benefit
    return "便利アイテム","暮らしの小さな面倒","ひと手間を減らす"

def threads_drafts(item, owned, experience=""):
    label,pain,benefit=product_context(item.get("itemName",""))
    if owned and experience.strip():
        e=experience.strip()
        return [
          {"kind":"実体験","text":f"{pain}、地味に面倒だった。\\n\\n{e}\\n\\nこういう小さい面倒が減るの、結構うれしい。"},
          {"kind":"あるある","text":f"{pain}って、みんなどうしてる？\\n\\nうちはこれを使ってる。\\n{e}\\n\\n地味だけどこういうの助かる。"},
          {"kind":"気づき","text":f"これ使い始めてから気づいた。\\n\\n{e}\\n\\n便利グッズって、毎日のひと手間が減るのがいい。"},
          {"kind":"会話","text":f"{label}って何使ってる？\\n\\nうちはこれ。\\n{e}\\n\\n他にもラクになるやつあったら知りたい🐾"}
        ]
    return [
      {"kind":"あるある→発見","text":f"{pain}って、地味に困らない？\\n\\n{benefit}できるやつ見つけた。\\nこういうのでひと手間減るなら普通に気になる。"},
      {"kind":"発見","text":f"え、{benefit}できるの知らなかった😂\\n\\n{pain}が気になってたから、こういうのちょっと気になる。\\n\\n誰か使ってる人いる？"},
      {"kind":"もし使ったら","text":f"{pain}。\\nこれ使ったら{benefit}できそう。\\n\\nまだ使ってないけど、こういう「地味な面倒を減らす系」に弱い。"},
      {"kind":"会話","text":f"{pain}、みんなどうしてる？\\n\\n{benefit}する{label}を見つけたんだけど、実際どうなんだろ。\\n使ってる人いたら感想知りたい🐾"}
    ]

def ai_check(text, owned=False):
    flags=[]
    for x in ["ぜひチェック","おすすめポイント","いかがでしょう","ではないでしょうか","必見","絶対買うべき"]:
        if x in text: flags.append(f"広告・AIっぽい表現「{x}」")
    if not owned:
        for x in ["買ってよかった","愛用","我が家では","使ってみた","ラクになった","助かった"]:
            if x in text: flags.append(f"未購入なのに体験談に見える「{x}」")
    if "《" in text: flags.append("商品名のコピペ感あり")
    if text.count("✨")>=2: flags.append("絵文字が多め")
    if text.count("？")>=3: flags.append("質問が多すぎ")
    if len(text)>220: flags.append("少し長め")
    return flags or ["やめんちゃん向け文章チェック：大きな違和感なし"]

def room_draft(item, owned, experience=""):
    label,pain,benefit=product_context(item.get("itemName",""))
    price=int(item.get("itemPrice") or 0); rating=item.get("reviewAverage","-"); reviews=int(item.get("reviewCount") or 0)
    if owned and experience.strip():
        lead=f"実際に使っている{label}🐾\\n{experience.strip()}"
    else:
        lead=f"{pain}対策で見つけた{label}🐾\\n{benefit}できそうなのが気になっています。"
    return f"{lead}\\n\\n価格：{price:,}円 / ★{rating}（{reviews:,}件）\\n\\n#便利グッズ #暮らしをラクに #楽天ROOM"



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
<h1>やめんちゃん AI 🐾</h1><p class="tag">面倒くさいを、ちょっとラクに。今日の運用までまとめる。 <small>v5.2</small></p>
<div class="panel"><div class="themes">
{% for t in themes %}<a class="theme {% if t==theme %}on{% endif %}" href="/?theme={{t}}">{{t}}</a>{% endfor %}
</div><form method="get" style="margin-top:10px"><input type="hidden" name="theme" value="{{theme}}">
<div class="row"><input name="q" value="{{q}}" placeholder="自由検索：例 水切り 便利"><button>検索</button></div></form>
<p class="small">テーマを選ぶと関連キーワードを複数検索して候補をまとめます。スコアは楽天の売上データではなく、関連度・レビュー・評価・価格帯・料率による独自指標です。</p></div>
{% if error %}<div class="error">{{error}}</div>{% endif %}
<div class="panel"><b>今日のやめんちゃん作戦</b>
{% for s in schedule %}<div class="small" style="margin-top:7px"><b>{{s.time}}</b>　{{s.type}}<br>{{s.why}}</div>{% endfor %}
<div class="small" style="margin-top:9px">※時間帯は固定の正解ではなく初期テスト枠。実績が貯まったら、やめんちゃん自身の結果を優先します。</div></div>
{% if items %}<p class="small"><b>今日の候補 TOP {{items|length}}</b>　※同一商品を整理して表示</p>{% endif %}
{% for x in items %}<div class="card"><div class="top">
{% if x.image %}<img class="pic" src="{{x.image}}" alt="">{% endif %}<div class="meta"><span class="score">候補スコア {{x.score}}/100</span>
<div class="name">{{x.itemName}}</div><div class="small"><b>{{x.badge}}</b><br>{{"{:,}".format(x.itemPrice)}}円 ・ ★{{x.reviewAverage}}（{{"{:,}".format(x.reviewCount)}}件）・ 料率{{x.affiliateRate}}%</div></div></div>
<details><summary>投稿文を作る</summary><div class="ownbox">
<form method="post"><input type="hidden" name="payload" value="{{x.idx}}">
<label>この商品は？</label><select name="owned"><option value="no">🔵 持っていない</option><option value="yes">🟢 持っている</option></select>
<label>持っている場合：実際に使って感じたこと</label><textarea name="experience" rows="3" placeholder="例：汚れてもサッと拭けて、掃除がかなりラク"></textarea>
<button style="margin-top:8px">文案を表示</button></form>
{% if selected==x.idx %}
{% for d in drafts %}<div class="small"><b>{{d.kind}}</b></div><div class="draft">{{d.text}}</div>{% endfor %}
<div class="small"><b>AI感チェック</b></div>
{% for c in checks %}<div class="small">・{{c}}</div>{% endfor %}
{% if room %}<div class="draft">{{room}}</div>{% endif %}
{% endif %}
</div></details><div style="margin-top:10px"><a class="buy" href="{{x.url}}" target="_blank" rel="noopener">楽天で確認</a></div></div>{% endfor %}
<div class="panel"><b>投稿実績・学習</b>
<div class="small">実績はこのiPhoneのブラウザ内に保存します。Renderの再起動・再デプロイでは消えません。</div>
<div class="row" style="margin-top:8px"><input id="lt" placeholder="投稿時刻 例 18:40"><input id="ly" placeholder="投稿型 例 発見"></div>
<div class="row" style="margin-top:8px"><input id="lv" type="number" placeholder="表示数"><input id="lr" type="number" placeholder="返信数"></div>
<div class="row" style="margin-top:8px"><input id="lp" type="number" placeholder="プロフィール閲覧"><input id="lc" type="number" placeholder="ROOMクリック"></div>
<input style="margin-top:8px" id="lo" placeholder="冒頭の一文">
<button type="button" style="margin-top:8px" onclick="saveY()">記録する</button>
<button type="button" style="margin-top:8px" onclick="backupY()">バックアップ</button>
<div id="ystats" class="small" style="margin-top:10px"></div>
</div></div>
<script>
function ys(){try{return JSON.parse(localStorage.getItem('yamenchan_logs')||'[]')}catch(e){return []}}
function med(a){a=a.sort((x,y)=>x-y);if(!a.length)return 0;let m=Math.floor(a.length/2);return a.length%2?a[m]:Math.round((a[m-1]+a[m])/2)}
function slot(t){let h=parseInt((t||'0').split(':')[0]);if(h>=11&&h<14)return'昼';if(h>=18&&h<20)return'18〜20時';if(h>=20&&h<23)return'20〜22時';return'その他'}
function saveY(){let a=ys();a.push({date:new Date().toLocaleDateString('ja-JP'),time:lt.value,type:ly.value,views:+lv.value||0,replies:+lr.value||0,profile:+lp.value||0,clicks:+lc.value||0,opening:lo.value});localStorage.setItem('yamenchan_logs',JSON.stringify(a));showY();alert('記録しました')}
function showY(){let a=ys(),g={};a.forEach(x=>{let k=slot(x.time)+' × '+(x.type||'未分類');(g[k]??=[]).push(x)});let s='記録 '+a.length+'件';for(let k in g){let z=g[k];s+='<br>'+k+'：表示中央値 '+med(z.map(x=>x.views))+' / 返信 '+z.reduce((n,x)=>n+x.replies,0)+' / ROOMクリック '+z.reduce((n,x)=>n+x.clicks,0)}ystats.innerHTML=s}
function backupY(){let b=new Blob([JSON.stringify(ys(),null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='yamenchan_logs.json';a.click()}
showY();
</script></body></html>"""

def schedule_hint():
    return [
        {"time":"11:30〜13:00","type":"商品なし・あるある/質問","why":"昼休みのテスト枠"},
        {"time":"18:00〜20:00","type":"Threads便利グッズ","why":"夕方〜夜の主力テスト枠"},
        {"time":"20:00〜22:00","type":"楽天ROOM","why":"ROOMの夜間閲覧を狙うテスト枠"},
    ]

def collect(theme, custom=""):
    keywords=[custom] if custom else THEMES.get(theme, THEMES["便利グッズ"])
    pool={}
    for kw in keywords:
        for sort in ("-reviewCount","standard"):
            for item in search_api(kw,20,sort):
                name=item.get("itemName","")
                rel=relevance(name,kw)
                if rel < 0: continue
                key=item.get("itemCode") or item.get("itemUrl") or name
                s=score(item,kw)
                if key not in pool or s>pool[key][1]:
                    pool[key]=(item,s,kw)

    rows=list(pool.values())
    rows.sort(key=lambda z:z[1],reverse=True)

    # Mix categories so the list is not filled only by old bestsellers.
    chosen=[]; used=set()
    def take(label, n):
        for item,s,kw in rows:
            key=item.get("itemCode") or item.get("itemUrl") or item.get("itemName")
            if key in used or badge(item,kw)!=label: continue
            chosen.append((item,s,kw,label)); used.add(key)
            if sum(1 for x in chosen if x[3]==label)>=n: break

    take("定番・高評価",3)
    take("発見候補",3)
    take("高料率",2)
    take("高評価",2)
    for item,s,kw in rows:
        if len(chosen)>=10: break
        key=item.get("itemCode") or item.get("itemUrl") or item.get("itemName")
        if key not in used:
            chosen.append((item,s,kw,badge(item,kw))); used.add(key)
    return chosen[:10]

@app.route("/",methods=["GET","POST"])
def home():
    theme=request.values.get("theme","便利グッズ")
    if theme not in THEMES: theme="便利グッズ"
    q=request.values.get("q","").strip()
    error=None; cards=[]; selected=-1; drafts=[]; room=""; checks=[]
    try:
        ranked=collect(theme,q)
        for i,(item,s,kw,label) in enumerate(ranked):
            cards.append({"idx":i,"itemName":display_name(item.get("itemName","")),"fullName":item.get("itemName",""),
              "badge":label,"itemPrice":int(item.get("itemPrice") or 0),
              "reviewAverage":float(item.get("reviewAverage") or 0),"reviewCount":int(item.get("reviewCount") or 0),
              "affiliateRate":float(item.get("affiliateRate") or 0),"image":image_url(item),"score":s,
              "url":item.get("affiliateUrl") or item.get("itemUrl") or "#","raw":item})
        if request.method=="POST":
            selected=int(request.form.get("payload","-1"))
            if 0<=selected<len(cards):
                owned=request.form.get("owned")=="yes"; exp=request.form.get("experience","")
                if owned and not exp.strip():
                    drafts=[{"kind":"入力が必要","text":"🟢「持っている」を選んだ場合は、実際に感じたことを入力してください。架空の使用感は作りません。"}]
                    room=""
                else:
                    drafts=threads_drafts(cards[selected]["raw"],owned,exp)
                    checks=ai_check(drafts[0]["text"],owned) if drafts else []
                    room="ROOM案\n"+room_draft(cards[selected]["raw"],owned,exp)
    except Exception as e: error=str(e)
    return render_template_string(PAGE,themes=THEMES.keys(),theme=theme,q=q,items=cards,error=error,
      selected=selected,drafts=drafts,room=room,checks=checks,schedule=schedule_hint())


@app.route("/health")
def health(): return {"status":"ok","version":"v5.2"}

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
