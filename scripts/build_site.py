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
        return raw[1:-1]
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
    m = re.search(r"/atcl/contents/(.+?)/?$", url or "")
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
# --------------------------------------------------------------------------

CSS = """
:root{--bg:#fbfaf8;--card:#fff;--fg:#1c1a17;--muted:#6b6560;--line:#e6e1da;
--accent:#8a5a2b;--accent-soft:#f2ebe1;--warn-bg:#fdf3e3;--warn-line:#e3c48d;--warn-fg:#7a5310;}
@media (prefers-color-scheme:dark){
:root{--bg:#161513;--card:#201e1b;--fg:#eceae6;--muted:#a09990;--line:#332f2a;
--accent:#d9a86c;--accent-soft:#2b2620;--warn-bg:#2e2519;--warn-line:#6b5427;--warn-fg:#e8c88a;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font-family:"Hiragino Kaku Gothic ProN","Hiragino Sans","Noto Sans JP",Meiryo,system-ui,-apple-system,sans-serif;
line-height:1.75;-webkit-text-size-adjust:100%}
.wrap{max-width:860px;margin:0 auto;padding:0 20px 72px}
header.site{border-bottom:1px solid var(--line);margin-bottom:28px;padding:36px 0 22px}
header.site h1{margin:0 0 6px;font-size:1.6rem;letter-spacing:.02em}
header.site p{margin:0;color:var(--muted);font-size:.85rem}
.tools{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 18px}
#q{flex:1 1 240px;min-width:0;padding:10px 13px;border:1px solid var(--line);border-radius:9px;
background:var(--card);color:var(--fg);font-size:.92rem;font-family:inherit}
#q:focus{outline:2px solid var(--accent);outline-offset:1px}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:22px}
.tag{border:1px solid var(--line);background:var(--card);color:var(--muted);border-radius:999px;
padding:3px 11px;font-size:.76rem;cursor:pointer;font-family:inherit;line-height:1.6}
.tag:hover{border-color:var(--accent);color:var(--fg)}
.tag[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
@media (prefers-color-scheme:dark){.tag[aria-pressed="true"]{color:#1a1714}}
h2.day{font-size:.82rem;color:var(--muted);font-weight:600;letter-spacing:.09em;
margin:32px 0 12px;padding-bottom:7px;border-bottom:1px solid var(--line)}
.card{background:var(--card);border:1px solid var(--line);border-radius:11px;
padding:16px 18px;margin-bottom:11px}
.card h3{margin:0 0 7px;font-size:1.01rem;line-height:1.55;font-weight:600}
.card h3 a{color:var(--fg);text-decoration:none}
.card h3 a:hover{color:var(--accent);text-decoration:underline}
.series{display:inline-block;font-size:.74rem;color:var(--accent);background:var(--accent-soft);
border-radius:5px;padding:2px 8px;margin-bottom:8px}
.summary{font-size:.88rem;color:var(--muted);margin:0 0 10px;
display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:.74rem;color:var(--muted)}
.meta .chip{border:1px solid var(--line);border-radius:999px;padding:1px 8px}
.meta a{color:var(--accent);text-decoration:none}
.meta a:hover{text-decoration:underline}
.partial{background:var(--warn-bg);border-color:var(--warn-line);color:var(--warn-fg)}
.empty{color:var(--muted);text-align:center;padding:56px 0;font-size:.9rem}
article.detail{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:26px 28px}
article.detail h1{font-size:1.32rem;line-height:1.55;margin:0 0 14px}
article.detail p{font-size:.95rem}
article.detail blockquote{margin:16px 0;padding:2px 0 2px 16px;border-left:3px solid var(--warn-line);
background:var(--warn-bg);border-radius:0 7px 7px 0;padding-right:16px}
article.detail blockquote p{color:var(--warn-fg)}
.back{display:inline-block;margin:26px 0 20px;color:var(--accent);text-decoration:none;font-size:.86rem}
.back:hover{text-decoration:underline}
.source{margin-top:22px;padding-top:16px;border-top:1px solid var(--line);font-size:.85rem}
.source a{color:var(--accent)}
footer.site{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);
color:var(--muted);font-size:.76rem}
@media(max-width:600px){article.detail{padding:20px 18px}.wrap{padding:0 14px 56px}}
"""

