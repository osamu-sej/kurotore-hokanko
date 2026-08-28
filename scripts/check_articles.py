#!/usr/bin/env python3
"""articles/ の健全性チェック（CI で実行）。

1. frontmatter の必須項目がそろっているか
2. 同じ記事 URL を二重に取り込んでいないか（毎朝の差分取得の要）
3. 本文が長すぎないか = 元記事の全文転載になっていないか（公開リポジトリのため）

失敗すると exit 1。ローカルでも `python3 scripts/check_articles.py` で実行できる。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_site import ARTICLES_DIR, ROOT, parse_frontmatter  # noqa: E402

REQUIRED = ("title", "url", "date")
# 保管庫に置くのは「自分の言葉での要約」。これを超えたら全文転載を疑う。
MAX_BODY_CHARS = 3000


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    seen_urls: dict[str, str] = {}
    count = 0

    for path in sorted(ARTICLES_DIR.rglob("*.md")):
        if path.name.startswith("_"):
            continue
        rel = path.relative_to(ROOT)
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        count += 1

        for key in REQUIRED:
            if not meta.get(key):
                errors.append(f"{rel}: frontmatter に {key} がありません")

        url = str(meta.get("url", ""))
        if url:
            if not url.startswith("https://xtrend.nikkei.com/"):
                warnings.append(f"{rel}: xtrend.nikkei.com 以外の URL です ({url})")
            if url in seen_urls:
                errors.append(f"{rel}: URL が {seen_urls[url]} と重複しています -> {url}")
            else:
                seen_urls[url] = str(rel)

        date = str(meta.get("date", ""))
        if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            errors.append(f"{rel}: date が YYYY-MM-DD 形式ではありません ({date})")
        if date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.parent.name) and date != path.parent.name:
            warnings.append(f"{rel}: date ({date}) が親ディレクトリ名 ({path.parent.name}) と一致しません")

        if not meta.get("tags"):
            warnings.append(f"{rel}: tags が空です")

        if len(body) > MAX_BODY_CHARS:
            errors.append(
                f"{rel}: 本文が {len(body)} 文字あります（上限 {MAX_BODY_CHARS}）。"
                "保管庫に置くのは自作の要約のみで、元記事の全文転載は不可です。"
            )

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")

    print(f"\n{count} 本を検査 / エラー {len(errors)} 件 / 警告 {len(warnings)} 件")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
