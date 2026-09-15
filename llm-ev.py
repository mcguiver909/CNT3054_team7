"""수집한 댓글을 LLM으로 채점해 시리즈/리메이크 간 반응 비교에 쓸 표를 만든다.

원래는 뉴스의 sentiment/fairness를 재고 Supabase에서 읽어왔지만,
주제가 시리즈 영화·리메이크·시즌제 콘텐츠의 반응 비교로 바뀌면서
채점 축과 입력 경로를 함께 바꿨다.

- 입력: collect_comments.py가 만든 output/<실행폴더>/comments.csv
- 출력: 같은 폴더의 scored.csv와 summary.csv
- DB는 선택이다. --to-db를 줄 때만 Supabase에 올린다.

    ./.venv/bin/python llm-ev.py                    # 가장 최근 수집 폴더
    ./.venv/bin/python llm-ev.py --folder output/20260915_1200
    ./.venv/bin/python llm-ev.py --limit 50         # 비용 확인용 맛보기
"""

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm

BASE = Path(__file__).resolve().parent
OUTPUT_DIR = BASE / "output"

load_dotenv(BASE / ".env")
OPENAI_API_KEY = os.getenv("openai_api_key") or os.getenv("OPENAI_API_KEY")
DB_URL = os.getenv("SUPABASE_CONNECTION_STRING")

MODEL = "gpt-4o-mini"

# 시리즈 간 비교가 주제라, 감정 하나만 재면 "2편이 1편보다 별로"라는
# 핵심 신호를 놓친다. 그래서 비교 발화 여부와 무엇에 대한 반응인지를 함께 받는다.
SYSTEM_PROMPT = """You are a strict JSON generator analyzing YouTube comments about films and series.

For each input comment, return one object:
{
  "sentiment": -1.0 to 1.0,
  "aspect": one of ["story","acting","directing","action","visual","music","character","comparison","fandom","other"],
  "is_comparative": true if the comment compares this work to another entry/original/previous season, else false,
  "compares_to": short quoted mention of what it is compared to, or "" if none,
  "series_fatigue": true if it expresses tiredness with the series continuing (too many sequels, dragging on), else false,
  "notes": "very brief reason, max 15 chars"
}

sentiment: -1 very negative, 0 neutral, +1 very positive.
Judge only what the comment says. Do not infer beyond the text.
Comments are mostly Korean. Return a JSON object: {"results": [ ... ]} with one element per input, in order."""


def find_folder(arg_folder):
    """분석할 수집 폴더를 정한다. 지정이 없으면 가장 최근 것."""
    if arg_folder:
        folder = Path(arg_folder)
        if not folder.is_absolute():
            folder = BASE / folder
        if not (folder / "comments.csv").exists():
            raise SystemExit(f"comments.csv가 없습니다: {folder}")
        return folder

    if not OUTPUT_DIR.exists():
        raise SystemExit(
            "output 폴더가 없습니다. 먼저 collect_comments.py로 댓글을 수집하세요."
        )
    candidates = sorted(
        (p for p in OUTPUT_DIR.iterdir() if (p / "comments.csv").exists()),
        key=lambda p: p.name,
    )
    if not candidates:
        raise SystemExit(
            "수집 결과가 없습니다. 먼저 collect_comments.py로 댓글을 수집하세요."
        )
    return candidates[-1]


def analyze_batch(client, texts):
    """댓글 묶음 하나를 채점한다. 실패하면 중립값으로 자리를 채운다."""
    numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(texts))
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": numbered},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        results = data.get("results", [])
    except Exception as exc:
        print(f"  [경고] 배치 채점 실패: {exc}", file=sys.stderr)
        results = []

    # 개수가 어긋나면 행이 밀린다. 잘라내거나 채워서 입력과 길이를 맞춘다.
    blank = {"sentiment": 0, "aspect": "other", "is_comparative": False,
             "compares_to": "", "series_fatigue": False, "notes": "parse_error"}
    results = results[:len(texts)]
    results += [dict(blank) for _ in range(len(texts) - len(results))]
    return results


