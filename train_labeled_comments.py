"""Week 6 TF-IDF/LR workflow on explicitly AI-annotated real comments.

Scores measure agreement with the held-out AI annotations, not human accuracy.
"""
import argparse,json,hashlib
from pathlib import Path
import pandas as pd
from sklearn.metrics import classification_report,confusion_matrix
from week06 import train_sentiment as lab
from analyze_comments import clean_text
from categorize_comments import connected_groups


def run(folder):
    folder=Path(folder);output=folder/'analysis_ai';output.mkdir(exist_ok=False)
    annotated=pd.read_csv(folder/'ai_annotated_comments.csv',encoding='utf-8-sig',keep_default_na=False)
    raw=pd.read_csv(folder/'all_comments.csv',encoding='utf-8-sig',keep_default_na=False)
    parents=raw.set_index('comment_id').text_raw.to_dict()
    annotated['text_model']=annotated.apply(lambda r:clean_text(
        '원댓글: '+parents.get(r.parent_id,'')+' 답글: '+r.text_raw if r.comment_type=='reply' else r.text_raw),axis=1)
    annotated['group_id']=connected_groups(annotated.rename(columns={'text_model':'model_input'}))
    binary=annotated[annotated.sentiment_ai.isin(['긍정','부정']) & annotated.reaction_target_ai.ne('기타·대인·상영환경')].copy()
    binary['label']=binary.sentiment_ai.map({'부정':0,'긍정':1})
    binary['text']=binary.text_model
    binary['review_id']=binary.comment_id
    binary['source_type']='ai_annotated_youtube_unverified'
    binary['_key']=binary.text.map(lab.text_key)
    binary=binary[binary._key.ne('')].copy()
    conflict=binary.groupby('_key').label.nunique().gt(1)
    conflicts=set(conflict[conflict].index)
    binary[binary._key.isin(conflicts)].to_csv(output/'excluded_label_conflicts.csv',index=False,encoding='utf-8-sig')
    binary=binary[~binary._key.isin(conflicts)]
    train_csv=output/'training_data.csv'
    binary[['review_id','group_id','text','label','source_type']].to_csv(train_csv,index=False,encoding='utf-8-sig')
    data,data_meta=lab.load_data(train_csv)
    splits=lab.split_data(data)
    models,baseline,scores,selected=lab.compare_models(splits['train'],splits['validation'])
    model=models[selected]
    lab.write_csv(scores,output/'validation_scores.csv')
    weights=lab.feature_weights(model);lab.write_csv(weights,output/'feature_weights.csv')
    for split in ['validation','test']:
        table=lab.prediction_table(model,splits[split])
        lab.write_csv(table,output/(split+'_predictions.csv'))
        lab.write_csv(table[~table.correct],output/(split+'_errors.csv'))
        lab.save_plots(table,weights,output,split)
    test=lab.prediction_table(model,splits['test'])
    test_scores=pd.DataFrame([
        {'model':'majority_baseline',**lab.score_predictions(test.label,baseline.predict(splits['test'][['text']]))},
        {'model':selected,**lab.score_predictions(test.label,test.prediction)}])
    lab.write_csv(test_scores,output/'test_scores.csv')
    (output/'test_classification_report.txt').write_text(classification_report(test.label,test.prediction,labels=[0,1],target_names=['negative','positive'],zero_division=0,digits=4))
    manifests=pd.concat([f[['review_id','group_id']].assign(split=s) for s,f in splits.items()])
    lab.write_csv(manifests,output/'split_assignments.csv')
    result=annotated.copy()
    valid=result.text_model.map(lab.text_key).ne('')
    result['lr_prediction']=pd.Series(pd.NA,index=result.index,dtype='Int64')
    result['lr_p_positive']=float('nan');result['lr_known_features']=0
    result.loc[valid,'lr_prediction']=model.predict(result.loc[valid,'text_model'])
    result.loc[valid,'lr_p_positive']=model.predict_proba(result.loc[valid,'text_model'])[:,list(model.classes_).index(1)]
    result.loc[valid,'lr_known_features']=model.named_steps['tfidf'].transform(result.loc[valid,'text_model']).getnnz(axis=1)
    result['lr_sentiment']=result.lr_prediction.map({0:'부정 예측',1:'긍정 예측'}).fillna('분석 불가')
    result['lr_review_required']=~valid | result.lr_known_features.eq(0) | result.lr_p_positive.between(.4,.6)
    result['evaluation_split']=result.comment_id.map(manifests.set_index('review_id').split).fillna('학습·평가 제외')
    result.to_csv(output/'comments_labeled_and_lr.csv',index=False,encoding='utf-8-sig')
    matrix=confusion_matrix(test.label,test.prediction,labels=[0,1]).tolist()
    meta={'label_source':'AI semantic annotations by Codex, all 2983 comments read; not human-adjudicated gold',
        'training_source':'ai_annotated_youtube_unverified','data':data_meta,
        'training_sha256':hashlib.sha256(train_csv.read_bytes()).hexdigest(),'seed':42,
        'split_sizes':{k:len(v) for k,v in splits.items()},
        'split_label_counts':{k:{str(i):int(n) for i,n in v.label.value_counts().sort_index().items()} for k,v in splits.items()},
        'selected_model':selected,'selection_metric':'validation macro-F1; ties prefer unigram',
        'fit_scope':'train only, no validation refit','test_scores':test_scores.to_dict('records'),
        'test_confusion_matrix_labels_0_1':matrix,'human_gold_accuracy':None,'human_gold_f1':None,
        'warning':'Held-out scores are agreement with AI labels, not validated human accuracy. Full-data predictions include training rows and are marked by split.',
        'input_context':'Reply model input contains parent text plus reply. Same threads/normalized duplicate texts share a group.',
        'binary_filter':'Only AI positive/negative targeting works, characters, scenes, or video/creator; excludes neutral/mixed/unclear and other/person/cinema targets.'}
    (output/'metrics.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(meta,ensure_ascii=False,indent=2))
    return result,meta


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--folder',type=Path,required=True)
    run(parser.parse_args().folder)
