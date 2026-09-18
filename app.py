import os
import math
import html
import requests
from flask import Flask, request, render_template_string

app = Flask(__name__)

API_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"

def env(name):
    return os.environ.get(name, "").strip()

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def score_item(item):
    reviews = int(item.get("reviewCount") or 0)
    rating = float(item.get("reviewAverage") or 0)
    affiliate = float(item.get("affiliateRate") or 0)
    price = int(item.get("itemPrice") or 0)

    review_score = clamp(math.log10(reviews + 1) / 4 * 45, 0, 45)
    rating_score = clamp((rating - 3.0) / 2.0 * 30, 0, 30)
    affiliate_score = clamp(affiliate / 10 * 15, 0, 15)

    if 1000 <= price <= 10000:
        price_score = 10
    elif 500 <= price <= 20000:
        price_score = 7
    else:
        price_score = 4

    return round(review_score + rating_score + affiliate_score + price_score, 1)

def short_name(name, limit=44):
    name = (name or "").replace("\n", " ").strip()
    return name if len(name) <= limit else name[:limit] + "…"

def make_threads(item, owned=False):
    name = short_name(item.get("itemName", "この商品"), 28)
    if owned:
        return (
            f"これ、使ってみると地味に助かる😂\n\n"
            f"{name}\n"
            f"毎日の面倒を少し減らしたい時にこういうアイテム便利。\n\n"
            f"こういう『ちょっとラクになるもの』、みんな何使ってる？🐾"
        )
    return (
        f"え、こういうのあるんだ😂\n\n"
        f"{name}\n"
        f"毎回ちょっと面倒なことを減らせそうで気になる。\n\n"
        f"こういう便利グッズ、使ったことある人いる？🐾"
    )

def make_room(item, owned=False):
    name = short_name(item.get("itemName", "商品"), 55)
    price = int(item.get("itemPrice") or 0)
    rating = float(item.get("reviewAverage") or 0)
    reviews = int(item.get("reviewCount") or 0)
    if owned:
        intro = "実際に使っているアイテム🐾 面倒を少し減らしたい時に便利。"
    else:
        intro = "暮らしの面倒をちょっと減らしてくれそうで気になったアイテム🐾"
    return (
        f"{intro}\n\n{name}\n"
        f"価格：{price:,}円 / レビュー★{rating:.1f}（{reviews:,}件）\n\n"
        f"#便利グッズ #暮らしをラクに #家事ラク #楽天ROOM"
    )

def rakuten_search(keyword, sort="-reviewCount", hits=20):
    application_id = env("RAKUTEN_APPLICATION_ID")
    access_key = env("RAKUTEN_ACCESS_KEY")
    affiliate_id = env("RAKUTEN_AFFILIATE_ID")

    if not application_id or not access_key:
        raise RuntimeError("楽天APIの環境変数が設定されていません。")

    params = {
        "applicationId": application_id,
        "keyword": keyword,
        "format": "json",
        "formatVersion": 2,
        "hits": hits,
        "sort": sort,
        "availability": 1,
        "imageFlag": 1,
        "hasReviewFlag": 1,
        "carrier": 2,
        "field": 0,
    }
    if affiliate_id:
        params["affiliateId"] = affiliate_id

    # 2026-07-01 API accepts accessKey as a header or query parameter.
    # Use query parameter here to make the request easy to diagnose consistently.
    params["accessKey"] = access_key
    response = requests.get(API_URL, params=params, timeout=20)

    try:
        data = response.json()
    except Exception:
        raise RuntimeError(
            f"楽天API HTTP {response.status_code}: JSONではない応答が返りました。"
        )

    if response.status_code != 200:
        detail = data.get("error_description") or data.get("error") or "詳細不明"
        raise RuntimeError(f"楽天API HTTP {response.status_code}: {detail}")

    if data.get("error"):
        raise RuntimeError(
            f"楽天APIエラー: {data.get('error')} / "
            f"{data.get('error_description', '詳細不明')}"
        )

    items = data.get("items")
    if items is None:
        keys = ", ".join(list(data.keys())[:12])
        raise RuntimeError(
            f"API応答に items がありません。返却キー: {keys or 'なし'}"
        )

    diagnostic = {
        "http": response.status_code,
        "count": data.get("count"),
        "hits": data.get("hits"),
        "page": data.get("page"),
        "items_len": len(items),
    }
    return items, diagnostic

