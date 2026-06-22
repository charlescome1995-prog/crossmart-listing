# -*- coding: utf-8 -*-
"""
CrossMart Listing — 一键运行（STEP1 + STEP2）
=============================================
用法：
    python backend/run_listing.py "happy light"
    python backend/run_listing.py "happy light" --max 15 --top 6

流程：
    STEP 1: 关键词 → 抓对标 ASIN（Edge 唯一默认账户）
    STEP 2: 对标 ASIN → 火山方舟 LLM 生成英文 Listing
输出：frontend/data/listing-data.json
"""
import sys, os, argparse

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
sys.stdout.reconfigure(encoding='utf-8')

from step1_find_benchmark import run_step1
from step2_build_listing import run_step2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('keyword', help='搜索关键词')
    ap.add_argument('--max', type=int, default=12, help='最多扫描 ASIN 数')
    ap.add_argument('--top', type=int, default=5, help='选出对标 ASIN 数')
    ap.add_argument('--step', choices=['1', '2', 'all'], default='all',
                    help='只跑某一步（1=找对标 2=生成 all=全部）')
    args = ap.parse_args()

    if args.step in ('1', 'all'):
        r1 = run_step1(args.keyword, args.max, args.top)
        if not r1:
            print('STEP1 失败，终止。')
            sys.exit(1)
    if args.step in ('2', 'all'):
        run_step2(args.keyword)
    print('\n✅ 全部完成。git add/commit/push 后 Ctrl+F5 刷新前端。')


if __name__ == '__main__':
    main()
