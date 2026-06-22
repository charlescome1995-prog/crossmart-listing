# -*- coding: utf-8 -*-
"""
CrossMart Listing — STEP 2: 对标 ASIN → 设计自己的 Listing
==========================================================
流程：
  1. 读取 STEP 1 输出的 benchmark-<keyword>.json
  2. 汇总对标 ASIN 的共性（高频卖点词、标题结构、价格带、五点要素）
  3. 喂给火山方舟 LLM，生成英文 Listing：
       - Title（含核心关键词 + 差异化卖点）
       - 5 个 Bullet Points
       - Product Description（A+ 文案建议）
       - Backend Search Terms
  4. 输出 ../frontend/data/listing-data.json（前端读这个）

输出语言：英文（亚马逊美国站）。
"""
import sys, os, re, json, argparse
from collections import Counter
from datetime import datetime

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
sys.stdout.reconfigure(encoding='utf-8')

from llm_client import chat_openai

OUTPUT_DIR = os.path.join(_THIS, 'data', 'output')
FRONTEND_JSON = os.path.join(_THIS, '..', 'frontend', 'data', 'listing-data.json')

STOPWORDS = set('''a an the and or for with of to in on at by from your you our we
this that these those is are be it its as new pack set use used using more most
high low best top great good premium quality product products amazon size color'''.split())


def _safe(s):
    return re.sub(r'[^a-zA-Z0-9]+', '_', str(s)).strip('_')[:50]


def _to_float(v):
    try:
        m = re.search(r'[\d.]+', str(v))
        return float(m.group(0)) if m else 0.0
    except Exception:
        return 0.0


def load_benchmark(keyword):
    path = os.path.join(OUTPUT_DIR, f'benchmark-{_safe(keyword)}.json')
    if not os.path.exists(path):
        raise FileNotFoundError(f'找不到 STEP1 输出：{path}\n请先运行 step1_find_benchmark.py')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def analyze_benchmarks(bm):
    """汇总对标 ASIN 共性"""
    benchmarks = bm.get('benchmarks', [])
    # 高频卖点词（从标题 + 五点）
    word_counter = Counter()
    for b in benchmarks:
        text = (b.get('title', '') + ' ' + ' '.join(b.get('features', []))).lower()
        for w in re.findall(r"[a-z][a-z0-9'\-]{2,}", text):
            if w not in STOPWORDS:
                word_counter[w] += 1
    top_words = [w for w, c in word_counter.most_common(25)]

    prices = [_to_float(b.get('price')) for b in benchmarks if _to_float(b.get('price')) > 0]
    price_range = (min(prices), max(prices)) if prices else (0, 0)

    return {
        'top_keywords': top_words,
        'price_range': price_range,
        'sample_titles': [b.get('title', '') for b in benchmarks[:5]],
        'sample_features': [f for b in benchmarks[:5] for f in b.get('features', [])][:20],
    }


def build_prompt(keyword, analysis):
    pr = analysis['price_range']
    return f"""You are an expert Amazon US listing copywriter and SEO specialist.

TARGET KEYWORD: "{keyword}"

COMPETITOR ANALYSIS (top benchmark ASINs for this keyword):
- High-frequency selling-point words: {', '.join(analysis['top_keywords'])}
- Competitor price range: ${pr[0]:.2f} - ${pr[1]:.2f}
- Sample competitor titles:
{chr(10).join('  * ' + t for t in analysis['sample_titles'])}
- Sample competitor bullet points:
{chr(10).join('  * ' + f[:150] for f in analysis['sample_features'][:12])}

TASK: Design a NEW, differentiated Amazon listing that can compete with and stand out from the above. Follow Amazon US best practices.

Return STRICT JSON only (no markdown, no commentary) with this exact schema:
{{
  "title": "<=200 chars, lead with brand placeholder [BRAND], include the target keyword and 2-3 top differentiators",
  "bullets": ["5 bullet points, each starts with a CAPITALIZED benefit phrase then a colon, 150-250 chars each"],
  "description": "180-300 word product description suitable for A+ content, persuasive and benefit-driven",
  "search_terms": "backend search terms, space-separated, no commas, no brand names, <=240 chars, complementary long-tail keywords not already in title",
  "differentiation_notes": ["3-5 short notes on how this listing differentiates from competitors"]
}}

All output must be in ENGLISH. Output ONLY the JSON object."""


def generate_listing(keyword, analysis):
    prompt = build_prompt(keyword, analysis)
    print('  [LLM] 生成 listing 中...')
    raw = chat_openai(prompt, system='You are a precise JSON-only Amazon listing generator.',
                      max_tokens=2000, temperature=0.4)
    # 抽取 JSON
    raw = raw.strip()
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception as e:
        print(f'  [warn] JSON 解析失败：{e}')
        return {'_raw': raw, '_parse_error': str(e)}


def run_step2(keyword):
    print('=' * 60)
    print(f' STEP 2 — 设计 Listing：{keyword}')
    print('=' * 60)
    bm = load_benchmark(keyword)
    analysis = analyze_benchmarks(bm)
    print(f"  对标 ASIN：{len(bm.get('benchmarks', []))} 个")
    print(f"  高频词：{', '.join(analysis['top_keywords'][:12])}")
    listing = generate_listing(keyword, analysis)

    out = {
        'keyword': keyword,
        'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'benchmark_count': len(bm.get('benchmarks', [])),
        'analysis': analysis,
        'listing': listing,
        'benchmarks': bm.get('benchmarks', []),
    }
    os.makedirs(os.path.dirname(FRONTEND_JSON), exist_ok=True)
    with open(FRONTEND_JSON, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    # 也存一份带关键词名的存档
    archive = os.path.join(OUTPUT_DIR, f'listing-{_safe(keyword)}.json')
    with open(archive, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print('\n  ✅ Listing 生成完成')
    if isinstance(listing, dict) and listing.get('title'):
        print(f"     Title: {listing['title'][:80]}")
        print(f"     Bullets: {len(listing.get('bullets', []))}")
    print(f'  📄 前端数据：{FRONTEND_JSON}')
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('keyword', help='关键词（需先跑过 step1）')
    args = ap.parse_args()
    run_step2(args.keyword)
