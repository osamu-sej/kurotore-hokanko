#!/usr/bin/env python3
"""クロトレ保管庫 静的サイトビルダー

articles/**/*.md を読み込み、site/ 以下に静的サイトを生成する。

  site/index.html     一覧（全文検索・タグ絞り込み付き）
  site/a/<slug>.html  記事ごとの要約ページ
  site/index.json     取得済み記事の機械可読インデックス（重複取得の判定に使う）

依存パッケージなし（標準ライブラリのみ）。ローカルでは次で確認できる:
  python3 scripts/build_site.py && python3 -m http.server -d site
"""

from __future__ import annotations

import html
import json
import re
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT / "articles"
OUT_DIR = ROOT / "site"
JST = timezone(timedelta(hours=9))
SITE_TITLE = "クロトレ保管庫"
SITE_DESC = "日経クロストレンドの読了記事アーカイブ（タイトル・出典リンク・自作サマリー）"


# --------------------------------------------------------------------------
# frontmatter の解析
# --------------------------------------------------------------------------

def parse_scalar(raw: str):
    """YAML スカラーのうち、この保管庫で実際に使う形だけを解釈する。"""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        inner = raw[1:-1]
        if raw[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    if raw in ("true", "false"):
        return raw == "true"
    return raw


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """--- で囲まれた frontmatter と本文を返す。"""
    if not text.startswith("---"):
        return {}, text

    lines = text.split("\n")
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}, text

    meta: dict = {}
    key = None
    for line in lines[1:end]:
        if not line.strip():
            continue
        # ブロック形式のリスト（  - foo）
        if line.lstrip().startswith("-") and key:
            meta.setdefault(key, [])
            if isinstance(meta[key], list):
                meta[key].append(parse_scalar(line.lstrip()[1:]))
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            meta[key] = [parse_scalar(v) for v in inner.split(",") if v.strip()] if inner else []
        elif raw == "":
            meta[key] = []
        else:
            meta[key] = parse_scalar(raw)

    return meta, "\n".join(lines[end + 1:]).strip()


# --------------------------------------------------------------------------
# 最小限の Markdown レンダラ
# 保管庫の本文は「見出し / 引用 / 段落 / 強調」しか使わない前提。
# --------------------------------------------------------------------------

def render_inline(text: str) -> str:
    out = html.escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<em>\1</em>", out)
    out = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<a href="\2" rel="noopener noreferrer" target="_blank">\1</a>',
        out,
    )
    return out


def render_markdown(body: str, drop_first_h1: bool = True) -> str:
    """本文 Markdown を HTML に変換する。先頭の H1 はページ側で出すので既定で捨てる。"""
    blocks: list[str] = []
    para: list[str] = []
    quote: list[str] = []
    seen_h1 = False

    def flush_para():
        if para:
            blocks.append("<p>" + render_inline(" ".join(para)) + "</p>")
            para.clear()

    def flush_quote():
        if quote:
            inner = render_markdown("\n".join(quote), drop_first_h1=False)
            blocks.append("<blockquote>" + inner + "</blockquote>")
            quote.clear()

    for line in body.split("\n"):
        stripped = line.strip()

        if stripped.startswith(">"):
            flush_para()
            quote.append(stripped[1:].lstrip())
            continue
        flush_quote()

        if not stripped:
            flush_para()
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            level = len(m.group(1))
            if level == 1 and drop_first_h1 and not seen_h1:
                seen_h1 = True
                continue
            blocks.append(f"<h{level}>{render_inline(m.group(2))}</h{level}>")
            continue

        para.append(stripped)

    flush_para()
    flush_quote()
    return "\n".join(blocks)


# --------------------------------------------------------------------------
# 記事の読み込み
# --------------------------------------------------------------------------

def slug_for(url: str, fallback: str) -> str:
    """記事 URL から安定した slug を作る（ファイル名の連番に依存しないため）。"""
    for pattern in (r"/atcl/contents/(.+?)/?$", r"/atcl/(.+?)/?$"):
        m = re.search(pattern, url or "")
        if m:
            return re.sub(r"[^A-Za-z0-9_-]+", "-", m.group(1)).strip("-")
    return re.sub(r"[^A-Za-z0-9_-]+", "-", fallback).strip("-")