PAGE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>やめんちゃん AI</title>
<style>
:root{--bg:#f6f1e8;--card:#fffdf8;--ink:#3e342d;--sub:#74665d;--accent:#8b6d55;--line:#e7ddd2}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Yu Gothic",sans-serif}
.wrap{max-width:760px;margin:auto;padding:20px 14px 60px}.hero{padding:18px 4px 8px}.hero h1{margin:0;font-size:28px}.hero p{color:var(--sub);margin:7px 0}
form{background:var(--card);padding:14px;border:1px solid var(--line);border-radius:18px;box-shadow:0 4px 18px #0000000a}
.row{display:flex;gap:8px}input,select,button{font:inherit;border-radius:12px;border:1px solid var(--line);padding:12px}
input{width:100%;background:white}select{background:white}button{background:var(--ink);color:white;border:none;font-weight:700}
.note{font-size:12px;color:var(--sub);margin:10px 2px 0}.error{background:#fff0ef;border:1px solid #efc1bd;padding:12px;border-radius:12px;margin-top:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;margin-top:14px;padding:14px;overflow:hidden}
.top{display:flex;gap:12px}.pic{width:100px;height:100px;border-radius:12px;object-fit:cover;background:#eee}.meta{flex:1;min-width:0}
.name{font-weight:700;line-height:1.45}.stats{font-size:13px;color:var(--sub);margin-top:7px;line-height:1.6}.score{display:inline-block;background:#efe5d9;padding:4px 8px;border-radius:999px;font-size:12px;font-weight:700}
.tabs{margin-top:12px}.draft{white-space:pre-wrap;background:#f7f3ed;border-radius:12px;padding:11px;font-size:14px;line-height:1.65;margin-top:8px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.link{display:inline-block;text-decoration:none;background:var(--accent);color:white;padding:9px 11px;border-radius:10px;font-size:13px;font-weight:700}
.owned{font-size:13px;color:var(--sub);margin-top:9px}.footer{font-size:12px;color:var(--sub);margin-top:20px;line-height:1.6}
@media(max-width:520px){.row{flex-direction:column}.row button{width:100%}.pic{width:86px;height:86px}}
</style>
</head>
<body><div class="wrap">
<div class="hero"><h1>やめんちゃん AI 🐾</h1><p>面倒くさいを、ちょっとラクに。商品候補を楽天から発掘します。</p></div>
<form method="get">
<div class="row">
<input name="q" value="{{ q }}" placeholder="例：収納 便利グッズ" required>
<select name="sort">
<option value="-reviewCount" {% if sort=='-reviewCount' %}selected{% endif %}>レビュー数順</option>
<option value="-reviewAverage" {% if sort=='-reviewAverage' %}selected{% endif %}>評価順</option>
<option value="-affiliateRate" {% if sort=='-affiliateRate' %}selected{% endif %}>料率順</option>
<option value="standard" {% if sort=='standard' %}selected{% endif %}>楽天標準</option>
</select>
<button type="submit">商品を探す</button>
</div>
<p class="note">候補スコアはレビュー数・評価・価格帯・アフィリエイト料率から作る独自指標です。実際の売上を保証するものではありません。</p>
</form>
{% if error %}<div class="error"><strong>診断結果</strong><br>{{ error }}</div>{% endif %}
{% if diagnostic %}
<div class="card">
<strong>楽天API 診断</strong>
<div class="stats">
HTTP: {{ diagnostic.http }}<br>
楽天検索総件数 count: {{ diagnostic.count }}<br>
API返却件数 hits: {{ diagnostic.hits }}<br>
items配列: {{ diagnostic.items_len }}件<br>
page: {{ diagnostic.page }}
</div>
</div>
{% endif %}
{% if q and not error %}<p class="note">{{ items|length }}件取得 → 独自スコア順に表示</p>{% endif %}
{% for x in items %}
<div class="card">
<div class="top">
{% if x.image %}<img class="pic" src="{{ x.image }}" alt="">{% endif %}
<div class="meta">
<div class="score">候補スコア {{ x.score }}/100</div>
<div class="name">{{ x.itemName }}</div>
<div class="stats">{{ "{:,}".format(x.itemPrice) }}円 ・ ★{{ x.reviewAverage }}（{{ "{:,}".format(x.reviewCount) }}件）<br>料率 {{ x.affiliateRate }}% ・ {{ x.shopName }}</div>
</div></div>
<div class="tabs">
<div class="owned">🔵 未購入用 Threads案</div>
<div class="draft">{{ x.threads }}</div>
<div class="owned">🔵 未購入用 ROOM案</div>
<div class="draft">{{ x.room }}</div>
</div>
<div class="actions">
<a class="link" href="{{ x.url }}" target="_blank" rel="noopener">楽天で商品を見る</a>
</div>
</div>
{% endfor %}
<div class="footer">※ 未購入商品の文案では「買ってよかった」「使ってみた」などの実体験表現を使いません。購入済み商品の実体験文案は次のアップデートで切替機能を追加します。</div>
</div></body></html>"""

@app.route("/")
def home():
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "-reviewCount")
    allowed_sorts = {"-reviewCount", "-reviewAverage", "-affiliateRate", "standard"}
    if sort not in allowed_sorts:
        sort = "-reviewCount"

    items_out = []
    error = None
    diagnostic = None
    if q:
        try:
            items, diagnostic = rakuten_search(q, sort=sort)
            for item in items:
                image = ""
                images = item.get("mediumImageUrls") or []
                if images:
                    first = images[0]
                    image = first.get("imageUrl", "") if isinstance(first, dict) else str(first)
                item["_score"] = score_item(item)
                item["_image"] = image
            items.sort(key=lambda x: x["_score"], reverse=True)

            for item in items:
                items_out.append({
                    "itemName": item.get("itemName", ""),
                    "itemPrice": int(item.get("itemPrice") or 0),
                    "reviewAverage": float(item.get("reviewAverage") or 0),
                    "reviewCount": int(item.get("reviewCount") or 0),
                    "affiliateRate": float(item.get("affiliateRate") or 0),
                    "shopName": item.get("shopName", ""),
                    "score": item["_score"],
                    "image": item["_image"],
                    "url": item.get("affiliateUrl") or item.get("itemUrl") or "#",
                    "threads": make_threads(item, owned=False),
                    "room": make_room(item, owned=False),
                })
        except Exception as e:
            error = str(e)

    return render_template_string(
        PAGE, q=q, sort=sort, items=items_out,
        error=error, diagnostic=diagnostic
    )

@app.route("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
