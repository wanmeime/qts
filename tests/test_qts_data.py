import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest
import qts_data as qd


class TestQtsData(unittest.TestCase):
    def test_data_info_keys(self):
        info = qd.data_info()
        for key in ['行情数据', 'K线数据', '行业分类', 'CPI', 'PMI', 'Shibor', 'GDP']:
            self.assertIn(key, info)

    def test_market_not_empty(self):
        df = qd.market()
        self.assertGreater(len(df), 100)

    def test_kline_has_rows(self):
        codes = qd.kline_codes()[:3]
        self.assertTrue(codes)
        for code in codes:
            df = qd.kline(code)
            self.assertGreater(len(df), 10)


if __name__ == '__main__':
    unittest.main()