def load_articles() -> list[dict]:
    articles: list[dict] = []
    for path in sorted(ARTICLES_DIR.rglob("*.md")):
        if path.name.startswith("_"):
            continue
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        if not meta.get("title"):
            continue
        url = str(meta.get("url", ""))
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        articles.append(
            {
                "title": str(meta["title"]),
                "url": url,
                "series": str(meta.get("series", "")),
                "category": str(meta.get("category", "")),
                "date": str(meta.get("date", path.parent.name)),
                "tags": [str(t) for t in tags],
                "partial": bool(meta.get("paywalled_other_brand")),
                "paywall_note": str(meta.get("paywall_note", "")),
                "fetched_via": str(meta.get("fetched_via", "")),
                "slug": slug_for(url, path.stem),
                "source_path": str(path.relative_to(ROOT)),
                "body": body,
            }
        )
    articles.sort(key=lambda a: (a["date"], a["title"]), reverse=True)
    return articles


# --------------------------------------------------------------------------
# HTML 生成
#
# 記事数が数千件規模まで増えるため、一覧は 1 枚に全部並べない。
#   index.html   直近 RECENT 件 + 月別ナビ + 検索（index.json を必要時に取得）
#   m/YYYY-MM.html  その月の全記事
# --------------------------------------------------------------------------

RECENT = 80

CSS = """
:root{--bg:#f0efe8;--surface:#fbfaf6;--fg:#211f1a;--muted:#7c7568;--faint:#a49c8c;
--line:#e2ddd0;--accent:#c1502e;--accent-strong:#a63e20;--accent-tint:#f3ddd2;
--tag-bg:#efe9dd;--tag-text:#6d6455;--warn-bg:#fdf3e3;--warn-line:#e3c48d;--warn-fg:#7a5310;}
@media (prefers-color-scheme:dark){:root{--bg:#17160f;--surface:#201e17;--fg:#f0ece0;
--muted:#a89e88;--faint:#766d5c;--line:#37331f;--accent:#e08654;--accent-strong:#f0996a;
--accent-tint:#3d2a1c;--tag-bg:#2a271b;--tag-text:#b8ad94;--warn-bg:#2e2519;
--warn-line:#6b5427;--warn-fg:#e8c88a;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);line-height:1.7;
font-family:'Noto Sans JP','Hiragino Kaku Gothic ProN','Hiragino Sans',Meiryo,system-ui,sans-serif;
-webkit-font-smoothing:antialiased;-webkit-text-size-adjust:100%}
.wrap{max-width:1000px;margin:0 auto;padding:0 22px 80px}
a{color:var(--accent)}
header.site{border-bottom:1px solid var(--line);margin-bottom:24px;padding:40px 0 22px}
header.site h1{margin:0 0 8px;font-size:clamp(24px,3.4vw,32px);font-weight:700;letter-spacing:.01em}
header.site .lede{margin:0;color:var(--muted);font-size:14px}
.tools{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 16px}
#q{flex:1 1 260px;min-width:0;padding:11px 14px;border:1px solid var(--line);border-radius:9px;
background:var(--surface);color:var(--fg);font-size:15px;font-family:inherit}
#q:focus{outline:2px solid var(--accent);outline-offset:1px}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:20px}
.tag{border:1px solid var(--line);background:var(--surface);color:var(--tag-text);
border-radius:999px;padding:4px 12px;font-size:12px;cursor:pointer;font-family:inherit;line-height:1.6}
.tag:hover{border-color:var(--accent);color:var(--fg)}
.tag[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
@media (prefers-color-scheme:dark){.tag[aria-pressed="true"]{color:#1a1714}}
.nav{background:var(--surface);border:1px solid var(--line);border-radius:11px;
padding:16px 18px;margin-bottom:26px}
.nav h2{margin:0 0 10px;font-size:12px;letter-spacing:.1em;color:var(--muted);font-weight:600}
.nav .yr{display:flex;flex-wrap:wrap;gap:6px;align-items:baseline;margin-bottom:8px}
.nav .yr b{font-size:13px;color:var(--faint);margin-right:4px;font-weight:600}
.nav a{display:inline-block;font-size:13px;text-decoration:none;border:1px solid var(--line);
border-radius:7px;padding:3px 9px;background:var(--bg)}
.nav a:hover{border-color:var(--accent)}
.nav a span{color:var(--faint);font-size:11px;margin-left:3px}
h2.day{font-size:12px;color:var(--muted);font-weight:600;letter-spacing:.09em;
margin:30px 0 12px;padding-bottom:7px;border-bottom:1px solid var(--line)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:11px;
padding:15px 18px;margin-bottom:10px}
.card h3{margin:0 0 7px;font-size:16px;line-height:1.55;font-weight:600}
.card h3 a{color:var(--fg);text-decoration:none}
.card h3 a:hover{color:var(--accent);text-decoration:underline}
.series{display:inline-block;font-size:12px;color:var(--accent-strong);background:var(--accent-tint);
border-radius:5px;padding:2px 8px;margin-bottom:7px}
.summary{font-size:13.5px;color:var(--muted);margin:0 0 10px;
display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:11.5px;color:var(--muted)}
.meta .chip{border:1px solid var(--line);background:var(--tag-bg);color:var(--tag-text);
border-radius:999px;padding:1px 9px}
.meta .cat{background:var(--accent-tint);color:var(--accent-strong);border-color:transparent}
.meta a{color:var(--accent);text-decoration:none}
.meta a:hover{text-decoration:underline}
.partial{background:var(--warn-bg);border-color:var(--warn-line);color:var(--warn-fg)}
.note{color:var(--faint);font-size:12.5px;margin:0 0 18px}
.status{color:var(--muted);font-size:13px;margin:0 0 14px}
article.detail{background:var(--surface);border:1px solid var(--line);border-radius:11px;padding:28px 30px}
article.detail h1{font-size:21px;line-height:1.55;margin:0 0 14px}
article.detail p{font-size:15px}
article.detail blockquote{margin:16px 0;padding:2px 16px;border-left:3px solid var(--warn-line);
background:var(--warn-bg);border-radius:0 7px 7px 0}
article.detail blockquote p{color:var(--warn-fg)}
.back{display:inline-block;margin:26px 0 20px;color:var(--accent);text-decoration:none;font-size:14px}
.back:hover{text-decoration:underline}
.source{margin-top:22px;padding-top:16px;border-top:1px solid var(--line);font-size:13.5px;color:var(--muted)}
footer.site{margin-top:48px;padding-top:18px;border-top:1px solid var(--line);
color:var(--faint);font-size:12px}
@media(max-width:600px){article.detail{padding:20px 18px}.wrap{padding:0 14px 60px}}
"""

