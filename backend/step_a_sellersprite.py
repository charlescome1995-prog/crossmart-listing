# -*- coding: utf-8 -*-
"""
CrossMart Listing — A 套（老逻辑 / 卖家精灵 listing-builder）
============================================================
思路（沿用 amazon_ai_kit/pipelines/final_listing.py 的寄生方案，但接入
新的 Edge 唯一默认账户铁律 + 结构化输出）：

  1. 读取 STEP1 输出的 benchmark-<keyword>.json，取评分最高的对标 ASIN
  2. 用 Edge 唯一默认账户打开卖家精灵 listing-builder
  3. 输入对标 ASIN → 点「获取Listing」拿原始 → 点「AI生成标题 / AI生成描述」
  4. 提取卖家精灵 AI 生成的标题 / 五点 / 描述（结构化）
  5. 输出 ../frontend/data/listing-data-A.json（A 套结果）

⛔ 铁律：浏览器只用 Edge 唯一默认账户（端口 9225，不指定 profile）。
⚠️ 卖家精灵需已登录（默认账户带登录态缓存）。UI 改版会影响选择器，
   选择器集中在 SELECTORS 区，便于维护。
"""
import sys, os, re, json, time, argparse
from datetime import datetime

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)
sys.stdout.reconfigure(encoding='utf-8')

from browser.edge_session import open_edge

OUTPUT_DIR = os.path.join(_THIS, 'data', 'output')
FRONTEND_JSON = os.path.join(_THIS, '..', 'frontend', 'data', 'listing-data-A.json')
os.makedirs(OUTPUT_DIR, exist_ok=True)

LISTING_BUILDER_URL = 'https://www.sellersprite.com/v3/listing-builder'

# ─── 卖家精灵 UI 关键词（集中维护，改版只改这里）───
BTN_GET_LISTING = '获取Listing'
BTN_AI_TITLE = 'AI生成标题'
BTN_AI_DESC = 'AI生成描述'      # 五点描述
BTN_AI_DESC_ALT = 'AI生成'      # 兜底
PH_ASIN = 'asin'                # ASIN 输入框 placeholder 含此词
PH_TITLE = '写一个标题'          # 标题 textarea placeholder 含此词


def _safe(s):
    return re.sub(r'[^a-zA-Z0-9]+', '_', str(s)).strip('_')[:50]


def load_benchmark(keyword):
    path = os.path.join(OUTPUT_DIR, f'benchmark-{_safe(keyword)}.json')
    if not os.path.exists(path):
        raise FileNotFoundError(
            f'找不到 STEP1 输出：{path}\n请先运行 step1_find_benchmark.py')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _input_asin(br, asin):
    """在卖家精灵页面找 ASIN 输入框并填值（React 受控输入兼容写法）"""
    js = r'''(() => {
        var inputs = document.querySelectorAll('input');
        for (var i = 0; i < inputs.length; i++) {
            var inp = inputs[i];
            var ph = (inp.placeholder || '').toLowerCase();
            if (ph.indexOf("%s") >= 0 && inp.offsetParent !== null) {
                var native = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                native.call(inp, "%s");
                inp.dispatchEvent(new Event("input", {bubbles:true}));
                inp.dispatchEvent(new Event("change", {bubbles:true}));
                return "ok:placeholder";
            }
        }
        // 兜底：第一个可见 text 输入框
        for (var j = 0; j < inputs.length; j++) {
            var x = inputs[j];
            if (x.offsetParent !== null && (x.type === 'text' || !x.type)) {
                var nat = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                nat.call(x, "%s");
                x.dispatchEvent(new Event("input", {bubbles:true}));
                x.dispatchEvent(new Event("change", {bubbles:true}));
                return "ok:first";
            }
        }
        return "no-input";
    })()''' % (PH_ASIN, asin, asin)
    return br.eval(js)


def _click_button(br, text):
    """按文本点击按钮（支持 button 和 element-ui .el-button）"""
    js = r'''(() => {
        var btns = document.querySelectorAll('button, .el-button, a');
        for (var i = 0; i < btns.length; i++) {
            var b = btns[i];
            var t = (b.textContent || '').trim();
            if (t.indexOf("%s") >= 0 && b.offsetParent !== null) {
                b.click();
                return "clicked:" + t.substring(0, 20);
            }
        }
        return "not-found";
    })()''' % text
    return br.eval(js)


