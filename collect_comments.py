"""여러 YouTube 영상의 최상위 댓글을 라벨과 함께 한 데이터셋으로 수집한다.

시리즈 영화·리메이크·시즌제 콘텐츠의 반응을 비교하려면 영상 1편이 아니라
여러 편을 같은 기준으로 모아야 한다. 그래서 각 영상에 label(시리즈명)과
entry(1편/2편, 원작/리메이크 같은 비교 축)를 붙여 하나의 CSV로 저장한다.

    # 연결 확인
    ./.venv/bin/python collect_comments.py --video "URL" --check

    # 한 편만
    ./.venv/bin/python collect_comments.py --video "URL" --max-pages 3

    # 여러 편 비교 (권장)
    ./.venv/bin/python collect_comments.py --manifest videos.json --max-pages 5
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

BASE = Path(__file__).resolve().parent
OUTPUT_DIR = BASE / "output"

# 1차 시행 대상. --video로 언제든 덮어쓸 수 있다.
DEFAULT_VIDEO = "https://youtu.be/lekS3GR1jps"
DEFAULT_LABEL = "마블"
DEFAULT_ENTRY = "몰아보기"

COLUMNS = [
    "label",         # 비교 그룹 (예: "아이언맨", "올드보이")
    "entry",         # 그룹 안의 위치 (예: "1편", "원작", "시즌3")
    "video_id",
    "video_title",
    "comment_id",
    "author",
    "text_raw",
    "published_at",
    "updated_at",
    "like_count",
    "reply_count",
    "collected_at",
]


def parse_video_id(value):
    """영상 URL 또는 ID 문자열에서 video_id만 꺼낸다."""
    value = value.strip()

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    # youtu.be/<id>, /watch?v=<id>, /shorts/<id>, /live/<id>, /embed/<id>
    patterns = [
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"[?&]v=([A-Za-z0-9_-]{11})",
        r"/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        found = re.search(pattern, value)
        if found:
            return found.group(1)

    raise ValueError(f"영상 ID를 찾을 수 없습니다: {value}")


def load_targets(args):
    """--manifest 또는 --video에서 수집 대상 목록을 만든다."""
    targets = []

    if args.manifest:
        path = Path(args.manifest)
        if not path.is_absolute():
            path = BASE / path
        if not path.exists():
            raise SystemExit(f"manifest 파일이 없습니다: {path}")

        entries = json.loads(path.read_text(encoding="utf-8"))
        for entry in entries:
            targets.append({
                "video_id": parse_video_id(entry["url"]),
                "label": entry.get("label", ""),
                "entry": entry.get("entry", ""),
            })

    for url in args.video or []:
        targets.append({
            "video_id": parse_video_id(url),
            "label": args.label,
            "entry": args.entry,
        })

    # --video도 --manifest도 없으면 1차 시행 대상 한 편을 쓴다.
    if not targets:
        targets.append({
            "video_id": parse_video_id(DEFAULT_VIDEO),
            "label": args.label or DEFAULT_LABEL,
            "entry": args.entry or DEFAULT_ENTRY,
        })
    return targets


def make_youtube_client():
    """.env의 키로 YouTube API 요청 객체를 만든다."""
    load_dotenv(BASE / ".env")
    api_key = os.getenv("google_cloud_api_key")

    if not api_key:
        raise SystemExit(
            ".env에서 google_cloud_api_key를 찾을 수 없습니다.\n"
            f"확인할 파일: {BASE / '.env'}"
        )
    if not api_key.startswith("AIza"):
        print(
            f"[경고] 키가 'AIza'로 시작하지 않습니다 (현재: {api_key[:4]}...).\n"
            "       YouTube Data API v3는 Google Cloud 콘솔에서 만든 API 키를 요구합니다.\n"
            "       401 'API keys are not supported' 오류가 나면 키부터 다시 발급하세요.",
            file=sys.stderr,
        )

    return build("youtube", "v3", developerKey=api_key)


def get_video_info(youtube, video_id):
    """영상의 제목·채널·공개일·통계를 조회한다."""
    response = youtube.videos().list(
        part="snippet,statistics",
        id=video_id,
    ).execute()

    items = response.get("items", [])
    if not items:
        raise SystemExit(f"영상을 찾을 수 없습니다: {video_id} (비공개이거나 삭제된 영상)")

    snippet = items[0]["snippet"]
    stats = items[0].get("statistics", {})
    return {
        "video_id": video_id,
        "title": snippet["title"],
        "channel_title": snippet["channelTitle"],
        "published_at": snippet["publishedAt"],
        "view_count": stats.get("viewCount"),
        "like_count": stats.get("likeCount"),
        "comment_count": stats.get("commentCount"),
    }


def parse_comment(item, target, video_title, collected_at):
    """댓글 스레드 1개를 CSV 한 행으로 바꾼다."""
    top = item["snippet"]["topLevelComment"]
    comment = top["snippet"]

    return {
        "label": target["label"],
        "entry": target["entry"],
        "video_id": target["video_id"],
        "video_title": video_title,
        "comment_id": top["id"],
        "author": comment["authorDisplayName"],
        "text_raw": comment["textDisplay"],
        "published_at": comment["publishedAt"],
        "updated_at": comment.get("updatedAt"),
        "like_count": comment["likeCount"],
        "reply_count": item["snippet"]["totalReplyCount"],
        "collected_at": collected_at,
    }


def collect_comments(youtube, target, video_title, max_pages, seen, since_days=None):
    """영상 1편에 대해 페이지 상한까지 반복하며 최상위 댓글을 모은다.

    seen은 여러 영상에 걸쳐 공유하는 집합이라, 같은 댓글이 두 번 저장되지 않는다.
    """
    collected_at = datetime.now(timezone.utc).isoformat()
    cutoff = None
    if since_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    rows = []
    page_token = None
    pages_received = 0
    stop_reason = "page_limit"
    duplicates = 0
    filtered_out = 0

    for _ in range(max_pages):
        try:
            response = youtube.commentThreads().list(
                part="snippet",
                videoId=target["video_id"],
                maxResults=100,
                order="time",
                textFormat="plainText",
                pageToken=page_token,
            ).execute()
        except HttpError as exc:
            stop_reason = "error"
            print(f"  [오류] 댓글 조회 실패: {exc}", file=sys.stderr)
            print(f"         그 전까지 받은 {len(rows)}행만 저장합니다.", file=sys.stderr)
            break

        pages_received += 1
        reached_cutoff = False

        for item in response.get("items", []):
            row = parse_comment(item, target, video_title, collected_at)

            # order="time"이라 최신순이다. 기준일보다 오래된 댓글이 나오면 그 뒤는 볼 필요가 없다.
            if cutoff is not None:
                written = datetime.fromisoformat(
                    row["published_at"].replace("Z", "+00:00")
                )
                if written < cutoff:
                    filtered_out += 1
                    reached_cutoff = True
                    continue

            if row["comment_id"] in seen:
                duplicates += 1
                continue
            seen.add(row["comment_id"])
            rows.append(row)

        print(f"  페이지 {pages_received}: 이 영상 누적 {len(rows)}행")

        if reached_cutoff:
            stop_reason = "since_days_reached"
            break

        page_token = response.get("nextPageToken")
        if not page_token:
            stop_reason = "no_next_page"
            break

    log = {
        "label": target["label"],
        "entry": target["entry"],
        "video_id": target["video_id"],
        "pages_received": pages_received,
        "stop_reason": stop_reason,
        "has_more": bool(page_token) and stop_reason == "page_limit",
        "rows_saved": len(rows),
        "duplicates_skipped": duplicates,
        "filtered_out_by_since_days": filtered_out,
    }
    return rows, log


def save_results(rows, logs, run_conditions):
    """comments.csv와 collection_log.json을 이번 실행 폴더에 저장한다."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = OUTPUT_DIR / stamp
    folder.mkdir(parents=True, exist_ok=True)

    csv_path = folder / "comments.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    log_path = folder / "collection_log.json"
    with log_path.open("w", encoding="utf-8") as f:
        json.dump(
            {"run": run_conditions, "videos": logs},
            f, ensure_ascii=False, indent=2,
        )

    return folder


