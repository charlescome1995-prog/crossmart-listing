# -*- coding: utf-8 -*-
"""
CrossMart Listing 配置
"""
import os

_THIS = os.path.dirname(os.path.abspath(__file__))

# 输出目录
OUTPUT_DIR = os.path.join(_THIS, 'data', 'output')

# 抓取参数
MAX_SCAN_ASINS = 12      # 每个关键词最多扫描的 ASIN 数
TOP_BENCHMARKS = 5       # 选出的对标 ASIN 数

# 对标 ASIN 评分权重
BENCHMARK_WEIGHTS = {
    'reviews': 0.40,        # 评论数（市场验证）
    'rating': 0.30,         # 评分（口碑）
    'natural_rank': 0.20,   # 自然位优先（非广告）
    'completeness': 0.10,   # 信息完整度（五点齐全）
}

# LLM 生成参数
LLM_MAX_TOKENS = 2000
LLM_TEMPERATURE = 0.4