JS = """
(function(){
  var q=document.getElementById('q'), cards=[].slice.call(document.querySelectorAll('.card'));
  var days=[].slice.call(document.querySelectorAll('h2.day')), active=new Set();
  var empty=document.getElementById('empty');
  function apply(){
    var term=(q.value||'').trim().toLowerCase(), shown=0;
    cards.forEach(function(c){
      var hay=c.dataset.search, tags=(c.dataset.tags||'').split('\\u001f');
      var okText=!term||hay.indexOf(term)>-1, okTags=true;
      active.forEach(function(t){ if(tags.indexOf(t)<0) okTags=false; });
      var vis=okText&&okTags;
      c.hidden=!vis; if(vis)shown++;
    });
    days.forEach(function(h){
      var n=h.nextElementSibling, any=false;
      while(n&&n.classList.contains('card')){ if(!n.hidden)any=true; n=n.nextElementSibling; }
      h.hidden=!any;
    });
    empty.hidden=shown>0;
  }
  q.addEventListener('input',apply);
  [].forEach.call(document.querySelectorAll('.tag'),function(b){
    b.addEventListener('click',function(){
      var t=b.dataset.tag;
      if(active.has(t)){active.delete(t);b.setAttribute('aria-pressed','false');}
      else{active.add(t);b.setAttribute('aria-pressed','true');}
      apply();
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


def build_index(articles: list[dict]) -> str:
    all_tags: dict[str, int] = {}
    for a in articles:
        for t in a["tags"]:
            all_tags[t] = all_tags.get(t, 0) + 1
    top_tags = sorted(all_tags.items(), key=lambda kv: (-kv[1], kv[0]))[:28]

    parts = [
        '<header class="site">',
        f"<h1>{html.escape(SITE_TITLE)}</h1>",
        f'<p>日経クロストレンド 読了アーカイブ — 全 {len(articles)} 本 / '
        f'最終更新 {datetime.now(JST).strftime("%Y-%m-%d %H:%M")} JST</p>',
        "</header>",
        '<div class="tools"><input id="q" type="search" placeholder="タイトル・シリーズ・要約・タグを検索" autocomplete="off"></div>',
    ]

    if top_tags:
        parts.append('<div class="tags">')
        for tag, count in top_tags:
            parts.append(
                f'<button class="tag" type="button" aria-pressed="false" '
                f'data-tag="{html.escape(tag)}">{html.escape(tag)} <span>{count}</span></button>'
            )
        parts.append("</div>")

    current_day = None
    for a in articles:
        if a["date"] != current_day:
            current_day = a["date"]
            parts.append(f'<h2 class="day">{html.escape(current_day)}</h2>')

        haystack = " ".join([a["title"], a["series"], summary_text(a["body"], 400), " ".join(a["tags"])]).lower()
        parts.append(
            f'<div class="card" data-search="{html.escape(haystack)}" '
            f'data-tags="{html.escape(chr(31).join(a["tags"]))}">'
        )
        if a["series"]:
            parts.append(f'<div class="series">{html.escape(a["series"])}</div>')
        parts.append(f'<h3><a href="a/{a["slug"]}.html">{html.escape(a["title"])}</a></h3>')
        parts.append(f'<p class="summary">{html.escape(summary_text(a["body"]))}</p>')

        parts.append('<div class="meta">')
        if a["partial"]:
            parts.append('<span class="chip partial">一部のみ取得</span>')
        for t in a["tags"][:6]:
            parts.append(f'<span class="chip">{html.escape(t)}</span>')
        if a["url"]:
            parts.append(f'<a href="{html.escape(a["url"])}" target="_blank" rel="noopener noreferrer">元記事 ↗</a>')
        parts.append("</div></div>")

    parts.append('<p class="empty" id="empty" hidden>該当する記事がありません。</p>')
    parts.append(f"<script>{JS}</script>")
    return "\n".join(parts)


def build_detail(a: dict) -> str:
    parts = [
        '<a class="back" href="../index.html">← 一覧に戻る</a>',
        '<article class="detail">',
    ]
    if a["series"]:
        parts.append(f'<div class="series">{html.escape(a["series"])}</div>')
    parts.append(f'<h1>{html.escape(a["title"])}</h1>')

    parts.append('<div class="meta">')
    parts.append(f'<span class="chip">{html.escape(a["date"])}</span>')
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

    (OUT_DIR / "style.css").write_text(CSS, encoding="utf-8")
    (OUT_DIR / "index.html").write_text(page(SITE_TITLE, build_index(articles)), encoding="utf-8")
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")

    for a in articles:
        (OUT_DIR / "a" / f"{a['slug']}.html").write_text(
            page(f"{a['title']} | {SITE_TITLE}", build_detail(a), depth=1, desc=summary_text(a["body"])),
            encoding="utf-8",
        )

    # 翌朝の取り込みで「すでに保管済みか」を判定するためのインデックス
    (OUT_DIR / "index.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(JST).isoformat(),
                "count": len(articles),
                "urls": sorted({a["url"] for a in articles if a["url"]}),
                "articles": [
                    {k: a[k] for k in ("title", "url", "series", "date", "tags", "partial", "slug")}
                    for a in articles
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"built {len(articles)} articles -> {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
