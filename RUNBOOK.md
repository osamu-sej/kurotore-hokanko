# 朝の運用手順（Osamu さん用）

`CLAUDE.md` は Claude が読む手順書。こちらは **Osamu さんが何をするか** を書いたもの。

---

## 0. 前日までに一度だけ確認すること

明日の朝に詰まらないよう、先に 3 つ確認する。5 分で終わる。

### 0-1. 作業する場所を決める

リポジトリを触れる場所は複数あるが、**朝の取り込みは「Claude in Chrome が使える環境」でやる必要がある**。
記事本文の取得に Osamu さんのログイン済み Chrome を使うため。

| 場所 | git push | Claude in Chrome | 備考 |
| --- | --- | --- | --- |
| Mac のローカルクローン | 要認証設定 | ◯ | 朝の取り込みはここ |
| GitHub Codespace | 最初から通る | ✗（クラウド上の別環境のため） | コード修正には便利 |
| Claude Code（web/リモート） | セッションにリポジトリを紐づければ通る | ✗ | xtrend への通信も遮断されている |

**リポジトリの場所は環境によって違う。** 探すときは決め打ちせず、次で確認する。

```bash
# いまどこにいるか
pwd
# git リポジトリの中にいるか（中にいればルートが出る）
git rev-parse --show-toplevel
```

- Codespace なら `/workspaces/kurotore-hokanko`
- Mac でクローン済みなら、そのクローン先
- Mac にまだ無ければクローンする:

  ```bash
  cd ~ && git clone https://github.com/osamu-sej/kurotore-hokanko.git && cd kurotore-hokanko
  ```

### 0-2. そこから push できるか

**リポジトリの中にいる状態で**、実際には push せず通るかどうかだけ試す。

```bash
git pull origin main
git push --dry-run origin main
```

- `Everything up-to-date` と出れば **OK**。
- Codespace では最初から通ることが多い。
- Mac でユーザー名／パスワードを聞かれる、または `403` / `Authentication failed` が出たら
  Personal Access Token が必要:

  ```bash
  git config --global credential.helper osxkeychain
  # 次の push 時に ユーザー名 = osamu-sej、パスワード = トークン を入力すると保存される
  ```

### 0-3. Chrome で日経クロストレンドにログインできているか

Chrome で https://xtrend.nikkei.com/ を開き、有料会員として記事本文が読める状態か見る。
ログアウトしていると、翌朝 Claude が読める範囲が導入部だけになる。

---

## 1. 明日の朝やること

### 1-1. Claude を開く場所に注意

**Claude in Chrome が使える環境で開く。** 0-1 の表のとおり、Codespace や
Claude Code(web) では記事本文を取得できない。

作業フォルダは 0-1 で確認したリポジトリのルート。

### 1-2. 打つ言葉

```
クロトレ取り込んで
```

これだけ。`CLAUDE.md` に手順が書いてあるので、Claude は以下を順に実行する。

### 1-3. Claude がやること（Osamu さんが眺めるところ）

| # | Claude の動き | 正常なら |
| --- | --- | --- |
| 1 | `git pull origin main` | 最新に追いつく |
| 2 | 保管済み URL を一覧化 | **783 件**（8/28 時点）と出る |
| 3 | Chrome で新着一覧を開く | 日経クロストレンドの一覧が見えている |
| 4 | 2 に無い URL だけ選ぶ | 「新規 N 件」と報告してくる |
| 5 | 新規記事を開いて読み、要約を書く | `articles/2026-08-29/` にファイルが増える |
| 6 | `python3 scripts/check_articles.py` | **エラー 0 件** |
| 7 | 1 記事 1 コミットで push | `main` に反映 |

### 1-4. 終わったら確認すること

push の 1〜2 分後に開く。

**https://osamu-sej.github.io/kurotore-hokanko/**

- ページ最上部の日付が **2026年8月29日** になっているか
- 左上の「記事」の数が 783 + 今朝の件数 になっているか
- 新しい記事のカードが出ているか

ここまで出れば、取り込みから公開までが一周したことになる。

---

## 2. 詰まったときの見分け方

| 症状 | 意味 | 対処 |
| --- | --- | --- |
| `No such file or directory` でフォルダに入れない | パスの決め打ちが環境と違う | `git rev-parse --show-toplevel` でリポジトリのルートを確認する |
| `not in this session's authorized repository set` | クラウド側セッションにリポジトリが紐づいていない | ローカルのクローンまたは Codespace で作業する |
| push で `403` / `Authentication failed` | 認証が未設定 | 0-2 の手順をやる |
| 記事の本文が導入部までしか読めない | クロストレンドからログアウトしている、または日経トレンディ／エンタテインメント！の別会員限定記事 | 前者なら再ログイン。後者は仕様なので `paywalled_other_brand: true` を付けて読めた範囲だけ残す |
| `check_articles.py` が `ERROR` で止まる | 重複・必須項目欠落・本文が長すぎる | メッセージにファイル名と理由が出る。そのまま Claude に直させる |
| サイトに反映されない | Actions が失敗している | https://github.com/osamu-sej/kurotore-hokanko/actions を開いて赤いものを見る |

## 3. 記事が 1 本も無い日

新着が無ければ **何もコミットしない**。空コミットは作らない。
「新着はありませんでした」と言われたら、それで正常。
