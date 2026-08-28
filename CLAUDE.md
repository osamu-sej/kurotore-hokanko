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

**取り込みの経路は 2 つあり、使える道具が違う。まずどちらにいるか判断すること。**

### 経路A: Mac の Claude デスクトップアプリ（通常の朝はこちら）

記事の取得に Claude in Chrome を使い、書き込みは GitHub コネクタ（API）で行う。
**ローカルにリポジトリのファイルは無い。** `git` コマンドも `python3` も使えない前提で動くこと。

1. 取得済み URL を調べる。Chrome で次を開き、`urls` 配列を見る。

   https://osamu-sej.github.io/kurotore-hokanko/index.json

   これは公開サイトが持つ全記事の索引で、保管済み URL が全部入っている。
   （前回の push から 1〜2 分は反映にラグがあるので、直後の再実行では GitHub 上の
   `articles/` を直接見て確認する）

2. Chrome で日経クロストレンドの新着一覧を開き、**1 に無い URL だけ**を対象にする。
3. 対象記事を開いて読み、下の書式で本文を組み立てる。
4. GitHub コネクタで `articles/YYYY-MM-DD/<記事ID>.md` を **1 記事ずつ**作成する。
   1 ファイル 1 コミット。コミットメッセージは記事の内容が分かるものにする。
5. **検査はローカルで走らせられないので、GitHub Actions に任せる。**
   push 後に自動で `check_articles.py` が走る。数分後に次を開いて緑になっているか確認する。

   https://github.com/osamu-sej/kurotore-hokanko/actions

   赤い場合はログに「どのファイルの何が悪いか」が出るので、それを直して再度書き込む。

### 経路B: ローカルのクローン / Codespace（コードを直すとき）

`git` と `python3` が使える。リポジトリのルートは `git rev-parse --show-toplevel` で確認する。

1. `git pull origin main` で最新化する。
2. 取得済み URL の一覧を出す:
   `grep -rh '^url:' articles/ | sed 's/url: *"//; s/"$//' | sort`
3. （Claude in Chrome が使えないので、記事の取得はできない。
   記事を足す場合は経路A で取得した内容を持ち込む）
4. `articles/YYYY-MM-DD/<記事ID>.md` を作る。
5. `python3 scripts/check_articles.py` を通す。**ここでエラーが出たら push しない。**
6. 1 記事 1 コミットで `main` に push する。

### 両方に共通するルール

- `YYYY-MM-DD` は記事の公開日（＝取り込んだ日）。
- `<記事ID>` は **URL から機械的に導く**。`/atcl/contents/` の後ろをハイフンで繋ぐ。
  `.../atcl/contents/18/01432/00006/` → `18-01432-00006.md`
  `.../atcl/contents/casestudy/00001/00023/` → `casestudy-00001-00023.md`
  `/atcl/contents/` 以外（`/atcl/seminar/…` など）は `/atcl/` の後ろを使う → `seminar-19-00075-00025.md`
- 連番を数えたり英語スラッグを考えたりしない。同じ記事なら常に同じファイル名になるので、
  取り込みを二度走らせても増殖しない。
- `order` はその日の新着一覧での並び順を 0 始まりで入れる。サイト上の表示順に使う。
- **重複の判定は必ず `url` で行う。** ファイル名や連番で見ない。
- 新着が無ければ何もコミットしない。空コミットは作らない。

push されると Pages が自動更新され、1〜2 分で公開サイトに反映される。

## 記事ファイルの書式

```markdown
---
title: "記事タイトル（全角スペースもそのまま）"
url: "https://xtrend.nikkei.com/atcl/contents/18/01432/00006/"
series: "シリーズ名（第6回／全6回）"      # 無ければ空文字か省略
category: "マーケ・消費"                   # 記事ページ上部のカテゴリ
date: 2026-08-28
order: 0                                   # その日の中での掲載順（0 始まり）
fetched_via: "claude-in-chrome"
tags: ["マーケ", "運輸", "ブランド価値向上"]   # 記事ページのタグに合わせる。空にしない
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
| `scripts/build_site.py` | `site/` に静的サイトを生成（トップ＝直近80本＋月別ナビ＋検索、`m/YYYY-MM.html`＝月別、`a/<記事ID>.html`＝記事ごと） |
| `scripts/check_articles.py` | 必須項目・URL 重複・本文長を検査 |

`articles/` 配下の `.md` は例外なく検査対象になる。除外される名前は無いので、
記事以外のメモを置きたい場合は `articles/` の外に置くこと。
| `.github/workflows/deploy.yml` | `main` への push でビルドして Pages へデプロイ |

ローカル確認:

```bash
python3 scripts/check_articles.py
python3 scripts/build_site.py
python3 -m http.server -d site 8000   # http://localhost:8000
```

`site/` はビルド生成物なのでコミットしない（`.gitignore` 済み）。

## 記事数の規模について

2026-01-05 以降の 783 本はアーティファクト版保管庫から一括移行したもので、
移行分は `fetched_via: "artifact-migration"` で識別できる。1 日あたり最大 14 本のペースで増えるため、
トップページは全件を並べず「直近 80 本＋月別アーカイブ＋検索」の形にしてある。
検索は `index.json`（全件の索引）を検索欄にフォーカスした時点で初めて取得する遅延読み込みなので、
記事が数千本になってもトップページ自体は軽いまま保たれる。