JS = """
(function(){
  var q=document.getElementById('q'), out=document.getElementById('results'),
      def=document.getElementById('default'), status=document.getElementById('status'),
      idx=null, pending=false, active=new Set();

  function esc(s){return String(s).replace(/[&<>"]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}

  function render(list){
    if(!list.length){ status.textContent='該当する記事がありません。'; out.innerHTML=''; return; }
    status.textContent=list.length+' 件';
    var day=null, h=[];
    list.forEach(function(a){
      if(a.date!==day){ day=a.date; h.push('<h2 class="day">'+esc(day)+'</h2>'); }
      h.push('<div class="card">');
      if(a.series) h.push('<div class="series">'+esc(a.series)+'</div>');
      h.push('<h3><a href="a/'+esc(a.slug)+'.html">'+esc(a.title)+'</a></h3>');
      h.push('<div class="meta">');
      if(a.category) h.push('<span class="chip cat">'+esc(a.category)+'</span>');
      if(a.partial) h.push('<span class="chip partial">一部のみ取得</span>');
      (a.tags||[]).slice(0,6).forEach(function(t){h.push('<span class="chip">'+esc(t)+'</span>');});
      if(a.url) h.push('<a href="'+esc(a.url)+'" target="_blank" rel="noopener noreferrer">元記事 ↗</a>');
      h.push('</div></div>');
    });
    out.innerHTML=h.join('');
  }

  function filter(){
    var term=(q.value||'').trim().toLowerCase();
    if(!term && active.size===0){
      def.hidden=false; out.innerHTML=''; status.textContent=''; return;
    }
    def.hidden=true;
    if(!idx){ status.textContent='読み込み中…'; return; }
    render(idx.filter(function(a){
      if(active.size){
        var tags=a.tags||[], ok=true;
        active.forEach(function(t){ if(tags.indexOf(t)<0) ok=false; });
        if(!ok) return false;
      }
      if(!term) return true;
      return (a.title+' '+(a.series||'')+' '+(a.category||'')+' '+(a.tags||[]).join(' ')
             ).toLowerCase().indexOf(term)>-1;
    }));
  }

  function ensure(){
    if(idx||pending) return;
    pending=true;
    fetch('index.json').then(function(r){return r.json();}).then(function(j){
      idx=j.articles; pending=false; filter();
    }).catch(function(){ pending=false; status.textContent='索引を読み込めませんでした。'; });
  }

  q.addEventListener('input',function(){ ensure(); filter(); });
  q.addEventListener('focus',ensure);
  [].forEach.call(document.querySelectorAll('.tag'),function(b){
    b.addEventListener('click',function(){
      var t=b.dataset.tag;
      if(active.has(t)){active.delete(t);b.setAttribute('aria-pressed','false');}
      else{active.add(t);b.setAttribute('aria-pressed','true');}
      ensure(); filter();
    });
  });
})();
"""