def main():
    parser = argparse.ArgumentParser(
        description="여러 YouTube 영상의 최상위 댓글을 라벨과 함께 수집"
    )
    parser.add_argument("--video", action="append",
                        help=f"영상 URL 또는 11자리 ID (여러 번 지정 가능). "
                             f"생략하면 {DEFAULT_VIDEO}")
    parser.add_argument("--manifest",
                        help='[{"label":..., "entry":..., "url":...}] 형식의 JSON 파일')
    parser.add_argument("--label", default="", help="--video에 붙일 비교 그룹 이름")
    parser.add_argument("--entry", default="", help="--video에 붙일 그룹 내 위치")
    parser.add_argument("--check", action="store_true",
                        help="API 연결과 영상 정보만 확인하고 종료")
    parser.add_argument("--max-pages", type=int, default=1,
                        help="영상당 요청할 최대 페이지 수 (한 페이지 최대 100개)")
    parser.add_argument("--since-days", type=int, default=None,
                        help="최근 N일 이내 댓글만 수집")
    args = parser.parse_args()

    targets = load_targets(args)
    youtube = make_youtube_client()

    # 먼저 전부 조회해서, 잘못된 링크가 있으면 수집 전에 알아차린다.
    infos = {}
    for target in targets:
        info = get_video_info(youtube, target["video_id"])
        infos[target["video_id"]] = info
        tag = f"[{target['label']} {target['entry']}]".strip(" []")
        prefix = f"{tag} " if tag else ""
        print(f"{prefix}{info['channel_title']} / {info['title']}")
        print(f"  공개일 {info['published_at']} · 조회수 {info['view_count']} "
              f"· 댓글 {info['comment_count']}")

    print(f"\nAPI 연결 및 영상 {len(targets)}편 조회 성공")
    if args.check:
        return

    all_rows = []
    logs = []
    seen = set()

    for target in targets:
        info = infos[target["video_id"]]
        print(f"\n수집: {info['title']} (최대 {args.max_pages}페이지)")
        rows, log = collect_comments(
            youtube, target, info["title"], args.max_pages, seen, args.since_days
        )
        log["video"] = info
        all_rows.extend(rows)
        logs.append(log)

    run_conditions = {
        "order": "time",
        "max_results_per_page": 100,
        "max_pages": args.max_pages,
        "since_days": args.since_days,
        "top_level_only": True,
        "reply_bodies_included": False,
        "videos_requested": len(targets),
        "total_rows": len(all_rows),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }

    folder = save_results(all_rows, logs, run_conditions)
    print(f"\n저장 완료: {folder}")
    print(f"  comments.csv         총 {len(all_rows)}행 / 영상 {len(targets)}편")
    for log in logs:
        tag = f"{log['label']} {log['entry']}".strip() or log["video_id"]
        print(f"    - {tag}: {log['rows_saved']}행, "
              f"stop_reason={log['stop_reason']}, has_more={log['has_more']}")
    print("  collection_log.json  수집 조건과 영상별 종료 이유")


if __name__ == "__main__":
    main()
