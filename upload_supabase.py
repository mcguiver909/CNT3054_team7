"""collect_comments.py가 만든 수집 폴더를 Supabase PostgreSQL에 올린다.

원본 data_scrape.py는 수집과 저장이 한 함수 안에 붙어 있어서, 수집을 다시
하지 않으면 저장도 다시 할 수 없었다. 여기서는 CSV를 읽어 올리기만 하므로
같은 폴더를 몇 번 올려도 되고, API 호출도 더 들지 않는다.

테이블 이름은 원본의 videos/comments와 구분하려고 lab_ 접두사를 쓴다.

    ./.venv/bin/python upload_supabase.py --check-db     # 연결만 확인
    ./.venv/bin/python upload_supabase.py --init-db      # 테이블 생성
    ./.venv/bin/python upload_supabase.py                # 최근 폴더 업로드
    ./.venv/bin/python upload_supabase.py --folder output/20260915_161353
    ./.venv/bin/python upload_supabase.py --count        # 저장 건수 조회
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

BASE = Path(__file__).resolve().parent
OUTPUT_DIR = BASE / "output"

load_dotenv(BASE / ".env")
DB_URL = os.getenv("SUPABASE_CONNECTION_STRING")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lab_videos (
    video_id      TEXT PRIMARY KEY,
    title         TEXT,
    channel_title TEXT,
    label         TEXT,
    entry         TEXT,
    published_at  TIMESTAMPTZ,
    view_count    BIGINT,
    comment_count BIGINT,
    collected_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS lab_comments (
    comment_id   TEXT PRIMARY KEY,
    video_id     TEXT NOT NULL REFERENCES lab_videos(video_id),
    author       TEXT,
    text_raw     TEXT,
    published_at TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ,
    like_count   INTEGER,
    reply_count  INTEGER,
    collected_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS lab_comments_video_id_idx ON lab_comments (video_id);

-- RLS를 켜고 정책을 만들지 않으면, 공개 API 키로는 아무 행도 읽히지 않는다.
-- 우리 코드는 DB 비밀번호로 직접 붙기 때문에 영향을 받지 않는다.
ALTER TABLE lab_videos   ENABLE ROW LEVEL SECURITY;
ALTER TABLE lab_comments ENABLE ROW LEVEL SECURITY;
"""


def connect_db():
    if not DB_URL:
        raise SystemExit(
            ".env에 SUPABASE_CONNECTION_STRING이 없습니다.\n"
            "Supabase 콘솔 Connect > URI > Session pooler에서 복사하세요."
        )
    return psycopg2.connect(DB_URL, sslmode="require", connect_timeout=10)


def find_folder(arg_folder):
    """업로드할 수집 폴더를 정한다. 지정이 없으면 가장 최근 것."""
    if arg_folder:
        folder = Path(arg_folder)
        if not folder.is_absolute():
            folder = BASE / folder
    else:
        if not OUTPUT_DIR.exists():
            raise SystemExit("output 폴더가 없습니다. 먼저 collect_comments.py를 실행하세요.")
        candidates = sorted(
            (p for p in OUTPUT_DIR.iterdir() if (p / "comments.csv").exists()),
            key=lambda p: p.name,
        )
        if not candidates:
            raise SystemExit("수집 결과가 없습니다. 먼저 collect_comments.py를 실행하세요.")
        folder = candidates[-1]

    if not (folder / "comments.csv").exists():
        raise SystemExit(f"comments.csv가 없습니다: {folder}")
    return folder


def read_batch(folder):
    """CSV와 로그를 읽어 영상 목록과 댓글 행으로 나눈다."""
    with (folder / "comments.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    log_path = folder / "collection_log.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}

    # 로그에 영상 메타데이터(채널명·조회수)가 들어 있다. CSV만으로는 알 수 없다.
    info_by_id = {}
    for entry in log.get("videos", []):
        info = entry.get("video", {})
        if info.get("video_id"):
            info_by_id[info["video_id"]] = {
                "channel_title": info.get("channel_title"),
                "published_at": info.get("published_at"),
                "view_count": info.get("view_count"),
                "comment_count": info.get("comment_count"),
                "label": entry.get("label", ""),
                "entry": entry.get("entry", ""),
            }

    videos = {}
    for row in rows:
        vid = row["video_id"]
        if vid in videos:
            continue
        extra = info_by_id.get(vid, {})
        videos[vid] = (
            vid,
            row.get("video_title"),
            extra.get("channel_title"),
            row.get("label") or extra.get("label"),
            row.get("entry") or extra.get("entry"),
            extra.get("published_at"),
            extra.get("view_count"),
            extra.get("comment_count"),
            row.get("collected_at"),
        )

    def as_int(value):
        return int(value) if value not in (None, "") else None

    comments = [
        (
            row["comment_id"],
            row["video_id"],
            row.get("author"),
            row.get("text_raw"),
            row.get("published_at"),
            row.get("updated_at") or None,
            as_int(row.get("like_count")),
            as_int(row.get("reply_count")),
            row.get("collected_at"),
        )
        for row in rows
    ]
    return list(videos.values()), comments


