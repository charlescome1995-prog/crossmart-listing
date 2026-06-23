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

from llm_client import chat_openai, gen_image, download_image

OUTPUT_DIR = os.path.join(_THIS, 'data', 'output')
# B 套结果（自抓 + 火山方舟）
FRONTEND_JSON = os.path.join(_THIS, '..', 'frontend', 'data', 'listing-data-B.json')
# 兼容旧前端：同时写一份 listing-data.json
FRONTEND_JSON_LEGACY = os.path.join(_THIS, '..', 'frontend', 'data', 'listing-data.json')
# A+ 模块配图输出目录（前端可直接引用）
IMAGE_DIR = os.path.join(_THIS, '..', 'frontend', 'data', 'images')

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
  "differentiation_notes": ["3-5 short notes on how this listing differentiates from competitors"],
  "aplus_modules": [
    {{
      "type": "one of: brand_story | feature_highlight | comparison | how_to_use | lifestyle_scene | specifications",
      "heading": "short module headline (<=60 chars)",
      "body": "module body copy, 40-80 words, benefit-driven",
      "image_prompt": "a detailed ENGLISH text-to-image prompt to generate the module visual: describe scene, composition, lighting, style, mood. NO text/words in image, NO brand logos, NO copyrighted characters. Photorealistic commercial product photography style."
    }}
  ]
}}

Provide 4-5 aplus_modules covering different module types (include at least one lifestyle_scene and one feature_highlight). Each image_prompt must be original (do NOT reference or copy any competitor imagery).

All output must be in ENGLISH. Output ONLY the JSON object."""


def generate_listing(keyword, analysis):
    prompt = build_prompt(keyword, analysis)
    print('  [LLM] 生成 listing 中...')
    raw = ''
    # coding model 偶发返回空内容，重试最多 3 次
    for attempt in range(3):
        raw = (chat_openai(prompt, system='You are a precise JSON-only Amazon listing generator.',
                           max_tokens=8000, temperature=0.4) or '').strip()
        if raw:
            break
        print(f'  [retry] LLM 返回空，重试 {attempt + 1}/3')
    # 抽取 JSON
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception as e:
        # 尝试修复被截断的 JSON（补全未闭合的引号/括号）
        repaired = _repair_truncated_json(raw)
        if repaired is not None:
            print('  [repair] 检测到截断，已自动补全 JSON')
            return repaired
        print(f'  [warn] JSON 解析失败：{e}')
        return {'_raw': raw, '_parse_error': str(e)}


def _repair_truncated_json(s):
    """尝试修复被 max_tokens 截断的 JSON：删到最后一个完整元素，再补闭合括号。"""
    if not s or '{' not in s:
        return None
    # 从末尾向前找最后一个完整的 } 或 "，逐步补齐
    for cut in range(len(s), 0, -1):
        frag = s[:cut].rstrip().rstrip(',')
        # 统计未闭合的 { [ 
        depth_obj = frag.count('{') - frag.count('}')
        depth_arr = frag.count('[') - frag.count(']')
        if depth_obj < 0 or depth_arr < 0:
            continue
        candidate = frag + (']' * depth_arr) + ('}' * depth_obj)
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def generate_module_images(listing, keyword, skip_images=False):
    """为 A+ 模块生成配图。成功的模块会被加上 image_url（本地相对路径）。
    skip_images=True 时只保留 image_prompt 不出图。"""
    if not isinstance(listing, dict):
        return listing
    modules = listing.get('aplus_modules') or []
    if not modules:
        return listing
    kw_safe = _safe(keyword)
    for idx, mod in enumerate(modules):
        ip = (mod.get('image_prompt') or '').strip()
        if not ip or skip_images:
            continue
        try:
            print(f'  [image] 模块 {idx+1}/{len(modules)} 出图中 ({mod.get("type", "")})...')
            url = gen_image(ip, size='1024x1024')
            fname = f'{kw_safe}_module{idx+1}.jpeg'
            dest = os.path.join(IMAGE_DIR, fname)
            download_image(url, dest)
            # 前端从 frontend/ 加载，相对路径为 data/images/<fname>
            mod['image_url'] = f'data/images/{fname}'
            print(f'  [image] ✅ 已保存 {fname}')
        except Exception as e:
            mod['image_error'] = str(e)[:160]
            print(f'  [image] ⚠️ 模块 {idx+1} 出图失败: {str(e)[:120]}')
    return listing


def run_step2(keyword, skip_images=False):
    print('=' * 60)
    print(f' STEP 2 — 设计 Listing：{keyword}')
    print('=' * 60)
    bm = load_benchmark(keyword)
    analysis = analyze_benchmarks(bm)
    print(f"  对标 ASIN：{len(bm.get('benchmarks', []))} 个")
    print(f"  高频词：{', '.join(analysis['top_keywords'][:12])}")
    listing = generate_listing(keyword, analysis)

    # ── 为 A+ 模块生成配图 ──
    listing = generate_module_images(listing, keyword, skip_images=skip_images)

    out = {
        'keyword': keyword,
        'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'benchmark_count': len(bm.get('benchmarks', [])),
        'analysis': analysis,
        'listing': listing,
        'benchmarks': bm.get('benchmarks', []),
    }
    out['engine'] = 'B'
    out['engine_name'] = '自抓亚马逊 + 火山方舟 LLM'
    os.makedirs(os.path.dirname(FRONTEND_JSON), exist_ok=True)
    with open(FRONTEND_JSON, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open(FRONTEND_JSON_LEGACY, 'w', encoding='utf-8') as f:
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
    ap.add_argument('--skip-images', action='store_true', help='不生成配图（只出文案+image_prompt）')
    args = ap.parse_args()
    run_step2(args.keyword, skip_images=args.skip_images)
