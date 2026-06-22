#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快照存储 + 变化对比引擎
管理ASIN/关键词的历史快照，检测变化，生成摘要
"""
import sys, os, json, re
sys.stdout.reconfigure(encoding='utf-8')
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/ 的父目录 = 项目根
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "processed")

os.makedirs(DATA_DIR, exist_ok=True)


# ══════════════════════════════════════════════════
# 快照管理
# ══════════════════════════════════════════════════

def _asin_dir(asin):
    """ASIN的数据目录"""
    d = os.path.join(DATA_DIR, f"asin_{asin}")
    os.makedirs(d, exist_ok=True)
    return d


def _keyword_dir(keyword):
    """关键词的数据目录"""
    safe = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fff]', '_', keyword)[:40]
    d = os.path.join(DATA_DIR, f"kw_{safe}")
    os.makedirs(d, exist_ok=True)
    return d


# ══════════════════════════════════════════════════
# ASIN 元数据（首次写入后锁定）
# ══════════════════════════════════════════════════

META_FILE = "_meta.json"


def save_asin_meta(asin, related_asins):
    """
    保存ASIN关联ASIN元数据（首次发现后固定，后续不覆盖）
    related_asins: [{"asin": "B0XXXXXXX", "source": "competitor|keyword_reversal|ads"}, ...]
    """
    d = _asin_dir(asin)
    meta_path = os.path.join(d, META_FILE)
    if os.path.exists(meta_path):
        print(f"  [meta] _meta.json 已存在，跳过写入")
        return
    meta = {
        "asin": asin,
        "related_asins": related_asins,
        "first_seen": datetime.now().isoformat(),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"  [meta] _meta.json 已写入，{len(related_asins)} 个关联ASIN（首次固定）")
    return meta


def load_asin_meta(asin):
    """加载ASIN关联ASIN元数据"""
    meta_path = os.path.join(_asin_dir(asin), META_FILE)
    if not os.path.exists(meta_path):
        return None
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_asin_snapshot(asin, data):
    """
    保存ASIN快照
    data = {
        "price": "$28.99",
        "rating": "4.2",
        "review_count": "342",
        "bsr": "#1,234",
        "title": "...",
        "competitor_count": "12",
        "estimated_sales": "800-1200",
        "screenshots": [...],
        "raw_text": "...",
        "notes": "...",
    }
    """
    d = _asin_dir(asin)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot = {
        "asin": asin,
        "timestamp": datetime.now().isoformat(),
        "data": data,
    }

    path = os.path.join(d, f"snapshot_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    # 也保存一个 latest.json（最新快照的引用）
    latest_path = os.path.join(d, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    # 清理过期快照（保留最近48小时的）
    _clean_old_snapshots(d)

    print(f"  💾 快照已保存: {path}")
    return path


def load_latest_asin(asin):
    """加载ASIN的最新快照"""
    latest_path = os.path.join(_asin_dir(asin), "latest.json")
    if not os.path.exists(latest_path):
        return None
    with open(latest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_previous_asin(asin):
    """加载上一个快照（不是latest，是倒数第二个）"""
    d = _asin_dir(asin)
    snapshots = sorted([f for f in os.listdir(d) if f.startswith("snapshot_") and f.endswith(".json")])
    if len(snapshots) < 2:
        return None
    prev_path = os.path.join(d, snapshots[-2])
    with open(prev_path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_asin_snapshots(asin, limit=10):
    """列出ASIN的所有快照（由新到旧）"""
    d = _asin_dir(asin)
    snaps = sorted([f for f in os.listdir(d) if f.startswith("snapshot_") and f.endswith(".json")],
                   reverse=True)
    result = []
    for s in snaps[:limit]:
        with open(os.path.join(d, s), "r", encoding="utf-8") as f:
            snap = json.load(f)
            result.append({
                "file": s,
                "timestamp": snap.get("timestamp", ""),
            })
    return result


def _clean_old_snapshots(d, hours=48):
    """删除48小时前的快照"""
    now = datetime.now()
    for f in os.listdir(d):
        if not (f.startswith("snapshot_") and f.endswith(".json")):
            continue
        path = os.path.join(d, f)
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        if (now - mtime) > timedelta(hours=hours):
            os.remove(path)


# ══════════════════════════════════════════════════
# 变化对比
# ══════════════════════════════════════════════════

def _extract_price(text):
    """从文本中提取价格"""
    m = re.search(r'\$?(\d+\.?\d*)', text)
    return float(m.group(1)) if m else None


def _extract_rating(text):
    """提取评分"""
    m = re.search(r'([45]\.[0-9]) out of 5', text)
    if m: return float(m.group(1))
    m = re.search(r'(\d\.\d)\s*★', text)
    if m: return float(m.group(1))
    return None


def _extract_review_count(text):
    """提取评论数"""
    m = re.search(r'([\d,]+)\s*(?:ratings?|reviews?)', text, re.I)
    if m: return int(m.group(1).replace(',', ''))
    return None


def _extract_bsr(text):
    """提取BSR排名"""
    m = re.search(r'#([\d,]+)\s*(?:in|Best Sellers Rank)', text, re.I)
    if m: return int(m.group(1).replace(',', ''))
    m = re.search(r'Best Sellers Rank\s*[#]?([\d,]+)', text, re.I)
    if m: return int(m.group(1).replace(',', ''))
    return None


def parse_asin_data(raw_text):
    """从页面文本解析ASIN关键指标"""
    return {
        "price": _extract_price(raw_text),
        "rating": _extract_rating(raw_text),
        "review_count": _extract_review_count(raw_text),
        "bsr": _extract_bsr(raw_text),
    }


def diff_asin(old, new):
    """
    对比两个ASIN快照，返回变化摘要
    old/new: 从快照中取 data 字段
    """
    changes = []

    # 价格对比
    old_p = _extract_price(str(old.get("price", "")) or "")
    new_p = _extract_price(str(new.get("price", "")) or "")
    if old_p and new_p and old_p != new_p:
        diff = new_p - old_p
        pct = (diff / old_p) * 100
        direction = "↑" if diff > 0 else "↓"
        changes.append(f"价格 {direction} ${abs(diff):.2f} ({pct:+.1f}%)")

    # 评分对比
    old_r = _extract_rating(str(old.get("rating", "")) or "")
    new_r = _extract_rating(str(new.get("rating", "")) or "")
    if old_r and new_r and abs(old_r - new_r) > 0.05:
        diff = new_r - old_r
        direction = "↑" if diff > 0 else "↓"
        changes.append(f"评分 {direction} {abs(diff):.1f}★")

    # 评论数对比
    old_c = _extract_review_count(str(old.get("review_count", "")) or "")
    new_c = _extract_review_count(str(new.get("review_count", "")) or "")
    if old_c and new_c and old_c != new_c:
        diff = new_c - old_c
        direction = "↑" if diff > 0 else "↓"
        changes.append(f"评论 {direction} {abs(diff)}条")

    # BSR对比
    old_b = _extract_bsr(str(old.get("bsr", "")) or "")
    new_b = _extract_bsr(str(new.get("bsr", "")) or "")
    if old_b and new_b and old_b != new_b:
        diff = new_b - old_b
        direction = "↓" if diff > 0 else "↑"  # BSR数字越小越好
        changes.append(f"BSR {direction} (从{old_b:,} → {new_b:,})")

    return {
        "has_changes": len(changes) > 0,
        "changes": changes,
        "old_data": {"price": old_p, "rating": old_r, "review_count": old_c, "bsr": old_b},
        "new_data": {"price": new_p, "rating": new_r, "review_count": new_c, "bsr": new_b},
    }


def diff_summary(asin, changes):
    """生成人类可读的变化摘要字符串"""
    if not changes["has_changes"]:
        return f"{asin} | 无变化"

    parts = [f"ASIN {asin}"]
    parts.extend(changes["changes"])
    return " | ".join(parts)


def generate_report(asin, amazon_data=None, sprite_data=None, screenshot_paths=None):
    """
    生成一次完整检查的报告
    """
    # 加载上一次快照
    previous = load_previous_asin(asin)

    # 解析当前数据
    current_raw = {}
    if amazon_data:
        current_raw.update(amazon_data)
    if sprite_data and "competitor" in sprite_data:
        raw_text = sprite_data["competitor"].get("text", "")
        parsed = parse_asin_data(raw_text)
        current_raw.update(parsed)
        # 卖家精灵页面文本可能包含更多信息
        current_raw["sprite_raw"] = raw_text[:1000]

    # 对比
    changes = {"has_changes": False, "changes": []}
    if previous:
        changes = diff_asin(previous.get("data", {}), current_raw)

    # 构建报告
    report = {
        "asin": asin,
        "timestamp": datetime.now().isoformat(),
        "changes": changes,
        "summary": diff_summary(asin, changes),
        "data": current_raw,
        "screenshots": screenshot_paths or [],
    }

    return report


# ══════════════════════════════════════════════════
# 关键词快照
# ══════════════════════════════════════════════════

def save_keyword_snapshot(keyword, data):
    """保存关键词快照"""
    d = _keyword_dir(keyword)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot = {
        "keyword": keyword,
        "timestamp": datetime.now().isoformat(),
        "data": data,
    }
    path = os.path.join(d, f"snapshot_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    latest_path = os.path.join(d, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    _clean_old_snapshots(d)
    print(f"  💾 关键词快照已保存")
    return path