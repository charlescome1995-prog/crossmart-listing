# -*- coding: utf-8 -*-
"""
CrossMart Listing — STEP 1: 关键词 → 对标 ASIN
================================================
流程：
  1. 输入关键词
  2. 用 Edge 唯一默认账户打开亚马逊搜索该关键词
  3. 抓取搜索结果前 N 个 ASIN（区分自然位 / 广告位）
  4. 逐个进入详情页抓取：标题、五点、价格、评分、评论数、品牌、BSR、徽章
  5. 按规则筛出「对标 ASIN」（评论多 + 评分高 + 自然排名靠前）
  6. 输出 data/output/benchmark-<keyword>.json

⛔ 铁律：浏览器抓取只用 Edge 唯一默认账户（端口 9225，不指定 profile）。
"""
import sys, os, re, json, time, argparse
from datetime import datetime

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
sys.stdout.reconfigure(encoding='utf-8')

from browser.edge_session import open_edge

OUTPUT_DIR = os.path.join(_THIS, 'data', 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 复用监控板块已验证的亚马逊抓取逻辑
_MONITOR_BROWSER = os.path.join(
    _THIS, '..', '..', 'crossmart-monitor', 'backend', 'browser')
_MONITOR_BROWSER = os.path.abspath(_MONITOR_BROWSER)
if _MONITOR_BROWSER not in sys.path:
    sys.path.insert(0, os.path.dirname(_MONITOR_BROWSER))  # 让 `browser.xxx` 可导入


def _safe(s):
    return re.sub(r'[^a-zA-Z0-9]+', '_', str(s)).strip('_')[:50]


def parse_search_page_asins(browser, max_asins=12):
    """从亚马逊搜索结果页提取 ASIN 列表（自然位 / 广告位）"""
    js = r'''(() => {
        var asins = [];
        var seen = new Set();
        var cards = document.querySelectorAll("[data-asin]:not([data-asin='']):not([data-asin-template]), .s-result-item[data-asin]");
        cards.forEach((el, i) => {
            var asin = el.getAttribute("data-asin") || "";
            if (asin && asin.startsWith("B0") && asin.length === 10 && !seen.has(asin)) {
                seen.add(asin);
                var sp = !!(
                    el.querySelector(".s-sponsored-info") ||
                    el.querySelector("[class*=sponsored]") ||
                    el.querySelector(".a-badge-container")
                );
                asins.push({ asin: asin, rank: i + 1, sponsored: sp });
            }
        });
        return JSON.stringify(asins.slice(0, 25));
    })()'''
    try:
        raw = browser.eval(js)
        if raw:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data[:max_asins]
    except Exception as e:
        print('  [JS err] ' + str(e))
    return []


def search_keyword(browser, keyword, max_asins=12):
    """打开亚马逊搜索页并提取 ASIN"""
    from browser.amazon_browser import AmazonBrowser
    print(f'  [search] {keyword}')
    amazon = AmazonBrowser(browser)
    amazon.browse_homepage()
    time.sleep(1)
    amazon.search(keyword)
    time.sleep(3)
    for attempt in range(8):
        asins = parse_search_page_asins(browser, max_asins)
        if len(asins) >= 5:
            print(f'    found {len(asins)} ASINs ({attempt+1} tries)')
            return asins
        time.sleep(1)
    asins = parse_search_page_asins(browser, max_asins)
    print(f'    final {len(asins)} ASINs')
    return asins


def fetch_asin_detail(browser, asin, keyword):
    """进入详情页抓取 listing 设计所需字段"""
    from browser.amazon_browser import AmazonBrowser
    from browser.asin_monitor import extract_asin_data
    print(f'    [fetch] {asin}')
    try:
        amazon = AmazonBrowser(browser)
        amazon.search_for_asin(asin)
        browser.scroll_down(times=1, min_pause=0.3, max_pause=0.8)
        time.sleep(2)
        data = extract_asin_data(browser)
        if not data.get('title'):
            return {}
        return {
            'asin': asin,
            'title': data.get('title', ''),
            'features': data.get('features', []),
            'price': data.get('price', ''),
            'rating': data.get('rating', ''),
            'reviews': data.get('review_count', ''),
            'brand': data.get('brand', ''),
            'bsr': data.get('bsr', ''),
            'bsr_subcategory': data.get('bsr_subcategory', ''),
            'badges': data.get('badges', []),
            'main_image': data.get('main_image', ''),
        }
    except Exception as e:
        print(f'    [fail] {asin}: {e}')
        return {}


def _to_int(v):
    try:
        return int(re.sub(r'[^\d]', '', str(v)) or 0)
    except Exception:
        return 0


def _to_float(v):
    try:
        m = re.search(r'[\d.]+', str(v))
        return float(m.group(0)) if m else 0.0
    except Exception:
        return 0.0


def select_benchmarks(details, top_n=5):
    """
    从抓取到的 ASIN 详情里挑「对标 ASIN」。
    评分逻辑：评论数(40%) + 评分(30%) + 自然位优先(20%) + 信息完整度(10%)
    """
    scored = []
    max_reviews = max([_to_int(d.get('reviews')) for d in details] + [1])
    for d in details:
        reviews = _to_int(d.get('reviews'))
        rating = _to_float(d.get('rating'))
        nat_bonus = 0 if d.get('sponsored') else 1
        completeness = 1 if (d.get('features') and len(d.get('features')) >= 3) else 0
        score = (
            0.40 * (reviews / max_reviews) * 100 +
            0.30 * (rating / 5.0) * 100 +
            0.20 * nat_bonus * 100 +
            0.10 * completeness * 100
        )
        d['benchmark_score'] = round(score, 1)
        scored.append(d)
    scored.sort(key=lambda x: x['benchmark_score'], reverse=True)
    return scored[:top_n]


def run_step1(keyword, max_asins=12, top_n=5):
    print('=' * 60)
    print(f' STEP 1 — 找对标 ASIN：{keyword}')
    print('=' * 60)
    br = open_edge()
    try:
        try:
            br.connect_tab(tab_url_filter='about:blank')
        except Exception:
            pass
        hits = search_keyword(br, keyword, max_asins)
        if not hits:
            print('  ❌ 未找到任何 ASIN')
            return None

        details = []
        for h in hits:
            d = fetch_asin_detail(br, h['asin'], keyword)
            if d and d.get('title'):
                d['sponsored'] = h.get('sponsored', False)
                d['search_rank'] = h.get('rank')
                details.append(d)
            time.sleep(1)

        if not details:
            print('  ❌ 未抓到任何详情')
            return None

        benchmarks = select_benchmarks(details, top_n)
        out = {
            'keyword': keyword,
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_scanned': len(details),
            'benchmarks': benchmarks,
            'all_asins': details,
        }
        path = os.path.join(OUTPUT_DIR, f'benchmark-{_safe(keyword)}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f'\n  ✅ 抓取 {len(details)} 个，选出 {len(benchmarks)} 个对标 ASIN')
        for b in benchmarks:
            print(f"     {b['benchmark_score']:5.1f}  {b['asin']}  "
                  f"⭐{b.get('rating')} ({b.get('reviews')})  {b.get('title','')[:50]}")
        print(f'  📄 输出：{path}')
        return out
    finally:
        br.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('keyword', help='搜索关键词')
    ap.add_argument('--max', type=int, default=12, help='最多扫描 ASIN 数')
    ap.add_argument('--top', type=int, default=5, help='选出对标 ASIN 数')
    args = ap.parse_args()
    run_step1(args.keyword, args.max, args.top)
