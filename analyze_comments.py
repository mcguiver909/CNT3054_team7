"""Connect the repository's text_raw schema to the uploaded Week 6 model.

Grouping label/entry is NEVER interpreted as a sentiment label.
Without manually labeled comments this is transfer inference, not evaluation.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

import pandas as pd
from week06 import train_sentiment as lab


def clean_text(text):
    text = re.sub(r'https?://\S+|www\.\S+', ' ', str(text))
    return lab.normalize_text(text)


def prepare(csv):
    frame = pd.read_csv(csv, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    required = {'video_id', 'comment_id', 'text_raw', 'label', 'entry'}
    if required - set(frame):
        raise ValueError(f'누락된 열: {sorted(required - set(frame))}')
    if frame.comment_id.eq('').any() or frame.video_id.eq('').any():
        raise ValueError('video_id/comment_id가 비어 있습니다.')
    original = len(frame)
    frame = frame.drop_duplicates('comment_id').copy()
    frame['text'] = frame.text_raw.map(clean_text)
    frame['text_key'] = frame.text.map(lab.text_key)
    frame['usable_text'] = frame.text_key.ne('')
    # Keep separate videos and original comments; dedup only analysis denominator.
    frame['duplicate_text_in_video'] = frame.duplicated(['video_id', 'text_key'])
    frame['in_analysis'] = frame.usable_text & ~frame.duplicate_text_in_video
    frame['group_id'] = frame.text_key.map(lambda s: hashlib.sha256(s.encode()).hexdigest()[:24])
    meta = {'input_rows': original, 'id_duplicates_removed': original-len(frame),
            'empty_or_nonword_rows': int((~frame.usable_text).sum()),
            'text_duplicates_in_video': int((frame.usable_text & frame.duplicate_text_in_video).sum()),
            'analysis_rows': int(frame.in_analysis.sum())}
    return frame.reset_index(drop=True), meta


def analyze(csv, output, training=lab.DEFAULT_DATA, evaluate_test=False):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('새 출력 폴더를 지정하세요. 기존 결과를 덮어쓰지 않습니다.')
    frame, cleaning = prepare(csv)
    data, training_meta = lab.load_data(training)
    # An uploaded actual-comment training set must not also be the inference set:
    # otherwise aggregate inference would contain in-sample predictions.
    overlap = set(frame.loc[frame.usable_text, 'text_key']) & set(data._text_key)
    if overlap:
        raise ValueError('학습 자료와 입력 댓글이 겹칩니다. 실제 댓글 평가는 week06/train_sentiment.py의 홀드아웃 결과를 사용하세요.')
    splits = lab.split_data(data)
    models, baseline, scores, selected = lab.compare_models(splits['train'], splits['validation'])
    model = models[selected]
    output.mkdir(parents=True, exist_ok=True)
    lab.run_experiment(training, output/'training_evaluation', evaluate_test, plots=True)
    frame['prediction'] = pd.Series(pd.NA, index=frame.index, dtype='Int64')
    frame['p_positive'] = float('nan')
    frame['known_features'] = 0
    valid = frame.usable_text
    if valid.any():
        text = frame.loc[valid, 'text']
        frame.loc[valid, 'prediction'] = model.predict(text)
        frame.loc[valid, 'p_positive'] = model.predict_proba(text)[:, list(model.classes_).index(1)]
        frame.loc[valid, 'known_features'] = model.named_steps['tfidf'].transform(text).getnnz(axis=1)
    frame['review_required'] = ~valid | frame.known_features.eq(0) | frame.p_positive.between(.4,.6)
    # Author is excluded from analysis artifacts.
    frame = frame.drop(columns=['author'], errors='ignore')
    lab.write_csv(frame, output/'predictions.csv')
    summary = []
    for video_id, video in frame.groupby('video_id', sort=False):
        subset = video.loc[video.in_analysis]
        n = len(subset)
        summary.append({'video_id':video_id, 'label':video.iloc[0]['label'], 'entry':video.iloc[0]['entry'],
                        'rows_collected':len(video), 'analysis_rows':n,
                        'predicted_positive':int(subset.prediction.eq(1).sum()),
                        'predicted_negative':int(subset.prediction.eq(0).sum()),
                        'predicted_positive_ratio':float(subset.prediction.eq(1).mean()) if n else None,
                        'zero_feature_rows':int(subset.known_features.eq(0).sum()),
                        'review_required_rows':int(subset.review_required.sum())})
    pd.DataFrame(summary, columns=['video_id','label','entry','rows_collected','analysis_rows',
        'predicted_positive','predicted_negative','predicted_positive_ratio',
        'zero_feature_rows','review_required_rows']).to_csv(output/'summary.csv',index=False,encoding='utf-8-sig')
    annotation = frame.loc[frame.in_analysis, ['comment_id','video_id','label','entry','text_raw','text','group_id']].copy()
    annotation = annotation.rename(columns={'label':'series_label','comment_id':'review_id'})
    for col in ['target','sentiment_label','notes']:
        annotation[col] = ''
    lab.write_csv(annotation, output/'annotation_template.csv')
    metadata = {'input_csv':str(Path(csv).resolve()), 'input_sha256':hashlib.sha256(Path(csv).read_bytes()).hexdigest(),
                'cleaning':cleaning, 'training_data':training_meta, 'selected_model':selected,
                'actual_comment_accuracy':None, 'actual_comment_f1':None,
                'inference_mode':'transfer_from_supplied_training_data',
                'warning':'합성 리뷰 학습 모델의 실제 댓글 예측은 탐색용입니다. 실제 댓글 정답 라벨이 없어 정확도/F1은 계산하지 않았습니다. 확률은 감정 강도나 중립 판정이 아닙니다.',
                'deduplication':'수집: comment_id; 분석: 영상 내 정규화 동일 본문 제외. 원문 보존.',
                'review_flag':'빈 본문/미인식 특징/0.4~0.6 확률을 검토 대상으로 표시하며 중립으로 분류하지 않음.'}
    log = Path(csv).parent/'collection_log.json'
    if log.exists():
        metadata['collection_log'] = json.loads(log.read_text())
    reply_log = Path(csv).parent/'reply_collection_log.json'
    if 'comment_type' in frame:
        metadata['scope_counts'] = frame.comment_type.value_counts().to_dict()
        if reply_log.exists():
            metadata['reply_collection_log'] = json.loads(reply_log.read_text())
    (output/'analysis_log.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--training-csv', type=Path, default=lab.DEFAULT_DATA)
    parser.add_argument('--evaluate-test', action='store_true')
    args = parser.parse_args()
    try:
        meta = analyze(args.csv,args.output,args.training_csv,args.evaluate_test)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'입력/설정 확인: {exc}\n')
    print(json.dumps(meta['cleaning'], ensure_ascii=False))
    print(meta['warning'])


if __name__ == '__main__':
    main()
