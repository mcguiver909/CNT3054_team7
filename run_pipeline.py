"""Run the existing collector and Week 6 inference for the configured target videos."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-pages',type=int,default=10)
    parser.add_argument('--include-replies',action='store_true',help='공개 답글 전체 페이지도 수집하고 전체 댓글 분석')
    args = parser.parse_args()
    # Match the credential locations without exposing the value in arguments.
    load_dotenv(BASE/'.env')
    load_dotenv(Path.cwd()/'.env')
    load_dotenv(BASE.parent.parent/'.env')
    if not (os.getenv('YOUTUBE_API_KEY') or os.getenv('google_cloud_api_key')):
        parser.exit(2,'API 키가 없습니다. 작업 폴더 .env의 YOUTUBE_API_KEY를 설정하세요. 실제 수집은 실행하지 않았습니다.\n')
    if args.max_pages < 1:
        parser.error('max-pages는 양수여야 합니다.')
    before = set((BASE/'output').glob('*'))
    command = [sys.executable,str(BASE/'collect_comments.py'),'--manifest','videos.json',
               '--max-pages',str(args.max_pages)]
    result = subprocess.run(command,cwd=BASE)
    if result.returncode:
        return result.returncode
    created = set((BASE/'output').glob('*')) - before
    if len(created) != 1:
        parser.exit(1,'새 수집 결과 폴더를 확정할 수 없습니다. 로그를 확인하세요.\n')
    folder = created.pop()
    log = json.loads((folder/'collection_log.json').read_text())
    has_error = any(v['stop_reason']=='error' for v in log['videos'])
    if log['run']['total_rows']:
        csv_name, analysis_name = 'comments.csv', 'analysis'
        if args.include_replies:
            result = subprocess.run([sys.executable,str(BASE/'collect_replies.py'),
                '--folder',str(folder)],cwd=BASE)
            if result.returncode:
                return result.returncode
            csv_name, analysis_name = 'all_comments.csv', 'analysis_all'
        result = subprocess.run([sys.executable,str(BASE/'analyze_comments.py'),
            '--csv',str(folder/csv_name),'--output',str(folder/analysis_name)],cwd=BASE)
        if result.returncode:
            return result.returncode
        result = subprocess.run([sys.executable,str(BASE/'categorize_comments.py'),
            '--predictions',str(folder/analysis_name/'predictions.csv'),
            '--output',str(folder/'categories')],cwd=BASE)
        if result.returncode:
            return result.returncode
    else:
        print('저장된 댓글이 0개여서 감성분석은 수행하지 않았습니다.')
    complete = all(v['stop_reason']=='no_next_page' for v in log['videos'])
    print(f"{log['run']['videos_requested']}개 영상의 API 조회 종료: "+('모든 페이지 조회' if complete else '부분 수집 또는 오류. collection_log.json 확인 필요'))
    print('결과 폴더:',folder)
    return 1 if has_error else 0


if __name__ == '__main__':
    raise SystemExit(main())
