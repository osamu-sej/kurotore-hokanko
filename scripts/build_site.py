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
                "order": int(meta["order"]) if str(meta.get("order", "")).lstrip("-").isdigit() else 0,
                "tags": [str(t) for t in tags],
                "partial": bool(meta.get("paywalled_other_brand")),
                "paywall_note": str(meta.get("paywall_note", "")),
                "fetched_via": str(meta.get("fetched_via", "")),
                "slug": slug_for(url, path.stem),
                "source_path": str(path.relative_to(ROOT)),
                "body": body,
            }
        )
    # 日付は新しい順、同じ日の中は掲載順（order 昇順）
    articles.sort(key=lambda a: (a["date"], -a["order"]), reverse=True)
    return articles


# --------------------------------------------------------------------------
# HTML 生成
#
# アーティファクト版保管庫 (kurotore-archive-updated) と同一の UI を再現する。
# スタイルは scripts/style.css をそのまま配置し、マークアップも同じ構造で出す。
# アーティファクトは全記事を JS で描画していたが、こちらはサーバー側で書き出して
# JS は絞り込みだけを担当する（JS 無しでも読める）。
# --------------------------------------------------------------------------

STYLE_SRC = Path(__file__).resolve().parent / "style.css"

JS = """
(function(){
  var state = { tag: null, q: "" };
  var cards = [].map.call(document.querySelectorAll('article.card'), function(el){
    var sum = el.querySelector('.summary');
    return {
      el: el,
      text: (el.querySelector('h2').textContent + ' ' + (sum ? sum.textContent : '')).toLowerCase(),
      tags: [].map.call(el.querySelectorAll('.tag-pill'), function(t){
        return t.textContent.replace(/^#/, '');
      })
    };
  });
  var headings = [].slice.call(document.querySelectorAll('.date-heading'));
  var buttons  = [].slice.call(document.querySelectorAll('.tag-btn'));
  var empty    = document.getElementById('empty');
  var search   = document.getElementById('search');

  function render(){
    var q = state.q.trim().toLowerCase(), shown = 0;
    cards.forEach(function(c){
      var ok = (!state.tag || c.tags.indexOf(state.tag) > -1) && (!q || c.text.indexOf(q) > -1);
      c.el.hidden = !ok;
      if (ok) shown++;
    });
    headings.forEach(function(h){
      var n = h.nextElementSibling, any = false;
      while (n && n.classList.contains('card')) { if (!n.hidden) any = true; n = n.nextElementSibling; }
      h.hidden = !any;
    });
    buttons.forEach(function(b){
      b.classList.toggle('active', (b.dataset.tag || null) === state.tag);
    });
    empty.hidden = shown > 0;
  }

  buttons.forEach(function(b){
    b.addEventListener('click', function(){
      state.tag = b.dataset.tag || null;
      render();
    });
  });
  search.addEventListener('input', function(e){ state.q = e.target.value; render(); });
})();
"""


