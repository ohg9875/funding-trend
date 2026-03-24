"""크롤러만 테스트 실행 (전처리·분석·리포트 제외)"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from agents.tumblbug_collector import collect_tumblbug, _load_categories_from_config as tb_cats
from agents.wadiz_collector import collect_wadiz, _load_categories_from_config as wz_cats

if __name__ == "__main__":
    print("=== 텀블벅 수집 (최대 2페이지) ===")
    categories = tb_cats()
    tb = collect_tumblbug(categories=categories, max_pages=2)
    print(f"텀블벅: {len(tb)}개")
    if tb:
        s = tb[0]
        print(f"  샘플: {s['title']} | {s['goods_category'] or s.get('tumblbug_category')}\n")

    print("=== 와디즈 수집 (최대 2페이지) ===")
    categories = wz_cats()
    wz = collect_wadiz(category_codes=categories, max_pages=2)
    print(f"와디즈: {len(wz)}개")
    if wz:
        s = wz[0]
        print(f"  샘플: {s['title']} | 달성률 {s['achieved_rate']}%\n")

    print(f"합계: {len(tb) + len(wz)}개")
