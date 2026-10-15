"""Join Table 5 multi-label comment tags to the Week 6 LR predictions."""
import argparse
import hashlib
import json
from pathlib import Path
import re

import pandas as pd
from week06.train_sentiment import text_key

BASE=Path(__file__).resolve().parent


def categorize(text, config):
    return {c['key']:[p for p in c['patterns'] if re.search(p,str(text),re.IGNORECASE)]
            for c in config['categories']}


def connected_groups(frame):
    """Keep same threads and normalized duplicate texts in one label/split group."""
    parent={cid:cid for cid in frame.comment_id}
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]];x=parent[x]
        return x
    def union(a,b):
        ra,rb=find(a),find(b)
        if ra!=rb:
            parent[max(ra,rb)]=min(ra,rb)
    texts={}
    for row in frame.to_dict('records'):
        cid=row['comment_id'];pid=str(row.get('parent_id',''))
        if pid in parent:
            union(cid,pid)
        key=text_key(str(row.get('text','')))
        if key:
            if key in texts:union(cid,texts[key])
            else:texts[key]=cid
    return [hashlib.sha256(find(cid).encode()).hexdigest()[:24] for cid in frame.comment_id]


def run(predictions,output,config_path=BASE/'comment_categories.json'):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    config=json.loads(Path(config_path).read_text())
    frame=pd.read_csv(predictions,encoding='utf-8-sig',keep_default_na=False)
    frame=frame.rename(columns={'label':'series_group','prediction':'sentiment_prediction'})
    if 'parent_id' not in frame:frame['parent_id']=''
    if 'comment_type' not in frame:frame['comment_type']='top_level'
    frame['sentiment_prediction']=pd.to_numeric(frame.sentiment_prediction,errors='coerce').astype('Int64')
    frame['sentiment_name']=frame.sentiment_prediction.map({0:'부정 예측',1:'긍정 예측'}).fillna('분석 불가')
    hits=frame.text_raw.map(lambda s:categorize(s,config))
    for category in config['categories']:
        key=category['key'];frame['category_'+key]=hits.map(lambda x:bool(x[key]))
        frame['matches_'+key]=hits.map(lambda x:json.dumps(x[key],ensure_ascii=False))
    frame['comment_categories']=hits.map(lambda x:' | '.join(c['name'] for c in config['categories'] if x[c['key']]) or '기타·키워드 미일치')
    frame['sentiment_gold']=''
    frame['reaction_target_gold']=''
    frame['group_id']=connected_groups(frame)
    frame.to_csv(output/'categorized_comments.csv',index=False,encoding='utf-8-sig')
    tables=[];cross=[]
    # Denominator: all collected comments, also report unique usable analysis count.
    subsets=[('ALL',frame)]+list(frame.groupby('video_id',sort=False))
    categories=config['categories']+[{'key':'other','name':'기타·키워드 미일치'}]
    for vid,subset in subsets:
        for cat in categories:
            mask=subset.comment_categories.eq('기타·키워드 미일치') if cat['key']=='other' else subset['category_'+cat['key']]
            selected=subset[mask];analyzed=selected[selected.in_analysis]
            tables.append({'video_id':vid,'category':cat['name'],'comments':len(selected),
                'denominator_all_collected':len(subset),'ratio':len(selected)/len(subset) if len(subset) else None,
                'unique_usable_analysis_rows':len(analyzed)})
            supported=analyzed[pd.to_numeric(analyzed.known_features).gt(0)]
            cross.append({'video_id':vid,'category':cat['name'],'category_comments':len(selected),
                'analysis_rows':len(analyzed),'predicted_positive':int(analyzed.sentiment_prediction.eq(1).sum()),
                'predicted_negative':int(analyzed.sentiment_prediction.eq(0).sum()),
                'zero_feature_rows':int(pd.to_numeric(analyzed.known_features).eq(0).sum()),
                'feature_supported_positive':int(supported.sentiment_prediction.eq(1).sum()),
                'feature_supported_negative':int(supported.sentiment_prediction.eq(0).sum()),
                'review_required_rows':int(analyzed.review_required.sum())})
    pd.DataFrame(tables).to_csv(output/'table5_categories.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(cross).to_csv(output/'category_sentiment_summary.csv',index=False,encoding='utf-8-sig')
    cols=['comment_id','video_id','video_title','series_group','entry','comment_type','parent_id',
          'text_raw','text','group_id','comment_categories','reaction_target_gold','sentiment_gold']
    # Prevent prediction anchoring: human labeling file deliberately has no model output.
    labeling=frame[cols].rename(columns={'comment_id':'review_id'})
    for col in ['reviewer_1','reviewer_1_label','reviewer_2','reviewer_2_label','adjudication_notes','label_confirmed']:
        labeling[col]=''
    labeling.to_csv(output/'labeling_sheet.csv',index=False,encoding='utf-8-sig')
    metadata={'rows':len(frame),'category_config':config,'category_config_sha256':hashlib.sha256(Path(config_path).read_bytes()).hexdigest(),
        'category_method':'Keyword/regex matches; multi-label; not manually validated semantic targets',
        'sentiment_method':'Existing Week 6 TF-IDF unigram + LogisticRegression; trained only on supplied synthetic review train split',
        'human_gold_labels_available':False,'actual_comment_accuracy':None,'actual_comment_f1':None,
        'group_method':'Connected components of parent thread and normalized duplicate text; manually merge other similar comments before actual evaluation',
        'note':''}
    metadata['note']='표5에 실린 키워드 예시를 바탕으로 확장한 규칙이며, 당시의 전체 사전이 제공되지 않아 과거 집계의 완전 재현을 주장하지 않음. 구분과 모델 예측 모두 사람이 검토해야 함.'
    (output/'categorization_log.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    return frame,pd.DataFrame(tables),pd.DataFrame(cross)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predictions',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    frame,table,cross=run(args.predictions,args.output)
    print(f'댓글 {len(frame):,}개에 표5 구분과 감성 예측을 연결했습니다. 사람 정답 라벨은 별도입니다.')
    print(table[table.video_id.eq('ALL')].to_string(index=False))


if __name__=='__main__':main()