def page(title: str, body_html: str, depth: int = 0, desc: str = SITE_DESC) -> str:
    base = "../" * depth
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<meta name="robots" content="noindex">
<link rel="stylesheet" href="{base}style.css">
</head>
<body>
<div class="wrap">
{body_html}
<footer class="site">
{html.escape(SITE_TITLE)} — 各記事は日経クロストレンドの著作物です。本サイトはタイトル・出典リンク・自作の要約のみを保管しており、本文は転載していません。
</footer>
</div>
</body>
</html>
"""


def summary_text(body: str, limit: int = 140) -> str:
    plain = re.sub(r"^#.*$", "", body, flags=re.MULTILINE)
    plain = re.sub(r"[>*`\[\]]", "", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:limit]


def card_html(a: dict, depth: int = 0) -> str:
    base = "../" * depth
    parts = ['<div class="card">']
    if a["series"]:
        parts.append(f'<div class="series">{html.escape(a["series"])}</div>')
    parts.append(f'<h3><a href="{base}a/{a["slug"]}.html">{html.escape(a["title"])}</a></h3>')
    parts.append(f'<p class="summary">{html.escape(summary_text(a["body"]))}</p>')
    parts.append('<div class="meta">')
    if a["category"]:
        parts.append(f'<span class="chip cat">{html.escape(a["category"])}</span>')
    if a["partial"]:
        parts.append('<span class="chip partial">一部のみ取得</span>')
    for t in a["tags"][:6]:
        parts.append(f'<span class="chip">{html.escape(t)}</span>')
    if a["url"]:
        parts.append(f'<a href="{html.escape(a["url"])}" target="_blank" rel="noopener noreferrer">元記事 ↗</a>')
    parts.append("</div></div>")
    return "\n".join(parts)


def cards_by_day(articles: list[dict], depth: int = 0) -> list[str]:
    out, day = [], None
    for a in articles:
        if a["date"] != day:
            day = a["date"]
            out.append(f'<h2 class="day">{html.escape(day)}</h2>')
        out.append(card_html(a, depth))
    return out


def month_nav(articles: list[dict]) -> str:
    months: dict[str, int] = {}
    for a in articles:
        months[a["date"][:7]] = months.get(a["date"][:7], 0) + 1

    years: dict[str, list[str]] = {}
    for ym in sorted(months, reverse=True):
        years.setdefault(ym[:4], []).append(ym)

    parts = ['<nav class="nav"><h2>月別アーカイブ</h2>']
    for year in sorted(years, reverse=True):
        parts.append(f'<div class="yr"><b>{year}</b>')
        for ym in years[year]:
            parts.append(
                f'<a href="m/{ym}.html">{ym[5:7]}月<span>{months[ym]}</span></a>'
            )
        parts.append("</div>")
    parts.append("</nav>")
    return "\n".join(parts)


def build_index(articles: list[dict]) -> str:
    all_tags: dict[str, int] = {}
    for a in articles:
        for t in a["tags"]:
            all_tags[t] = all_tags.get(t, 0) + 1
    top_tags = sorted(all_tags.items(), key=lambda kv: (-kv[1], kv[0]))[:24]

    parts = [
        '<header class="site">',
        f"<h1>{html.escape(SITE_TITLE)}</h1>",
        f'<p class="lede">日経クロストレンド 読了アーカイブ — 全 {len(articles)} 本 / '
        f'最終更新 {datetime.now(JST).strftime("%Y-%m-%d %H:%M")} JST</p>',
        "</header>",
        '<div class="tools"><input id="q" type="search" '
        'placeholder="全 %d 本から検索（タイトル・シリーズ・カテゴリ・タグ）" autocomplete="off"></div>'
        % len(articles),
    ]

    if top_tags:
        parts.append('<div class="tags">')
        for tag, count in top_tags:
            parts.append(
                f'<button class="tag" type="button" aria-pressed="false" '
                f'data-tag="{html.escape(tag)}">{html.escape(tag)} <span>{count}</span></button>'
            )
        parts.append("</div>")

    parts.append('<p class="status" id="status"></p>')
    parts.append('<div id="results"></div>')

    parts.append('<div id="default">')
    parts.append(month_nav(articles))
    parts.append(f'<p class="note">直近 {min(RECENT, len(articles))} 本を表示しています。'
                 "それ以前は上の月別アーカイブ、または検索欄から。</p>")
    parts.extend(cards_by_day(articles[:RECENT]))
    parts.append("</div>")

    parts.append(f"<script>{JS}</script>")
    return "\n".join(parts)


def build_month(ym: str, articles: list[dict]) -> str:
    parts = [
        '<a class="back" href="../index.html">← 保管庫トップに戻る</a>',
        '<header class="site">',
        f"<h1>{ym[:4]}年{ym[5:7]}月</h1>",
        f'<p class="lede">{len(articles)} 本</p>',
        "</header>",
    ]
    parts.extend(cards_by_day(articles, depth=1))
    return "\n".join(parts)


def build_detail(a: dict) -> str:
    parts = [
        '<a class="back" href="../index.html">← 保管庫トップに戻る</a>',
        '<article class="detail">',
    ]
    if a["series"]:
        parts.append(f'<div class="series">{html.escape(a["series"])}</div>')
    parts.append(f'<h1>{html.escape(a["title"])}</h1>')
    parts.append('<div class="meta">')
    parts.append(f'<span class="chip">{html.escape(a["date"])}</span>')
    if a["category"]:
        parts.append(f'<span class="chip cat">{html.escape(a["category"])}</span>')
    if a["partial"]:
        parts.append('<span class="chip partial">一部のみ取得</span>')
    for t in a["tags"]:
        parts.append(f'<span class="chip">{html.escape(t)}</span>')
    parts.append("</div>")
    parts.append(render_markdown(a["body"]))
    if a["url"]:
        parts.append(
            '<div class="source">出典: '
            f'<a href="{html.escape(a["url"])}" target="_blank" rel="noopener noreferrer">{html.escape(a["url"])}</a>'
            "<br>本文は転載していません。全文は元記事（日経クロストレンド）をご覧ください。</div>"
        )
    parts.append("</article>")
    return "\n".join(parts)


def main() -> None:
    articles = load_articles()
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    (OUT_DIR / "a").mkdir(parents=True)
    (OUT_DIR / "m").mkdir(parents=True)

    (OUT_DIR / "style.css").write_text(CSS, encoding="utf-8")
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (OUT_DIR / "index.html").write_text(page(SITE_TITLE, build_index(articles)), encoding="utf-8")

    by_month: dict[str, list[dict]] = {}
    for a in articles:
        by_month.setdefault(a["date"][:7], []).append(a)
    for ym, items in by_month.items():
        (OUT_DIR / "m" / f"{ym}.html").write_text(
            page(f"{ym[:4]}年{ym[5:7]}月 | {SITE_TITLE}", build_month(ym, items), depth=1),
            encoding="utf-8",
        )

    for a in articles:
        (OUT_DIR / "a" / f"{a['slug']}.html").write_text(
            page(f"{a['title']} | {SITE_TITLE}", build_detail(a), depth=1, desc=summary_text(a["body"])),
            encoding="utf-8",
        )

    # 翌朝の取り込みで「すでに保管済みか」を判定し、サイト内検索の索引も兼ねる
    (OUT_DIR / "index.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(JST).isoformat(),
                "count": len(articles),
                "urls": sorted({a["url"] for a in articles if a["url"]}),
                "articles": [
                    {k: a[k] for k in ("title", "url", "series", "category", "date", "tags", "partial", "slug")}
                    for a in articles
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    print(f"built {len(articles)} articles / {len(by_month)} months -> {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