def page(title: str, body_html: str, desc: str = SITE_DESC) -> str:
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<meta name="robots" content="noindex">
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="wrap">
{body_html}
</div>
<script>{JS}</script>
</body>
</html>
"""


def fmt_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{y}年{int(m)}月{int(d)}日"


def card_summary(body: str) -> str:
    """記事本文から、カードに出す要約テキストを取り出す。"""
    text = re.sub(r"^#.*$", "", body, flags=re.MULTILINE)
    lines = [re.sub(r"^>\s?", "", ln).strip() for ln in text.split("\n")]
    text = " ".join(ln for ln in lines if ln)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"（全文は元記事を参照[^）]*）", "", text)
    return re.sub(r"\s+", " ", text).strip()


def card_html(a: dict) -> str:
    parts = ['<article class="card">']

    crumb = f'<span class="cat">{html.escape(a["category"])}</span>' if a["category"] else ""
    if a["series"]:
        crumb = (crumb + " / " if crumb else "") + html.escape(a["series"])
    if crumb:
        parts.append(f'<div class="breadcrumb">{crumb}</div>')

    parts.append(f'<h2>{html.escape(a["title"])}</h2>')

    summary = card_summary(a["body"])
    if summary:
        parts.append(f'<p class="summary">{html.escape(summary)}</p>')

    if a["tags"]:
        pills = "".join(f'<span class="tag-pill">#{html.escape(t)}</span>' for t in a["tags"])
        parts.append(f'<div class="tags">{pills}</div>')

    if a["url"]:
        parts.append(
            f'<a class="source-link" href="{html.escape(a["url"])}" '
            'target="_blank" rel="noopener">元記事を読む ↗</a>'
        )
    parts.append("</article>")
    return "\n".join(parts)


def build_index(articles: list[dict]) -> str:
    tag_counts: dict[str, int] = {}
    for a in articles:
        for t in a["tags"]:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    sorted_tags = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    days = sorted({a["date"] for a in articles}, reverse=True)
    latest = fmt_date(days[0]) if days else "—"

    p = [
        '<header class="top">',
        "<div>",
        '<span class="eyebrow">XTREND ARCHIVE</span>',
        f"<h1>{html.escape(SITE_TITLE)}</h1>",
        '<p class="lede">日経クロストレンドの新着記事を読み、要約し、タグ別に蓄積していくアーカイブです。</p>',
        "</div>",
        '<div class="stats">',
        f'<div class="stat"><b>{len(articles)}</b><span>記事</span></div>',
        f'<div class="stat"><b>{len(tag_counts)}</b><span>タグ</span></div>',
        f'<div class="stat"><b>{len(days)}</b><span>日分</span></div>',
        "</div>",
        "</header>",
        '<div class="meta-row">',
        f'<span class="pill"><span class="dot"></span>最終更新： {latest}</span>',
        '<span class="pill">⏰ 毎朝7:00にチェックのリマインダーが届きます</span>',
        "</div>",
        '<hr class="rule" />',
        '<div class="layout">',
        "<aside>",
        '<div><div class="side-label">検索</div>',
        '<input id="search" type="text" placeholder="タイトル・要約を検索..." autocomplete="off" /></div>',
        '<div><div class="side-label">タグで絞り込み</div>',
        '<div class="tag-list" id="tagList">',
        f'<button class="tag-btn active" type="button"><span>すべて</span><span class="n">{len(articles)}</span></button>',
    ]
    for tag, count in sorted_tags:
        p.append(
            f'<button class="tag-btn" type="button" data-tag="{html.escape(tag)}">'
            f'<span>{html.escape(tag)}</span><span class="n">{count}</span></button>'
        )
    p.append("</div></div></aside>")

    p.append('<main id="main">')
    day = None
    for a in articles:
        if a["date"] != day:
            day = a["date"]
            p.append(f'<div class="date-heading">{html.escape(fmt_date(day))}</div>')
        p.append(card_html(a))
    p.append('<div class="empty" id="empty" hidden>該当する記事がありません。</div>')
    p.append("</main></div>")

    p.append(
        '<footer class="note">'
        "<p>タグは日経クロストレンドの記事に実際に付いているものをそのまま使用しています。"
        "毎朝の取り込みで新着記事がリポジトリに追加されると、このページは自動で再生成されます。</p>"
        "<p>Source: xtrend.nikkei.com（有料会員限定記事を含む）／本文は転載せず、要約のみを保管しています。"
        f"<br />最終取得日: {html.escape(latest)}</p>"
        "</footer>"
    )
    return "\n".join(p)


def main() -> None:
    articles = load_articles()
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    shutil.copyfile(STYLE_SRC, OUT_DIR / "style.css")
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (OUT_DIR / "index.html").write_text(page(SITE_TITLE, build_index(articles)), encoding="utf-8")

    # 翌朝の取り込みで「すでに保管済みか」を判定するためのインデックス
    (OUT_DIR / "index.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(JST).isoformat(),
                "count": len(articles),
                "urls": sorted({a["url"] for a in articles if a["url"]}),
                "articles": [
                    {k: a[k] for k in ("title", "url", "series", "category", "date", "tags", "partial")}
                    for a in articles
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    print(f"built {len(articles)} articles -> {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
