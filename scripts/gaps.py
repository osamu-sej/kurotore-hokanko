#!/usr/bin/env python3
"""取り込みの抜けを一覧する。

朝の取り込みが止まっていると抜けが静かに積み上がる（2026-08 に実際に起きた）。
いつでも `python3 scripts/gaps.py` で現状と埋め戻しの進捗を確認できるようにしておく。

週末と祝日は日経クロストレンドの更新が無いので対象外にする。
祝日は下の HOLIDAYS を手で足す（間違っていたら直してよい）。
"""

from __future__ import annotations

import collections
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_site import load_articles  # noqa: E402

WD = "月火水木金土日"

# 日本の祝日。ここに無い日は営業日として扱う。
HOLIDAYS = {
    "2026-01-01", "2026-01-12",              # 元日 / 成人の日
    "2026-02-11", "2026-02-23",              # 建国記念の日 / 天皇誕生日
    "2026-03-20",                            # 春分の日
    "2026-04-29",                            # 昭和の日
    "2026-05-03", "2026-05-04", "2026-05-05", "2026-05-06",   # 憲法記念日〜振替休日
    "2026-07-20",                            # 海の日
    "2026-08-11",                            # 山の日
    "2026-09-21", "2026-09-22", "2026-09-23",
    "2026-10-12", "2026-11-03", "2026-11-23",
}

# 取り込みが止まっていた既知の期間（バグではない。CLAUDE.md 参照）
KNOWN_GAP = (datetime.date(2026, 8, 3), datetime.date(2026, 8, 25))


def is_workday(d: datetime.date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def main() -> int:
    counts = collections.Counter(a["date"] for a in load_articles())
    if not counts:
        print("記事がありません")
        return 0

    days = sorted(counts)
    start, end = (datetime.date.fromisoformat(days[0]), datetime.date.fromisoformat(days[-1]))

    workdays, known, other = [], [], []
    d = start
    while d <= end:
        if is_workday(d):
            n = counts.get(d.isoformat(), 0)
            workdays.append(n)
            if n == 0:
                (known if KNOWN_GAP[0] <= d <= KNOWN_GAP[1] else other).append(d)
        d += datetime.timedelta(days=1)

    median = sorted(workdays)[len(workdays) // 2]
    print(f"期間 {days[0]} 〜 {days[-1]}   総数 {sum(counts.values())} 本")
    print(f"営業日 {len(workdays)} 日（週末・祝日を除く）   中央値 {median} 本/日\n")

    # 既知の停止期間 — 埋め戻し対象
    span = [KNOWN_GAP[0] + datetime.timedelta(days=i)
            for i in range((KNOWN_GAP[1] - KNOWN_GAP[0]).days + 1)]
    span = [d for d in span if is_workday(d)]
    filled = [d for d in span if counts.get(d.isoformat(), 0) > 0]
    print(f"■ 埋め戻し（{KNOWN_GAP[0]}〜{KNOWN_GAP[1]} の取り込み停止期間）")
    print(f"    営業日 {len(span)} 日中 {len(filled)} 日に着手済み / 残り {len(span)-len(filled)} 日")
    for d in span:
        n = counts.get(d.isoformat(), 0)
        mark = "済" if n >= median else ("途中" if n else "未")
        print(f"    {d} ({WD[d.weekday()]})  {n:2d} 件  {mark}")
    todo = [d for d in span if counts.get(d.isoformat(), 0) < median]
    if todo:
        print(f"\n    次に着手するなら {todo[0]} ({WD[todo[0].weekday()]})")

    # 停止期間の外で 0 件の営業日 — 想定外の抜け
    print(f"\n■ 上記以外で 0 件の営業日: {len(other)} 日")
    for d in other:
        print(f"    {d} ({WD[d.weekday()]})")
    if not other:
        print("    なし")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:      # head などで打ち切られたとき
        raise SystemExit(0)