def score_dataframe(client, df, batch_size=10):
    rows = []
    for i in tqdm(range(0, len(df), batch_size), desc="채점"):
        batch = df.iloc[i:i + batch_size]
        for res in analyze_batch(client, batch["text_raw"].tolist()):
            rows.append({
                "sentiment": res.get("sentiment", 0),
                "aspect": res.get("aspect", "other"),
                "is_comparative": bool(res.get("is_comparative", False)),
                "compares_to": res.get("compares_to", ""),
                "series_fatigue": bool(res.get("series_fatigue", False)),
                "notes": res.get("notes", ""),
            })

    scored = df.reset_index(drop=True).join(pd.DataFrame(rows))
    return scored


def summarize(scored):
    """라벨·편별로 묶어 비교표를 만든다."""
    return (
        scored.groupby(["label", "entry", "video_id"], dropna=False)
        .agg(
            n=("comment_id", "count"),
            sentiment_avg=("sentiment", "mean"),
            positive_ratio=("sentiment", lambda s: (s > 0.2).mean()),
            negative_ratio=("sentiment", lambda s: (s < -0.2).mean()),
            comparative_ratio=("is_comparative", "mean"),
            fatigue_ratio=("series_fatigue", "mean"),
            like_avg=("like_count", "mean"),
        )
        .round(3)
        .reset_index()
    )


def insert_scores(scored, folder):
    """선택 단계: Supabase에 채점 결과를 올린다."""
    import psycopg2
    from psycopg2.extras import execute_values

    if not DB_URL:
        raise SystemExit(".env에 SUPABASE_CONNECTION_STRING이 없습니다.")

    conn = psycopg2.connect(DB_URL, sslmode="require", connect_timeout=10)
    with conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS comment_scores (
                comment_id     TEXT PRIMARY KEY,
                video_id       TEXT,
                label          TEXT,
                entry          TEXT,
                text_raw       TEXT,
                published_at   TIMESTAMPTZ,
                like_count     INTEGER,
                sentiment      DOUBLE PRECISION,
                aspect         TEXT,
                is_comparative BOOLEAN,
                compares_to    TEXT,
                series_fatigue BOOLEAN,
                notes          TEXT,
                created_at     TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cols = ["comment_id", "video_id", "label", "entry", "text_raw",
                "published_at", "like_count", "sentiment", "aspect",
                "is_comparative", "compares_to", "series_fatigue", "notes"]
        rows = list(scored[cols].itertuples(index=False, name=None))
        # 같은 폴더를 두 번 올려도 행이 늘지 않는다.
        execute_values(cur, f"""
            INSERT INTO comment_scores ({", ".join(cols)}) VALUES %s
            ON CONFLICT (comment_id) DO NOTHING
        """, rows)
    conn.close()
    print(f"DB 저장 완료: comment_scores {len(rows)}행 시도 (중복은 건너뜀)")


def main():
    parser = argparse.ArgumentParser(description="수집한 댓글을 LLM으로 채점")
    parser.add_argument("--folder", help="분석할 수집 폴더 (생략 시 가장 최근)")
    parser.add_argument("--limit", type=int, help="앞에서 N개만 채점 (비용 확인용)")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--to-db", action="store_true", help="Supabase에도 저장")
    args = parser.parse_args()

    if not OPENAI_API_KEY:
        raise SystemExit(
            ".env에 openai_api_key가 없습니다.\n"
            "platform.openai.com에서 발급한 뒤 .env에 추가하세요."
        )

    folder = find_folder(args.folder)
    df = pd.read_csv(folder / "comments.csv")
    df = df[df["text_raw"].notna() & (df["text_raw"].str.strip() != "")]
    if args.limit:
        df = df.head(args.limit)

    if df.empty:
        raise SystemExit(f"채점할 댓글이 없습니다: {folder / 'comments.csv'}")

    print(f"대상 폴더: {folder}")
    print(f"채점할 댓글: {len(df)}행 / 모델: {MODEL}")

    client = OpenAI(api_key=OPENAI_API_KEY)
    scored = score_dataframe(client, df, args.batch_size)

    scored_path = folder / "scored.csv"
    scored.to_csv(scored_path, index=False, encoding="utf-8-sig")

    summary = summarize(scored)
    summary_path = folder / "summary.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    print(f"\n저장 완료")
    print(f"  {scored_path}   {len(scored)}행")
    print(f"  {summary_path}")
    print()
    print(summary.to_string(index=False))

    if args.to_db:
        insert_scores(scored, folder)


if __name__ == "__main__":
    main()
