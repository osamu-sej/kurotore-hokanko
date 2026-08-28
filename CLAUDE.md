# クロトレ保管庫

日経クロストレンド（xtrend.nikkei.com）で読んだ記事を、**タイトル・出典リンク・自作の要約・タグ**だけで
保管するアーカイブ。公開リポジトリなので、記事本文は絶対に転載しない。

公開先: GitHub Pages（`main` に push されると自動でビルド・デプロイされる）

## 原則

1. **本文は載せない。** 置いてよいのは自分の言葉での要約（数百字程度）とメタデータのみ。
   末尾は必ず `（全文は元記事を参照）` で締める。CI が本文 3000 字超で失敗する。
2. **重複の判定は `url`。** ファイル名や連番ではなく URL で見る。CI が重複を検出して失敗する。
3. **取得は Claude in Chrome 経由。** Osamu さんのログイン済みブラウザで、購読者として読める範囲だけを扱う。
   認証情報を使った自動スクレイピングはしない。

## 毎朝の取り込み手順

「クロトレ取り込んで」の一言でこの手順を実行する。

1. `git pull origin main` で最新化する。
2. 取得済み URL の一覧を出す:
   `grep -rh '^url:' articles/ | sed 's/url: *"//; s/"$//' | sort`
   （公開サイトの `index.json` の `urls` でも同じものが取れる）
3. Claude in Chrome で日経クロストレンドの新着一覧を開き、**2 に無い URL だけ**を対象にする。
4. 対象記事を開いて読み、下の書式で `articles/YYYY-MM-DD/NN-slug.md` を作る。
   - `YYYY-MM-DD` は取り込んだ日。
   - `NN` はそのディレクトリ内の既存の最大番号 + 1（同じ日に 2 回走らせても衝突しない）。
   - `slug` は内容が分かる短い英小文字ハイフン区切り。
5. `python3 scripts/check_articles.py` を通す。
6. 1 記事 1 コミットで `main` に push する。push されると Pages が自動更新される。

新着が無ければ何もコミットしない。空コミットは作らない。

## 記事ファイルの書式

```markdown
---
title: "記事タイトル（全角スペースもそのまま）"
url: "https://xtrend.nikkei.com/atcl/contents/18/01432/00006/"
series: "シリーズ名（第6回／全6回）"      # 無ければ空文字か省略
date: 2026-08-28
fetched_via: claude-in-chrome
tags: [マーケ, 運輸, ブランド価値向上]     # 記事ページのタグに合わせる。空にしない
---

# 記事タイトル

3〜6 文程度の要約。何を論じた記事かが分かること。

（全文は元記事を参照）
```

日経トレンディ電子版・日経エンタテインメント！電子版など**別ブランドの有料会員限定**で
本文が読めなかった場合は、次の 2 項目を足したうえで、読めた範囲だけを引用ブロックで要約する。

```yaml
paywalled_other_brand: true
paywall_note: "日経トレンディ電子版有料会員限定のため導入部のみで本文が取得できず"
```

## サイトの構成

| パス | 役割 |
| --- | --- |
| `articles/YYYY-MM-DD/*.md` | 記事の実体（唯一の情報源） |
| `scripts/build_site.py` | `site/` に静的サイトを生成 |
| `scripts/check_articles.py` | 必須項目・URL 重複・本文長を検査 |
| `.github/workflows/deploy.yml` | `main` への push でビルドして Pages へデプロイ |

ローカル確認:

```bash
python3 scripts/check_articles.py
python3 scripts/build_site.py
python3 -m http.server -d site 8000   # http://localhost:8000
```

`site/` はビルド生成物なのでコミットしない（`.gitignore` 済み）。
