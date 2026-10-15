"""Summarize independently reviewed semantic labels, never infer them from keywords."""
import argparse
from pathlib import Path
import json
import pandas as pd

SENTIMENTS=['긍정','부정','중립','혼합','판단 불가']
TARGETS=['작품·시리즈','배우·캐릭터','장면·서사·설정','영상·제작자','홍보물·포스터','상영·배급·관람환경','시청표시·시간정보','기타·대화·대상불명']

def summarize(source,output):
    frame=pd.read_csv(source,encoding='utf-8-sig',keep_default_na=False)
    required={'comment_id','video_id','text_raw','sentiment_ai','reaction_target_ai'}
    if required-set(frame):raise ValueError(f'필요한 열 누락: {sorted(required-set(frame))}')
    if frame.comment_id.eq('').any() or frame.comment_id.duplicated().any():raise ValueError('댓글 ID는 비어 있지 않고 고유해야 합니다.')
    if not frame.sentiment_ai.isin(SENTIMENTS).all():raise ValueError('허용되지 않은 감성 라벨')
    if not frame.reaction_target_ai.isin(TARGETS).all():raise ValueError('허용되지 않은 의미 구분')
    if frame.empty:raise ValueError('댓글이 없습니다.')
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    table=pd.crosstab(frame.reaction_target_ai,frame.sentiment_ai).reindex(index=TARGETS,columns=SENTIMENTS,fill_value=0)
    table.insert(0,'댓글수',table.sum(axis=1));table.insert(1,'전체비율',table['댓글수']/len(frame))
    table.index.name='댓글구분';table.to_csv(output/'semantic_category_sentiment.csv',encoding='utf-8-sig')
    video=pd.crosstab(frame.video_id,frame.sentiment_ai).reindex(columns=SENTIMENTS,fill_value=0)
    video.insert(0,'전체',video.sum(axis=1));video.to_csv(output/'video_sentiment.csv',encoding='utf-8-sig')
    assert int(table['댓글수'].sum())==int(video['전체'].sum())==len(frame)
    (output/'semantic_summary.json').write_text(json.dumps({'rows':len(frame),'method':'AI semantic primary-target annotations; mutually exclusive; not keyword matches','human_gold':False,'sentiment_counts':frame.sentiment_ai.value_counts().to_dict(),'target_counts':frame.reaction_target_ai.value_counts().to_dict()},ensure_ascii=False,indent=2)+'\n')
    return table,video

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();summarize(args.labels,args.output)
