#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人类行为模拟 - 控制节奏、随机化、伪装，降低被亚马逊风控识别的概率
"""
import random, time, json
from datetime import datetime, timedelta

# ─── 今日种子（基于日期，确保每天不固定但一天内一致） ───
_TODAY_SEED = int(datetime.now().strftime("%Y%m%d"))
_RNG = random.Random(_TODAY_SEED)


# ══════════════════════════════════════════════════
# 时间管理
# ══════════════════════════════════════════════════

def is_within_window(last_check_str):
    """
    检查是否已超过最小间隔（4-7小时随机）
    返回 True = 可以检查，False = 还太早
    """
    if not last_check_str:
        return True

    from datetime import datetime
    last = datetime.fromisoformat(last_check_str)
    now = datetime.now()
    diff_hours = (now - last).total_seconds() / 3600

    # 最小间隔在 3.5 ~ 6.5 小时之间随机，每天一个
    min_gap = 3.5 + _RNG.uniform(0, 3)
    return diff_hours >= min_gap


def get_daily_plan(min_checks=2, max_checks=4):
    """
    生成今天的检查计划（随机时间点）
    返回一个时间列表，比如 ["09:15", "14:30", "20:45"]
    """
    # 可用时间段：7-11点 / 13-17点 / 18-23点
    windows = [
        (7, 11),
        (13, 17),
        (18, 23),
    ]

    # 今天做多少次检查（2-4次随机）
    count = _RNG.randint(min_checks, max_checks)
    random.shuffle(windows, _RNG.random)

    plan = []
    for i in range(min(count, len(windows))):
        start_h, end_h = windows[i]
        h = start_h + _RNG.random() * (end_h - start_h)
        plan.append(f"{int(h):02d}:{int((h % 1) * 60):02d}")

    plan.sort()
    return plan


def time_to_next_check(plan):
    """计算距离下次检查还有多久（秒）"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    for t in plan:
        check_time = datetime.strptime(f"{today} {t}", "%Y-%m-%d %H:%M")
        if check_time > now:
            return (check_time - now).total_seconds()

    # 所有时间已过，明天
    return None


# ══════════════════════════════════════════════════
# 随机停留
# ══════════════════════════════════════════════════

def human_pause(min_sec=1, max_sec=5):
    """人类自然停顿（非均匀分布）"""
    # 偏向短停顿（像真人的阅读节奏）
    bias = random.triangular(min_sec, max_sec, min_sec * 1.2)
    time.sleep(max(0.5, bias))


def read_pause():
    """假装在阅读内容（1-5秒）"""
    time.sleep(random.uniform(1, 5))


def think_pause():
    """假装在犹豫思考（1-3秒）"""
    time.sleep(random.uniform(1, 3))


# ══════════════════════════════════════════════════
# 行为序列
# ══════════════════════════════════════════════════

# 常见亚马逊搜索词池（通用品类）
_COMMON_SEARCHES = [
    "beauty products",
    "gift for women",
    "gift for men",
    "home decor",
    "kitchen gadgets",
    "phone accessories",
    "office supplies",
    "pet supplies",
    "travel accessories",
    "fitness equipment",
    "makeup organizer",
    "storage solutions",
    "bathroom accessories",
    "outdoor gear",
    "winter warmers",
]


def random_amazon_search():
    """随机选一个看似自然的搜索词"""
    return random.choice(_COMMON_SEARCHES)


def random_category():
    """随机选一个类目名（模拟逛类目）"""
    cats = [
        "Beauty & Personal Care",
        "Home & Kitchen",
        "Electronics",
        "Clothing",
        "Sports & Outdoors",
        "Pet Supplies",
        "Health & Household",
        "Office Products",
    ]
    return random.choice(cats)