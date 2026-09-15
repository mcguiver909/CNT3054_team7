# CNT3054 7조 — 시리즈 콘텐츠 유튜브 댓글 반응 분석

문화콘텐츠와 자연어처리(CNT3054) 팀 프로젝트 저장소입니다.
YouTube 댓글을 수집해 Supabase(PostgreSQL)에 저장하고, 시리즈·리메이크·시즌제 콘텐츠에 대한 반응 차이를 분석합니다.

수업 실습 코드의 원본은 [111usionBin/jtbc-2025](https://github.com/111usionBin/jtbc-2025)이며, 우리 주제에 맞게 수집·저장 코드를 새로 작성했습니다.

## 주제 (논의 중)

- **시리즈 영화**: 장르별 비교, 흥행도 차이가 큰 편끼리의 리뷰 차이, 시리즈 장기화에 따른 반응 변화
- **리메이크 영화**: 원작과 리메이크작 비교
- **시즌제 드라마·예능**
- **콘텐츠 매체별 반응 차이**

## 진행 상황

| 단계 | 상태 | 결과 |
|---|---|---|
| 1차 시행 댓글 수집 | 완료 | 마블 몰아보기 영상 1편, 최상위 댓글 448행 |
| Supabase 저장 | 완료 | `lab_videos` 1행, `lab_comments` 448행 |
| 중복 저장 방지 확인 | 완료 | 같은 폴더 재업로드 시 추가 0행 |
| LLM 분석 | 보류 | 코드 준비됨, OpenAI 키 필요 |

**1차 시행 대상**: [마블영화 22편 한번에 몰아보기](https://youtu.be/lekS3GR1jps) (머프무비's 영화 뽀개기, 2022-07-16 공개, 조회수 약 585만)

- 영상 통계상 댓글 수는 666개지만 답글이 포함된 수치입니다. 최상위 댓글은 448개입니다.
- 댓글 작성일 범위: 2022-07-16 ~ 2026-09-06
- 요약·몰아보기 영상이라 개별 작품 평가보다 영상 자체에 대한 반응이 많습니다. 편별 비교를 하려면 작품별 영상을 따로 수집해야 합니다.

## 처리 흐름

```
YouTube Data API v3
      │  collect_comments.py
      ▼
output/<실행시각>/comments.csv + collection_log.json
      │  upload_supabase.py
      ▼
Supabase PostgreSQL (lab_videos, lab_comments)
      │  llm-ev.py  (보류)
      ▼
scored.csv + summary.csv
```

수집과 저장을 분리했습니다. 저장을 다시 해야 할 때 API를 또 호출하지 않아도 되므로 할당량이 들지 않습니다.

## 설치

Python **3.11**이 필요합니다. 3.13에서는 `pydub`가 사용하는 `audioop` 모듈이 표준 라이브러리에서 빠져 있어 동작하지 않습니다.

```bash
# uv 사용 (권장, .python-version의 3.11을 자동으로 맞춤)
uv venv
uv pip install -r requirements-uv.txt

# uv 없이
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements-uv.txt
```

Windows에서는 `./.venv/bin/python` 대신 `.\.venv\Scripts\python.exe`를 사용합니다.
VS Code에서는 `Python: Select Interpreter`로 `.venv`를 선택합니다.

## 환경 변수 (.env)

프로젝트 폴더에 `.env` 파일을 만듭니다. **이 파일은 `.gitignore`에 들어 있으며 절대 커밋하지 않습니다.**

```
google_cloud_api_key=AIza...
SUPABASE_CONNECTION_STRING=postgresql://postgres.<프로젝트참조값>:<DB비밀번호>@aws-0-<지역>.pooler.supabase.com:5432/postgres
```

### Google API 키

Google Cloud 콘솔에서 프로젝트 생성 → YouTube Data API v3 사용 설정 → 사용자 인증 정보 → API 키.
정상적인 키는 `AIza`로 시작합니다.

### Supabase 연결 문자열

Supabase 콘솔 상단 **Connect** → Type `URI` → **Session pooler**에서 복사합니다.

| 방식 | 호스트 | 포트 | 사용 |
|---|---|---|---|
| Direct | `db.<ref>.supabase.co` | 5432 | 사용 안 함 (IPv6 전용) |
| **Session pooler** | `aws-0-<지역>.pooler.supabase.com` | 5432 | **사용** |
| Transaction pooler | 같은 호스트 | 6543 | 사용 안 함 |

- Direct 연결은 IPv6 주소만 있어서 IPv4 네트워크(대부분의 가정·학교망)에서는 접속되지 않습니다.
- Project URL(`https://<ref>.supabase.co`)과 publishable/anon 키는 이 코드에서 쓰지 않습니다. 코드는 `psycopg2`로 Postgres에 직접 연결합니다.
- Supabase CLI(`supabase login`, `init`, `link`)도 필요하지 않습니다.

## 실행

### 1. 댓글 수집

```bash
# API 연결과 영상 정보만 확인
./.venv/bin/python collect_comments.py --check

# 1차 시행 영상 전체 수집 (영상 지정을 생략하면 마블 몰아보기 영상)
./.venv/bin/python collect_comments.py --max-pages 10

# 다른 영상 한 편
./.venv/bin/python collect_comments.py --video "영상_URL" --label "아이언맨" --entry "1편" --max-pages 10

# 최근 7일 댓글만
./.venv/bin/python collect_comments.py --video "영상_URL" --since-days 7 --max-pages 10
```

여러 편을 비교할 때는 manifest 파일을 만듭니다.

```json
[
  {"label": "아이언맨", "entry": "1편", "url": "https://youtu.be/..."},
  {"label": "아이언맨", "entry": "2편", "url": "https://youtu.be/..."},
  {"label": "아이언맨", "entry": "3편", "url": "https://youtu.be/..."}
]
```

```bash
./.venv/bin/python collect_comments.py --manifest videos.json --max-pages 10
```

| 옵션 | 의미 |
|---|---|
| `--video` | 영상 URL 또는 11자리 ID. 여러 번 지정 가능 |
| `--manifest` | 비교할 영상 목록 JSON |
| `--label` / `--entry` | 비교 그룹 이름 / 그룹 안의 위치 (1편, 원작, 시즌3 등) |
| `--max-pages` | 영상당 최대 페이지 수. 한 페이지 최대 100개 |
| `--since-days` | 최근 N일 이내 작성된 댓글만 |
| `--check` | 연결 확인만 하고 종료 |

### 2. Supabase 저장

```bash
./.venv/bin/python upload_supabase.py --check-db   # 연결 확인
./.venv/bin/python upload_supabase.py --init-db    # 테이블 생성 (최초 1회)
./.venv/bin/python upload_supabase.py              # 가장 최근 수집 폴더 업로드
./.venv/bin/python upload_supabase.py --folder output/20260915_161353
./.venv/bin/python upload_supabase.py --count      # 영상별 저장 건수 조회
```

### 3. LLM 분석 (보류)

`.env`에 `openai_api_key`를 추가하면 실행할 수 있습니다.

```bash
./.venv/bin/python llm-ev.py --limit 30   # 30개만 먼저 채점해 비용 확인
./.venv/bin/python llm-ev.py              # 가장 최근 수집 폴더 전체
```

댓글마다 다음 항목을 채점해 `scored.csv`로 저장하고, 라벨·편별 평균을 `summary.csv`로 저장합니다.

| 항목 | 의미 |
|---|---|
| `sentiment` | -1(매우 부정) ~ 1(매우 긍정) |
| `aspect` | 스토리, 연기, 연출, 액션, 영상미, 음악, 캐릭터, 비교, 팬덤, 기타 |
| `is_comparative` / `compares_to` | 다른 편·원작·이전 시즌과 비교하는 댓글인지, 무엇과 비교하는지 |
| `series_fatigue` | 시리즈 장기화에 대한 피로감 표현 여부 |

## 결과 데이터

### comments.csv

한 행은 최상위 댓글 1개입니다.

| 열 | 내용 |
|---|---|
| `label`, `entry` | 비교 그룹, 그룹 안의 위치 |
| `video_id`, `video_title` | 영상 ID, 제목 |
| `comment_id` | 댓글 고유 ID (중복 판단 기준) |
| `author` | 작성자 표시 이름 |
| `text_raw` | API에서 받은 댓글 본문 (가공 없음) |
| `published_at`, `updated_at` | 댓글 작성·수정 시각 (UTC) |
| `like_count`, `reply_count` | 수집 시점의 좋아요 수, 답글 수 |
| `collected_at` | 수집 실행 시각 (UTC) |

### collection_log.json

수집 조건(`order`, `max_pages`, `since_days`)과 영상별 결과(`pages_received`, `stop_reason`, `has_more`, `rows_saved`, `duplicates_skipped`)를 기록합니다.

| `stop_reason` | 의미 |
|---|---|
| `no_next_page` | 더 받을 페이지가 없음 (전량 수집) |
| `page_limit` | `--max-pages` 상한 도달. `has_more=true`면 남은 댓글이 있음 |
| `since_days_reached` | `--since-days` 기준보다 오래된 댓글에 도달 |
| `error` | 조회 중 오류. 그 전까지 받은 행만 저장 |

## 데이터베이스 구조

| 테이블 | 한 행의 의미 | 기본키 |
|---|---|---|
| `lab_videos` | 영상 1편 | `video_id` |
| `lab_comments` | 최상위 댓글 1개 | `comment_id` |

`lab_comments.video_id`는 `lab_videos.video_id`를 참조합니다(외래키). 두 테이블 모두 RLS를 켜고 정책을 만들지 않았으므로 공개 키로는 데이터를 읽을 수 없습니다.

Supabase SQL Editor에서 저장 건수를 확인하는 쿼리:

```sql
SELECT v.video_id, v.label, v.entry, v.title,
       count(c.comment_id) AS comments
FROM public.lab_videos AS v
LEFT JOIN public.lab_comments AS c ON c.video_id = v.video_id
GROUP BY v.video_id, v.label, v.entry, v.title;
```

## 방법론 메모

### API 요청과 페이지네이션

`youtube.commentThreads().list(...)`는 요청 조건만 구성하고, `.execute()`를 호출해야 실제 HTTP 요청이 전송됩니다.
한 번의 요청은 최대 100개까지만 돌려주므로, 응답의 `nextPageToken`을 다음 요청의 `pageToken`에 넣어 반복합니다. 응답에 `nextPageToken`이 없으면 마지막 페이지입니다.

1차 시행에서는 5페이지를 받고(저장 행 기준 100+100+100+100+48) `no_next_page`로 종료했습니다.

### 중복 처리

중복은 두 단계에서 막습니다.

1. **수집 중**: 이번 실행에서 본 `comment_id`를 집합(`seen`)에 담고, 이미 있으면 건너뜁니다. 여러 영상을 한 번에 수집할 때도 같은 집합을 공유합니다. 1차 시행에서는 앞 페이지에서 이미 받은 댓글 1개가 마지막 페이지에 다시 나와 이 단계에서 걸러졌습니다. 최신순 조회 중에 새 댓글이 달리면 페이지가 밀리면서 이런 일이 생길 수 있습니다.
2. **DB 저장 시**: `comment_id`가 기본키이고 `INSERT ... ON CONFLICT (comment_id) DO NOTHING`을 사용합니다. 같은 수집 폴더를 두 번 올려도 행 수가 늘지 않습니다.

같은 본문이라도 `comment_id`가 다르면 서로 다른 사람이 쓴 별개의 댓글로 보고 둘 다 유지합니다.

재업로드 시 이미 있는 댓글의 본문·좋아요 수는 갱신하지 않습니다. 시점별 변화를 보려면 별도의 관측 테이블이 필요합니다.

### 수집 범위의 한계

- 최상위 댓글만 수집하며 답글 본문은 포함하지 않습니다. `reply_count`는 답글 개수일 뿐입니다. 답글이 필요하면 `comments().list(parentId=댓글ID)`로 따로 조회해야 합니다.
- `order="time"`(최신순)으로 받습니다. 인기순(`relevance`)과 결과 순서가 다릅니다.
- `like_count`와 `reply_count`는 수집 시점의 값입니다.

## 파일 구성

### 이 프로젝트에서 사용하는 파일

| 파일 | 역할 |
|---|---|
| `collect_comments.py` | YouTube 댓글 수집 → CSV·로그 저장 |
| `upload_supabase.py` | 수집 폴더를 Supabase에 저장, 건수 조회 |
| `llm-ev.py` | 수집한 댓글의 LLM 채점 (시리즈 비교용 항목으로 수정) |
| `requirements-uv.txt` | 패키지 목록 |
| `.python-version` | Python 3.11 지정 |

### 원본 저장소에서 가져온 파일 (JTBC 뉴스 분석용, 현재 사용 안 함)

| 파일 | 원래 역할 |
|---|---|
| `data_scrape.py` | 재생목록 전체 순회 + 댓글·자막 수집 + DB 저장 (영상당 첫 100개만) |
| `stt.py`, `stt_resume.py` | 영상 음성을 Whisper로 받아쓰기 |
| `collect_missing_videos.py` | 특정 기간 누락 영상 재수집 |
| `ev-run.py` | 뉴스 대본 공정성 평가 |
| `apitest.py`, `llm-tst.py`, `test_openai.py`, `test_download.py` | API 연결 테스트 |
| `main.py` | 인사말 출력 |

## 자주 발생하는 오류

| 증상 | 원인과 해결 |
|---|---|
| `401 API keys are not supported by this API` | 키가 `AIza`로 시작하지 않음. Google Cloud 콘솔의 사용자 인증 정보에서 API 키를 새로 발급 |
| `403 accessNotConfigured` | 키를 만든 프로젝트에서 YouTube Data API v3를 사용 설정하지 않음 |
| `403 commentsDisabled` | 댓글이 꺼진 영상. 다른 영상 선택 |
| `403 quotaExceeded` | 일일 할당량 초과. 다음 날 재시도 |
| DB 연결 시간 초과 | Direct 연결(`db.<ref>.supabase.co`)을 사용 중. Session pooler 주소로 교체 |
| `Tenant or user not found` | 사용자명이 `postgres.<프로젝트참조값>` 형식이 아니거나 지역이 틀림. 콘솔에서 다시 복사 |
| `28P01` 인증 실패 | DB 비밀번호 오류. Settings → Database에서 재설정 후 `.env` 수정 |
| `42P01` 테이블 없음 | `upload_supabase.py --init-db`를 먼저 실행 |
| `ModuleNotFoundError` | 가상환경이 아닌 시스템 Python으로 실행함. `./.venv/bin/python`으로 실행 |
| `Couldn't find ffmpeg` 경고 | 수집·저장에는 영향 없음. STT 사용 시 `brew install ffmpeg` |

## 참고 자료

- [YouTube Data API — commentThreads.list](https://developers.google.com/youtube/v3/docs/commentThreads/list)
- [YouTube Data API — comments.list (답글)](https://developers.google.com/youtube/v3/docs/comments/list)
- [Supabase — Connecting to Postgres](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Supabase — Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [psycopg2 사용법](https://www.psycopg.org/docs/usage.html)
