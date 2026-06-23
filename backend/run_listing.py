# -*- coding: utf-8 -*-
"""
CrossMart Listing — 一键运行（两套逻辑并行）
=============================================
用法：
    # 两套都跑（先抓对标 ASIN，再 A 套 + B 套各生成一版，前端并排对比）
    python backend/run_listing.py "happy light" --engine both

    # 只跑 B 套（自抓亚马逊 + 火山方舟 LLM）
    python backend/run_listing.py "happy light" --engine B

    # 只跑 A 套（卖家精灵 listing-builder）
    python backend/run_listing.py "happy light" --engine A

两套逻辑：
    STEP1（共享）: 关键词 → 抓对标 ASIN（Edge 唯一默认账户）
    A 套: 对标 ASIN → 驱动卖家精灵 listing-builder 的 AI → listing-data-A.json
    B 套: 对标 ASIN 共性 → 火山方舟 LLM 生成英文 Listing → listing-data-B.json
"""
import sys, os, argparse

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
sys.stdout.reconfigure(encoding='utf-8')

from step1_find_benchmark import run_step1
from step2_build_listing import run_step2
from step_a_sellersprite import run_engine_a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('keyword', help='搜索关键词')
    ap.add_argument('--max', type=int, default=12, help='最多扫描 ASIN 数')
    ap.add_argument('--top', type=int, default=5, help='选出对标 ASIN 数')
    ap.add_argument('--engine', choices=['A', 'B', 'both'], default='both',
                    help='A=卖家精灵 listing-builder  B=自抓+火山方舟  both=两套并行')
    ap.add_argument('--step', choices=['1', '2', 'all'], default='all',
                    help='1=只找对标 2=只生成（需已跑过1） all=全部')
    ap.add_argument('--asin', default=None, help='A 套指定对标 ASIN（默认用评分最高）')
    ap.add_argument('--skip-images', action='store_true', help='B 套不生成 A+ 配图（只出文案）')
    args = ap.parse_args()

    # STEP1：抓对标 ASIN（两套共享，跑一次即可）
    if args.step in ('1', 'all'):
        r1 = run_step1(args.keyword, args.max, args.top)
        if not r1:
            print('STEP1 失败，终止。')
            sys.exit(1)

    if args.step in ('2', 'all'):
        if args.engine in ('B', 'both'):
            print('\n>>> 运行 B 套（自抓 + 火山方舟 LLM）')
            try:
                run_step2(args.keyword, skip_images=args.skip_images)
            except Exception as e:
                print(f'  B 套失败：{e}')
        if args.engine in ('A', 'both'):
            print('\n>>> 运行 A 套（卖家精灵 listing-builder）')
            try:
                run_engine_a(args.keyword, args.asin)
            except Exception as e:
                print(f'  A 套失败：{e}')

    print('\n✅ 全部完成。git add/commit/push 后 Ctrl+F5 刷新前端。')


if __name__ == '__main__':
    main()