def _extract_listing(br):
    """提取页面上所有 textarea 的内容，识别标题 / 五点 / 描述"""
    js = r'''(() => {
        var areas = document.querySelectorAll('textarea');
        var out = [];
        areas.forEach(function(ta) {
            var ph = ta.placeholder || '';
            var val = ta.value || '';
            if (val && val.length > 5) {
                out.push({placeholder: ph.substring(0, 40), value: val});
            }
        });
        return JSON.stringify(out);
    })()'''
    raw = br.eval(js)
    try:
        fields = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        fields = []

    title, bullets, description = '', [], ''
    for f in fields:
        ph = (f.get('placeholder') or '')
        val = (f.get('value') or '').strip()
        if not val:
            continue
        if PH_TITLE in ph or ('标题' in ph):
            if len(val) > len(title):
                title = val
        elif '描述' in ph or '五点' in ph or '卖点' in ph:
            # 五点：按行/分隔拆分
            parts = [p.strip() for p in re.split(r'[\n\r]+|•|·|\u25cf', val) if p.strip()]
            if len(parts) >= 2:
                bullets = parts[:5]
            else:
                description = val
        else:
            # 最长的那段当描述兜底
            if len(val) > len(description) and len(val) > 60:
                description = val
    # 如果没识别出标题，取最长非五点段
    if not title and fields:
        cand = max((f.get('value', '') for f in fields), key=len, default='')
        title = cand.strip()
    return {
        'title': title,
        'bullets': bullets,
        'description': description,
        '_raw_fields': fields,
    }


def run_engine_a(keyword, asin=None, wait=4):
    print('=' * 60)
    print(f' A 套（卖家精灵 listing-builder）：{keyword}')
    print('=' * 60)

    # 取对标 ASIN（默认用 STEP1 评分最高的）
    if not asin:
        bm = load_benchmark(keyword)
        benchmarks = bm.get('benchmarks', [])
        if not benchmarks:
            print('  ❌ benchmark 里没有对标 ASIN')
            return None
        asin = benchmarks[0]['asin']
        print(f'  对标 ASIN（评分最高）：{asin}  {benchmarks[0].get("title","")[:50]}')

    br = open_edge()
    try:
        print(f'  [nav] {LISTING_BUILDER_URL}')
        br.navigate(LISTING_BUILDER_URL, wait_min=wait, wait_max=wait + 2)

        # 登录态检查
        title_now = (br.eval('document.title') or '')
        if '登录' in title_now or 'login' in title_now.lower():
            print('  ⚠️ 卖家精灵未登录，请在 Edge 默认账户里先登录卖家精灵后重试')
            return None

        print(f'  [input ASIN] {asin}: {_input_asin(br, asin)}')
        time.sleep(1.5)

        print(f'  [click] {BTN_GET_LISTING}: {_click_button(br, BTN_GET_LISTING)}')
        time.sleep(wait)

        print(f'  [click] {BTN_AI_TITLE}: {_click_button(br, BTN_AI_TITLE)}')
        time.sleep(wait + 2)

        r = _click_button(br, BTN_AI_DESC)
        if r == 'not-found':
            r = _click_button(br, BTN_AI_DESC_ALT)
        print(f'  [click] {BTN_AI_DESC}: {r}')
        time.sleep(wait + 2)

        listing = _extract_listing(br)
        print(f'  [extract] title={len(listing["title"])} chars, '
              f'bullets={len(listing["bullets"])}, desc={len(listing["description"])} chars')

        out = {
            'engine': 'A',
            'engine_name': '卖家精灵 listing-builder',
            'keyword': keyword,
            'source_asin': asin,
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'listing': listing,
        }
        with open(FRONTEND_JSON, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        archive = os.path.join(OUTPUT_DIR, f'listing-A-{_safe(keyword)}.json')
        with open(archive, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

        print(f'\n  ✅ A 套完成')
        if listing['title']:
            print(f'     Title: {listing["title"][:80]}')
        print(f'  📄 前端数据：{FRONTEND_JSON}')
        return out
    finally:
        br.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('keyword', help='关键词（需先跑过 step1）')
    ap.add_argument('--asin', default=None, help='指定对标 ASIN（默认用 STEP1 评分最高）')
    args = ap.parse_args()
    run_engine_a(args.keyword, args.asin)
