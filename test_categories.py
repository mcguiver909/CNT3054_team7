import unittest
from pathlib import Path
import json
import pandas as pd
from categorize_comments import categorize,connected_groups


class CategoryTests(unittest.TestCase):
    def test_multi_label_does_not_force_sentiment(self):
        config=json.loads((Path(__file__).parent/'comment_categories.json').read_text())
        hits=categorize('12:34 엔드게임 이후 정리 감사합니다',config)
        self.assertTrue(all(hits[c['key']] for c in config['categories']))
        self.assertNotIn('sentiment',hits)

    def test_threads_and_duplicate_text_connect_transitively(self):
        frame=pd.DataFrame([
            {'comment_id':'a','parent_id':'','text':'원댓글A'},
            {'comment_id':'b','parent_id':'a','text':'동의'},
            {'comment_id':'c','parent_id':'','text':'원댓글C'},
            {'comment_id':'d','parent_id':'c','text':'동의!'},
            {'comment_id':'e','parent_id':'','text':'별개'},
        ])
        groups=connected_groups(frame)
        self.assertEqual(len(set(groups[:4])),1)
        self.assertNotEqual(groups[0],groups[4])



if __name__=='__main__':unittest.main()
