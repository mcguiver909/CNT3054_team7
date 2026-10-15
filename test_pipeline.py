import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import pandas as pd
from googleapiclient.errors import HttpError
import collect_comments as collector
from analyze_comments import prepare, analyze


TARGET = {'video_id':'C-NKIKiQCNE','label':'영상그룹','entry':'영상1'}


def item(cid, text='댓글 본문'):
    return {'snippet':{'topLevelComment':{'id':cid,'snippet':{
        'authorDisplayName':'테스트작성자','textDisplay':text,
        'publishedAt':'2026-10-01T00:00:00Z','updatedAt':'2026-10-01T00:00:00Z',
        'likeCount':0}},'totalReplyCount':0}}


class PipelineTests(unittest.TestCase):
    def collect(self, responses, limit=10):
        api = Mock()
        api.commentThreads.return_value.list.return_value.execute.side_effect = responses
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rows, log = collector.collect_comments(api,TARGET,'테스트',limit,set(),None)
        return rows, log, api

    def test_pagination_and_id_dedup(self):
        rows, log, api = self.collect([
            {'items':[item('a')],'nextPageToken':'next'},
            {'items':[item('a'),item('b')]},
        ])
        self.assertEqual([r['comment_id'] for r in rows],['a','b'])
        self.assertEqual(log['duplicates_skipped'],1)
        self.assertEqual(log['stop_reason'],'no_next_page')
        self.assertFalse(log['has_more'])
        self.assertEqual(api.commentThreads.return_value.list.call_args.kwargs['pageToken'],'next')

    def test_page_limit_is_partial(self):
        _, log, _ = self.collect([{'items':[item('a')],'nextPageToken':'next'}],1)
        self.assertEqual(log['stop_reason'],'page_limit')
        self.assertTrue(log['has_more'])

    def test_error_preserves_partial_rows_without_key(self):
        error = HttpError(Mock(status=403,reason='Forbidden'),b'{"error":{"message":"quota"}}',
                          uri='https://example.test/?key=DO_NOT_PRINT_SECRET')
        rows, log, _ = self.collect([{'items':[item('a')],'nextPageToken':'next'},error])
        self.assertEqual(len(rows),1)
        self.assertEqual(log['stop_reason'],'error')
        self.assertIsNone(log['has_more'])
        self.assertEqual(log['error_status'],403)

    def test_preprocessing_preserves_videos_and_negative_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp)/'comments.csv'
            pd.DataFrame([
                {**TARGET,'comment_id':'a','text_raw':'안 좋다 https://test.test'},
                {**TARGET,'comment_id':'a','text_raw':'안 좋다 https://test.test'},
                {**TARGET,'comment_id':'b','text_raw':'안 좋다'},
                {**TARGET,'video_id':'LMtoL902Ddo','comment_id':'c','text_raw':'안 좋다'},
                {**TARGET,'comment_id':'d','text_raw':'!!!'},
            ]).to_csv(csv,index=False)
            frame, meta = prepare(csv)
            self.assertEqual(meta['id_duplicates_removed'],1)
            self.assertEqual(meta['analysis_rows'],2)
            self.assertEqual(frame.iloc[0]['text'],'안 좋다')
            self.assertEqual(frame.loc[frame.comment_id.isin(['a','c']),'group_id'].nunique(),1)

    def test_inference_uses_text_raw_not_series_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp)/'comments.csv'
            pd.DataFrame([{**TARGET,'comment_id':'a','text_raw':'완전새로운미등록댓글표현'}]).to_csv(csv,index=False)
            meta = analyze(csv,Path(tmp)/'analysis')
            prediction = pd.read_csv(Path(tmp)/'analysis/predictions.csv')
            self.assertEqual(prediction.loc[0,'known_features'],0)
            self.assertTrue(prediction.loc[0,'review_required'])
            self.assertIsNone(meta['actual_comment_accuracy'])
            self.assertEqual(prediction.loc[0,'label'],'영상그룹')
            self.assertEqual(meta['selected_model'],'unigram')
            self.assertNotIn('author',prediction.columns)
            with self.assertRaises(ValueError):
                analyze(csv,Path(tmp)/'analysis')


if __name__ == '__main__':
    unittest.main()
