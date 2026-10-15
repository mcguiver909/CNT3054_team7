import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from googleapiclient.errors import HttpError
import collect_replies as replies
from test_pipeline import TARGET

PARENT = {**TARGET,'comment_id':'parent','video_title':'test','reply_count':2}


def item(cid):
    return {'id':cid,'snippet':{'parentId':'parent','authorDisplayName':'test',
        'textDisplay':'답글','publishedAt':'2026-10-15T00:00:00Z',
        'updatedAt':'2026-10-15T00:00:00Z','likeCount':1}}


class ReplyTests(unittest.TestCase):
    def test_fetches_all_pages_deduplicates_and_retains_parent(self):
        api=Mock()
        api.comments.return_value.list.return_value.execute.side_effect=[
            {'items':[item('r1')],'nextPageToken':'next'},
            {'items':[item('r1'),item('r2')]},
        ]
        rows,log=replies.fetch_replies(api,PARENT,{'parent'})
        self.assertEqual([r['comment_id'] for r in rows],['r1','r2'])
        self.assertTrue(all(r['parent_id']=='parent' and r['comment_type']=='reply' for r in rows))
        self.assertEqual(log['stop_reason'],'no_next_page')
        self.assertEqual(log['pages_received'],2)
        self.assertEqual(api.comments.return_value.list.call_args.kwargs['pageToken'],'next')

    def test_api_error_is_partial_not_success(self):
        api=Mock()
        api.comments.return_value.list.return_value.execute.side_effect=[
            {'items':[item('r1')],'nextPageToken':'next'},
            HttpError(Mock(status=403,reason='Forbidden'),b'{"error":{"message":"quota"}}')]
        rows,log=replies.fetch_replies(api,PARENT,{'parent'})
        self.assertEqual(len(rows),1)
        self.assertEqual(log['stop_reason'],'error')
        self.assertEqual(log['error_status'],403)


if __name__=='__main__':
    unittest.main()