def init_db(conn):
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()
    print("테이블 준비 완료: lab_videos, lab_comments (RLS 켜짐)")


def insert_batch(conn, videos, comments):
    """영상을 먼저 넣고 댓글을 넣는다. 외래키 때문에 순서가 중요하다."""
    with conn.cursor() as cur:
        # execute_values는 기본 100행씩 나눠 보내고 rowcount는 마지막 묶음만 센다.
        # 그래서 실제로 몇 행이 늘었는지는 전후 건수를 비교해서 구한다.
        cur.execute("SELECT count(*) FROM lab_comments")
        before = cur.fetchone()[0]

        execute_values(cur, """
            INSERT INTO lab_videos
                (video_id, title, channel_title, label, entry,
                 published_at, view_count, comment_count, collected_at)
            VALUES %s
            ON CONFLICT (video_id) DO UPDATE SET
                title = EXCLUDED.title,
                view_count = EXCLUDED.view_count,
                comment_count = EXCLUDED.comment_count
        """, videos)

        # 같은 폴더를 다시 올려도 comment_id가 같으면 행이 늘지 않는다.
        execute_values(cur, """
            INSERT INTO lab_comments
                (comment_id, video_id, author, text_raw,
                 published_at, updated_at, like_count, reply_count, collected_at)
            VALUES %s
            ON CONFLICT (comment_id) DO NOTHING
        """, comments)

        cur.execute("SELECT count(*) FROM lab_comments")
        after = cur.fetchone()[0]
    conn.commit()
    return after - before


def show_counts(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT v.video_id, v.label, v.entry, v.title,
                   count(c.comment_id) AS comments
            FROM lab_videos AS v
            LEFT JOIN lab_comments AS c ON c.video_id = v.video_id
            GROUP BY v.video_id, v.label, v.entry, v.title
            ORDER BY comments DESC
        """)
        rows = cur.fetchall()
        cur.execute("SELECT count(*) FROM lab_comments")
        total = cur.fetchone()[0]

    print(f"\n{'video_id':<14} {'label':<8} {'entry':<10} {'댓글':>6}  title")
    print("-" * 78)
    for vid, label, entry, title, n in rows:
        title = (title or "")[:30]
        print(f"{vid:<14} {label or '':<8} {entry or '':<10} {n:>6}  {title}")
    print("-" * 78)
    print(f"lab_comments 총 {total}행 / lab_videos {len(rows)}행")


def main():
    parser = argparse.ArgumentParser(description="수집 폴더를 Supabase에 업로드")
    parser.add_argument("--folder", help="업로드할 수집 폴더 (생략 시 가장 최근)")
    parser.add_argument("--check-db", action="store_true", help="연결만 확인")
    parser.add_argument("--init-db", action="store_true", help="테이블 생성")
    parser.add_argument("--count", action="store_true", help="저장 건수만 조회")
    args = parser.parse_args()

    conn = connect_db()

    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user")
        db, user = cur.fetchone()
    print(f"DB 연결 성공 / database: {db} / user: {user}")

    if args.check_db:
        conn.close()
        return

    if args.init_db:
        init_db(conn)
        conn.close()
        return

    if args.count:
        show_counts(conn)
        conn.close()
        return

    folder = find_folder(args.folder)
    videos, comments = read_batch(folder)
    print(f"읽은 폴더: {folder}")
    print(f"  영상 {len(videos)}편 / 댓글 {len(comments)}행")

    try:
        inserted = insert_batch(conn, videos, comments)
    except psycopg2.Error as exc:
        conn.rollback()
        conn.close()
        raise SystemExit(f"저장 실패, 롤백했습니다: {exc}")

    print(f"저장 완료: 새로 추가된 댓글 {inserted}행 "
          f"(중복 {len(comments) - inserted}행은 건너뜀)")
    show_counts(conn)
    conn.close()


if __name__ == "__main__":
    main()
