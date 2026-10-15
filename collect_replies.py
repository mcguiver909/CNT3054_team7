"""Fetch every available reply page and retain parent-child relationships.

The original 12-column comments.csv remains the top-level-only snapshot.
all_comments.csv includes those rows plus replies, parent_id, and comment_type.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from googleapiclient.errors import HttpError
import collect_comments as collector

COLUMNS = collector.COLUMNS + ['parent_id', 'comment_type']


def fetch_replies(youtube, parent, seen):
    rows, token, pages = [], None, 0
    error = None
    collected_at = datetime.now(timezone.utc).isoformat()
    while True:
        try:
            response = youtube.comments().list(part='snippet', parentId=parent['comment_id'],
                maxResults=100, textFormat='plainText', pageToken=token).execute()
        except HttpError as exc:
            error = int(exc.resp.status)
            break
        pages += 1
        for item in response.get('items', []):
            if item['id'] in seen:
                continue
            seen.add(item['id'])
            snippet = item['snippet']
            rows.append({
                'label':parent['label'], 'entry':parent['entry'],
                'video_id':parent['video_id'], 'video_title':parent['video_title'],
                'comment_id':item['id'], 'author':snippet.get('authorDisplayName',''),
                'text_raw':snippet.get('textDisplay',''),
                'published_at':snippet['publishedAt'], 'updated_at':snippet['updatedAt'],
                'like_count':snippet.get('likeCount',0), 'reply_count':0,
                'collected_at':collected_at, 'parent_id':snippet.get('parentId',parent['comment_id']),
                'comment_type':'reply',
            })
        token = response.get('nextPageToken')
        if not token:
            break
    return rows, {'parent_id':parent['comment_id'], 'video_id':parent['video_id'],
        'expected_replies_at_top_level_snapshot':int(parent['reply_count']),
        'rows_saved':len(rows), 'pages_received':pages,
        'stop_reason':'error' if error is not None else 'no_next_page', 'error_status':error}


def collect_folder(folder, youtube=None):
    folder = Path(folder)
    if (folder/'all_comments.csv').exists():
        raise ValueError('전체 댓글 파일이 이미 있습니다. 새 수집 폴더를 사용하세요.')
    with (folder/'comments.csv').open(encoding='utf-8-sig',newline='') as f:
        top = list(csv.DictReader(f))
    youtube = youtube or collector.make_youtube_client()
    seen = {row['comment_id'] for row in top}
    all_rows = [{**row, 'parent_id':'', 'comment_type':'top_level'} for row in top]
    replies, logs = [], []
    parents = [row for row in top if int(row['reply_count']) > 0]
    for i, parent in enumerate(parents,1):
        rows, log = fetch_replies(youtube, parent, seen)
        replies.extend(rows); logs.append(log)
        if i % 20 == 0 or i == len(parents):
            print(f'답글 스레드 {i}/{len(parents)} 조회, 답글 {len(replies)}개 저장',flush=True)
    all_rows.extend(replies)
    for name, rows in [('replies',replies),('all_comments',all_rows)]:
        with (folder/f'{name}.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer = csv.DictWriter(f,fieldnames=COLUMNS)
            writer.writeheader();writer.writerows(rows)
        (folder/f'{name}.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    summary = {'top_level_rows':len(top), 'reply_rows':len(replies), 'total_rows':len(all_rows),
        'parents_requested':len(parents), 'parents_failed':sum(x['stop_reason']=='error' for x in logs),
        'expected_replies_at_top_level_snapshot':sum(int(row['reply_count']) for row in top),
        'collected_at':datetime.now(timezone.utc).isoformat(),
        'scope':'All reply pages for top-level parents with reply_count>0 in the top-level snapshot',
        'note':'Counts may change during collection. Deleted/hidden replies are not available from the public API.',
        'parents':logs}
    (folder/'reply_collection_log.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,required=True)
    args = parser.parse_args()
    try:
        log = collect_folder(args.folder)
    except (ValueError,OSError) as exc:
        parser.exit(1,f'입력/설정 확인: {exc}\n')
    print(f"최상위 {log['top_level_rows']}개 + 답글 {log['reply_rows']}개 = 전체 {log['total_rows']}개")
    return 1 if log['parents_failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
