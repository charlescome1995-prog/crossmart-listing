#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASIN监控主入口 — 完整版
用法:
  python browser/asin_monitor.py B0XXXXXXX           # 完整检查(亚马逊+卖家精灵)
  python browser/asin_monitor.py B0XXXXXXX --amazon  # 只查亚马逊
  python browser/asin_monitor.py B0XXXXXXX --discover  # 只做竞品关联发现（不查亚马逊）
  python browser/asin_monitor.py B0XXXXXXX --status   # 查看状态
"""
import sys, os, json, time, random, re
sys.stdout.reconfigure(encoding='utf-8')
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from browser.cdp_bridge import CDPBrowser
from browser.amazon_browser import AmazonBrowser
from browser.sprite_bridge import SpriteBrowser
from browser.snapshot_storage import (
    save_asin_snapshot, load_latest_asin, diff_asin, diff_summary,
    save_asin_meta, load_asin_meta,
)
from browser.human_timer import get_daily_plan

# ─── DOM数据提取工具 ───

def extract_sprite_plugin_data(browser: CDPBrowser):
    """从亚马逊页面的卖家精灵插件 DOM 提取数据。
    
    2026-06-17 优化: 轮询等待机制，直到插件加载出关键数据或超时
    - auto-active 模式：扩展自动注入DOM，无需点击
    - 最长等待 90 秒，每秒钟检查一次
    - 找到质量得分/近30天销量即判定就绪，提前退出
    - 等待中自动滚动页面帮助插件加载
    """
    # 轮询等待直到插件DOM就绪或超时
    deadline = time.time() + 90
    plugin_ready = False
    while time.time() < deadline:
        elapsed = time.time() - (deadline - 90)
        
        # 快速检查是否有插件数据
        check_js = """(() => {
            return document.body.textContent.includes('质量得分') || 
                   document.body.textContent.includes('近30天销量') ||
                   document.getElementById('seller-sprite-extension-quick-view-listing') != null;
        })()"""
        try:
            has_data = browser.eval(check_js)
            if has_data:
                plugin_ready = True
                print(f"  [插件] 就绪，等待 {elapsed:.1f}s")
                break
        except:
            pass
        
        # 每5秒打印进度，顺便滚动页面
        if int(elapsed) % 5 == 0 and int(elapsed) > 0:
            print(f"  [插件] 等待中... {elapsed:.0f}s (未找到数据，继续等待+滚动)")
            try:
                browser.scroll_down(times=1, min_pause=0.2, max_pause=0.5)
            except:
                pass
        
        time.sleep(1)
    
    if not plugin_ready:
        print("  [插件] 等待超时(90s)，可能未登录/未激活自动显示，继续执行")
    
    # ── 提取 DOM 数据 ──
    js_get_plugin_text = r"""
(function(){
    var ids = [
        'seller-sprite-extension-quick-view-listing-page',
        'seller-sprite-extension-quick-view-listing',
        'seller-sprite-extension-main-relation',
        'sellersprite-extension-inventory'
    ];
    var data = {};
    for (var i = 0; i < ids.length; i++) {
        var el = document.getElementById(ids[i]);
        if (el) {
            if (ids[i] === 'seller-sprite-extension-main-relation') {
                data[ids[i]] = el.innerHTML;
            } else {
                data[ids[i]] = (el.textContent||'').trim();
            }
        }
    }
    // 备用：直接从页面 DOM 树中提取插件数据（overlay 模式下）
    // 找所有包含关键数据的 div
    var dataEls = [];
    document.querySelectorAll('div').forEach(function(el){
        var txt = el.textContent || '';
        if (txt.includes('质量得分') || txt.includes('近30天销量') || txt.includes('Listing销售额')) {
            dataEls.push(el.textContent.trim());
        }
    });
    if (dataEls.length > 0) {
        data['fallback_text'] = dataEls.join(' | ');
    }
    return JSON.stringify(data);
})()
"""
    try:
        raw = browser.eval(js_get_plugin_text)
        if not raw:
            return {}
        plugin_texts = json.loads(raw) if isinstance(raw, str) else raw
        metrics_text = plugin_texts.get('seller-sprite-extension-quick-view-listing-page', '')
        main_text   = plugin_texts.get('seller-sprite-extension-quick-view-listing', '')
        traffic_text = plugin_texts.get('seller-sprite-extension-main-relation', '')
        inv_text    = plugin_texts.get('sellersprite-extension-inventory', '')
    except Exception as e:
        print("  [插件] DOM 提取失败: " + str(e))
        return {}

    combined = (metrics_text + ' ' + main_text).replace('\n', ' ').replace('  ', ' ')
    data = {}

    # ── 指标面板字段 ──
    v = re.search(r'v([\d.]+)', metrics_text)
    if v: data['plugin_version'] = v.group(1)
    lqs = re.search(r'质量得分([\d.]+)', metrics_text)
    if lqs: data['lqs'] = lqs.group(1)


    sales = re.search(r'近30天销量\(父体\)([\d,]+)', combined)
    if sales:
        data['sales_30d_parent'] = sales.group(1).replace(',', '')
    sales_child = re.search(r'近30天销量\(子体\)([\d,]+)', combined)
    if sales_child:
        data['sales_30d_child'] = sales_child.group(1).replace(',', '')

    rev = re.search(r'Listing销售额\s+\$([\d,]+)', combined)
    if rev: data['revenue_30d'] = rev.group(1).replace(',', '')
    avg = re.search(r'均价\s+\$([\d.]+)', combined)
    if avg: data['avg_price'] = avg.group(1)
    bsr = re.search(r'BSR([\d,]+)', combined)
    if bsr: data['bsr'] = bsr.group(1).replace(',', '')
    fba = re.search(r'FBA费用\$([\d.]+)', combined)
    if fba: data['fba_fee'] = fba.group(1)
    variants = re.search(r'变体数(\d+)', combined)
    if variants: data['variant_count'] = variants.group(1)

    # 上架时间：格式 "2022-03-16(1,548天)" 或 "2022-03-16 (1,548天)"
    launch = re.search(r'(\d{4}-\d{2}-\d{2})\s*\(([\d,]+)\s*天\)', combined)
    if launch:
        data['launch_date'] = launch.group(1)
        data['days_online'] = launch.group(2).replace(',', '').replace(',', '')

    # 毛利率：支持 N/A 或 12.5% 格式
    profit = re.search(r'毛利率[^:\d]*([\d.]+%|[N/n]\s*/\s*[A/a])', combined)
    if profit:
        data['gross_margin'] = profit.group(1).replace(' ', '')

    # ── 主面板字段 ──
    asin_m = re.search(r'ASIN[:：]*(B[A-Z0-9]{9,10})', combined)
    if asin_m: data['asin'] = asin_m.group(1)


    # 品牌：Amazon Basics
    brand = re.search(r'品牌[:：]*\s*([A-Za-z][^\s：:]{2,30}(?:\s+[A-Za-z][^\s：:]{2,20})?)(?=\s*卖家|$)', combined)
    if brand:
        b = brand.group(1).strip()
        b = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', b)
        data['brand'] = b

    # 卖家
    seller = re.search(r'卖家[:：]*\s*([A-Za-z][^\s：:]{2,30})', combined)
    if seller: data['seller'] = seller.group(1).strip()

    # 配送类型：AMZ / FBA（用负向前瞻排除中文"卖家"）
    fulfill = re.search(r'配送[:：]*\s*([A-Z]{2,6}(?![A-Za-z\u4e00-\u9fff]))', combined)
    if fulfill: data['fulfillment'] = fulfill.group(1).strip()


    # 卖家数
    sc = re.search(r'卖家[:：]*\s*(\d+)', combined)
    if sc: data['seller_count'] = sc.group(1)

    # 大类 BSR
    bsr_main = re.search(r'#(\d+)\s+in\s+([^#\n]{3,40})', combined)
    if bsr_main:
        data['bsr_rank'] = bsr_main.group(1)
        data['bsr_category'] = bsr_main.group(2).strip()

    # 小类 BSR：第二个 # 后面到 "近30天销量" 或下一个 # 之前
    idx1 = combined.find('#')
    if idx1 >= 0:
        rest = combined[idx1 + 1:]
        idx2 = rest.find('#')
        if idx2 >= 0:
            segment = rest[idx2:]
            bsr_sub = re.search(r'#(\d+)\s+in\s+(.{3,40}?)(?=\s*#|\s*近30天)', segment)
            if bsr_sub:
                data['bsr_sub_rank'] = bsr_sub.group(1)
                data['bsr_sub_category'] = bsr_sub.group(2).strip()


    # 评分 + 评分数（合并提取）
    rating_m = re.search(r'评分[^\d]*([\d.]+)\s*\(?([\d,]+)\)?', combined)
    if rating_m:
        data['rating'] = rating_m.group(1)
        data['review_count'] = rating_m.group(2).replace(',', '')

    price_m = re.search(r'价格[^\d]*\$([\d.]+)', combined)
    if price_m: data['price'] = price_m.group(1)
    ship = re.search(r'配送时长[^\d]*(\d+)天', combined)
    if ship: data['ship_days'] = ship.group(1)
    prime = re.search(r'Prime配送时长[^\d]*(\d+)天', combined)
    if prime: data['prime_ship_days'] = prime.group(1)

    # 商品重量
    weight = re.search(r'商品重量[:：]*\s*([\d.]+)\s*ounces?\s*\(?([\d.]+)\s*g\)?', combined)
    if weight:
        data['weight_oz'] = weight.group(1)
        data['weight_g'] = weight.group(2)

    # 商品尺寸
    dims = re.search(r'商品尺寸[:：]*\s*([\d.]+)\s*x\s*([\d.]+)\s*x\s*([\d.]+)\s*inches?', combined)
    if dims:
        data['dim_l'], data['dim_w'], data['dim_h'] = dims.group(1), dims.group(2), dims.group(3)


    # 关键词统计
    for label, key in [('全部流量词', 'total_keywords'), ('自然搜索词', 'natural_keywords'),
                       ('广告流量词', 'ad_keywords'), ('搜索推荐词', 'suggest_keywords')]:
        m = re.search(rf'{re.escape(label)}[^\d]*(\d+)', combined)
        if m: data[key] = m.group(1)


    # 库存
    inv_stock = re.search(r'剩余库存(\d+)', inv_text)
    inv_price = re.search(r'剩余库存\d+\$([\d.]+)', inv_text)
    if inv_stock: data['inv_stock'] = inv_stock.group(1)
    if inv_price: data['inv_price'] = inv_price.group(1)

    # 流量词 Top 列表（Element UI 表格解析）
    # 插件使用 div.el-table__row 结构，每行 6 个 td.cell，innerHTML 含嵌套 div
    try:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', traffic_text, re.DOTALL)
        cell_texts = []
        for td in tds:
            # 剥除所有 HTML 标签；把 >< 替换为换行符，这样不同嵌套层级的文本不会串线
            raw = re.sub(r'<[^>]*>', '', td)
            raw = re.sub(r'\{\{[^}]+\}\}', '', raw)
            lines = [l.strip() for l in raw.split('\n') if l.strip()]
            cell_texts.append('\n'.join(lines))

        keywords = []
        for i in range(0, len(cell_texts), 6):
            if i + 5 >= len(cell_texts):
                break
            # keyword：去掉末尾的中文翻译，只保留纯英文词
            kw_raw = cell_texts[i+1].strip()
            kw = re.sub(r'[\u4e00-\udd2f\uf900-\ufaaf\u3400-\u4dbf\U00020000-\U0002a6df\U0002a700-\U0002ebaf\U00030000-\U000323af]', '', kw_raw).strip()

            # click_pct：只取第一行（百分比），去掉第二行的类型垃圾
            # click_pct：cell[i+2] 的第一行
            click_raw = cell_texts[i+2].strip()
            click_lines = [l.strip() for l in click_raw.split('\n') if l.strip()]
            click_pct = click_lines[0] if click_lines else ''

            # kw_type：cell[i+3]（自然搜索词/AC推荐词等）
            kw_type = cell_texts[i+3].strip() if len(cell_texts) > i+3 else ''

            # organic_rank：cell[i+4] 取开头的数字
            organic_raw = cell_texts[i+4].strip()
            organic_m = re.search(r'^(\d+)', organic_raw)
            organic_rank = organic_m.group(1) if organic_m else ''
            if kw:
                keywords.append({
                    'keyword': kw,
                    'traffic_pct': click_pct,
                    'type': kw_type,
                    'organic_rank': organic_rank
                })
        if keywords:
            data['traffic_keywords_top'] = keywords[:4]  # 只取前4个主要流量词
    except Exception as e:
        pass  # 流量词解析失败不影响主流程

    print(f"  [插件] 提取到 {len(data)} 个字段" + (f", 流量词 {len(keywords)} 条" if keywords else ""))
    return data


def extract_asin_data(browser: CDPBrowser):
    """从当前详情页提取完整的商品数据（修复版）"""
    print("  📊 提取商品数据...")

    js_bundle = r"""
(() => {
    const $ = (sel) => document.querySelector(sel);
    const body = document.body.innerText || '';

    const titleEl = document.querySelector('#productTitle');
    const title = (titleEl ? titleEl.textContent.trim() : (document.querySelector('h1') || {textContent: ''}).textContent.trim()).substring(0, 200);
    // title 备选：从 meta og:title 或 JSON-LD
    if (!title) {
        const ogT = document.querySelector('meta[property="og:title"]');
        if (ogT) title = ogT.content.substring(0, 200);
    }
    if (!title) {
        const ld = document.querySelector('script[type="application/ld+json"]');
        if (ld) { try { const d = JSON.parse(ld.textContent); if (d && d.name) title = d.name.substring(0, 200); } catch(e){} }
    }

    const priceWholeEl = document.querySelector('#corePrice_feature_div .a-price-whole');
    const priceOffscreenEl = document.querySelector('#corePrice_feature_div .a-offscreen');
    const corePrice = priceOffscreenEl ? priceOffscreenEl.textContent.trim() : (priceWholeEl ? '$' + priceWholeEl.textContent.trim() : '');
    let price = corePrice || (document.querySelector('.a-price .a-offscreen') || {textContent: ''}).textContent.trim();
    // price 备选：从页面 body 文本匹配 $xx.xx 或 $xx
    if (!price) { const pm = body.match(/\$\d+\.\d{2}/); if (pm) price = pm[0]; }
    if (!price) { const pm2 = body.match(/\$\d+(?:\.\d+)?/); if (pm2) price = pm2[0]; }

    const ratingEl = document.querySelector('.a-icon-alt');
    const ratingM = (ratingEl ? ratingEl.textContent.trim() : '').match(/([\d.]+)/);
    let rating = ratingM ? ratingM[1] : '';
    // rating 备选：从 body 文本匹配 "X.X out of 5 stars"
    if (!rating) { const rm = body.match(/([\d.]+)\s*out\s*of\s*5\s*stars?/i); if (rm) rating = rm[1]; }

    const reviewEl = document.querySelector('#acrCustomerReviewText');
    const reviewM = (reviewEl ? reviewEl.textContent.trim() : '').match(/([\d,]+)/);
    const review_count = reviewM ? reviewM[1].replace(/,/g, '') : '';

    // ── 品牌（多来源备选，优先级从高到低）──
    let brand = '';
    const brandSources = [
      // #1: "Visit the XXX Store" → 提取XXX（Amazon第三方卖家常用格式）
      () => { const m = body.match(/Visit the ([A-Z][A-Za-z\s&'\-]{2,40}) Store/i); return m ? m[1].trim() : ''; },
      // #2: bylineInfo 元素
      () => { const el = document.querySelector('#bylineInfo'); return el ? el.textContent.trim() : ''; },
      // #3: detailBulletsWrapper → Brand:
      () => { const el = document.querySelector('#detailBulletsWrapper_feature_div'); if (!el) return ''; const m = el.textContent.match(/Brand:\s*([^\n]+)/i); return m ? m[1].trim() : ''; },
      // #4: tech spec table
      () => { const el = document.querySelector('#productDetails_techSpec_section_1'); if (!el) return ''; const m = el.textContent.match(/Brand\s*([^\n]+)/i); return m ? m[1].trim() : ''; },
      // #5: JSON-LD
      () => { const el = document.querySelector('script[type="application/ld+json"]'); if (!el) return ''; try { const d = JSON.parse(el.textContent); if (d && d.brand) return typeof d.brand === 'string' ? d.brand : (d.brand.name || ''); if (d && d['@graph']) { const p = d['@graph'].find(x => x['@type'] === 'Product'); return (p && p.brand) ? (typeof p.brand === 'string' ? p.brand : (p.brand.name || '')) : ''; } } catch(e){} return ''; },
      // #6: page body "Brand: XXX"
      () => { const m = body.match(/Brand:\s*([^\n]{2,50})/i); return m ? m[1].trim() : ''; },
      // #7: 从标题提取首个单词（Garnier Micellar → Garnier）
      () => { const m = title.match(/^([A-Z][A-Za-z\s&'\-]{2,30})\s/); return m ? m[1].trim() : ''; },
    ];
    for (const fn of brandSources) { brand = fn(); if (brand && brand.length > 1) break; }
    brand = brand.replace(/^Visit the /, '').replace(/ Store$/, '').replace(/^访问/, '').replace(/品牌旗舰店$/, '').replace(/Brand:\s*/i, '').trim();
    if (brand.length > 60) brand = brand.substring(0, 60);

    const soldByEl = document.querySelector('#merchantInfoFeature_feature_div .a-link-normal') || document.querySelector('#merchant-info');
    const soldBy = soldByEl ? soldByEl.textContent.trim() : '';

    // ── 产品图片（多个备选选择器 + 高分辨率替换）──
    let mainImg = '';
    const imgSelectors = [
        '#landingImage',
        '#imgTagWrapperId img',
        '#main-image',
        '#imgBlkFront',
        '#mainImage',
        '#ebay-image img',
        '.a-dynamic-image',
        '#altImages img',
        '#richThumbnails img',
    ];
    for (const sel of imgSelectors) {
        const el = document.querySelector(sel);
        if (el) {
            mainImg = el.getAttribute('src') || el.getAttribute('data-old-hires') || '';
            if (mainImg) break;
        }
    }
    // 尝试从 data-a-dynamic-image 提取最高分辨率图片
    if (!mainImg) {
        const dynEl = document.querySelector('[data-a-dynamic-image]');
        if (dynEl) {
            try {
                const dynData = JSON.parse(dynEl.getAttribute('data-a-dynamic-image') || '{}');
                const urls = Object.keys(dynData);
                if (urls.length > 0) {
                    // 取分辨率最高的（最后一张通常是主图）
                    mainImg = urls[urls.length - 1];
                }
            } catch(e) {}
        }
    }
    // 升级到高分辨率
    if (mainImg) {
        mainImg = mainImg.replace(/\._AC_\w+_\.jpg/, '._AC_SL1500_.jpg');
        mainImg = mainImg.replace(/\._SY\d+_\.jpg/, '._AC_SL1500_.jpg');
        mainImg = mainImg.replace(/\._SX\d+_\.jpg/, '._AC_SL1500_.jpg');
        // 去掉尺寸后缀参数
        mainImg = mainImg.replace(/\?.*$/, '');
    }
    // main_image 备选：从 meta og:image
    if (!mainImg) {
        const ogI = document.querySelector('meta[property="og:image"]');
        if (ogI && ogI.content) mainImg = ogI.content;
    }
    // main_image 备选：从 JSON-LD product image
    if (!mainImg) {
        const ldI = document.querySelector('script[type="application/ld+json"]');
        if (ldI) {
            try {
                const d = JSON.parse(ldI.textContent);
                if (d && d.image) mainImg = Array.isArray(d.image) ? d.image[0] : d.image;
                else if (d && d["@graph"]) { const g = d["@graph"].find(x => x['@type'] === 'Product'); if (g && g.image) mainImg = Array.isArray(g.image) ? g.image[0] : g.image; }
            } catch(e){}
        }
    }

    // ── BSR ──
    let bsr = '', bsrSubCategory = '', bsrSubRank = '', bsrAllSubRanks = [];
    const bsrSection = body.match(/Best Sellers Rank[\s\S]{0,500}/);
    if (bsrSection) {
        bsr = bsrSection[0].substring(0, 300);
        const topM = bsr.match(/#([\d,]+)\s+in\s+([^#\n\r]+)/);
        if (topM) { bsrSubRank = topM[1].replace(/,/g, ''); bsrSubCategory = topM[2].trim().substring(0, 100); }
        // 提取所有 #数字（第一个是大类，其余是小类/子分类排名）
        const allMatches = bsr.matchAll(/#([\d,]+)\s+in\s+([^\n\r]+)/g);
        let idx = 0;
        for (const m of allMatches) {
            if (idx === 0) { idx++; continue; } // 跳过第一个（已作为大类）
            bsrAllSubRanks.push(m[1].replace(/,/g, ''));
            idx++;
            if (bsrAllSubRanks.length >= 5) break; // 最多取5个
        }
    }

    // ── Badges (多个来源) ──
    const badges = [];
    const lowerBody = body.toLowerCase();
    if (lowerBody.includes("bestseller") || document.querySelector('[class*="bestseller"], #detailBulletsWrapper_feature_div [class*="bestseller"]')) badges.push('BS');
    if (lowerBody.includes("amazon's choice") || document.querySelector('[class*="choices"], #acBadge')) badges.push('AC');
    if (lowerBody.includes("new release") || document.querySelector('[class*="new-releases"]')) badges.push('NR');
    if (document.querySelector('#aplusBrandLogo, #aplus_feature_div iframe, #aplus3pFeatureText')) badges.push('A+');
    const badgeEl = document.querySelector('.a-badge-container');
    if (badgeEl) {
        const bt = badgeEl.innerText || '';
        if (bt.includes('Bestseller')) badges.push('BS');
        if (bt.includes('New')) badges.push('NR');
    }
    // A+ badge
    if (badges.indexOf('A+') === -1 && document.querySelector('#aplus_feature_div')) badges.push('A+');

    // ── Deal 活动 ──
    let deal_activity = '无';
    const dealEl = document.querySelector('#dealBadge_feature_div, #dealsLabel_feature_div, .deal-sash, [class*="deal-badge"]');
    if (dealEl) {
        const dt = dealEl.innerText || '';
        if (dt.includes('Lightning Deal')) deal_activity = 'Lightning Deal';
        else if (dt.includes('Deal of the Day') || dt.includes('DOTD')) deal_activity = 'Deal of the Day';
        else if (dt.includes('Best Deal')) deal_activity = 'Best Deal';
        else if (dt.includes('Deal')) deal_activity = 'Deal';
        else deal_activity = dt.trim() || 'Deal';
    }
    // 从 body 文本二次确认
    if (deal_activity === '无') {
        if (lowerBody.includes('lightning deal')) deal_activity = 'Lightning Deal';
        else if (lowerBody.includes('deal of the day')) deal_activity = 'Deal of the Day';
        else if (lowerBody.includes('best deal')) deal_activity = 'Best Deal';
    }

    // ── 优惠券 ──
    let coupon = '无';
    const couponEl = document.querySelector('#couponPopoverFeature, [data-coupon], .coupon-badge, #sidesheet看到她 .coupon');
    if (couponEl) {
        const ct = couponEl.innerText || '';
        const pctM = ct.match(/(\d+)%/);
        const amtM = ct.match(/\$(\d+\.?\d*)/);
        if (pctM) coupon = pctM[1] + '% off';
        else if (amtM) coupon = '$' + amtM[1] + ' off';
        else if (ct.trim()) coupon = ct.trim();
        else coupon = '有优惠券';
    }
    if (coupon === '无' && lowerBody.includes('coupon')) {
        const cM = body.match(/(\d+)%\s*off.*coupon|save\s*\$(\d+\.?\d*)/i);
        if (cM) coupon = cM[1] ? cM[1] + '% off' : '$' + cM[2] + ' off';
    }

    // ── Prime 专享折扣 ──
    let prime_discount = '未开启';
    const primeEl = document.querySelector('#primeExclusiveExtraContent, #primeBenefits, .prime-benefits, #prime-ingress-features');
    if (primeEl) {
        const pt = primeEl.innerText || '';
        const discM = pt.match(/(\d+)%/);
        if (discM) prime_discount = discM[1] + '%';
        else if (pt.includes('Prime')) prime_discount = pt.trim().substring(0, 30);
    }
    if (prime_discount === '未开启') {
        if (lowerBody.includes('prime member') && lowerBody.includes('%')) {
            const pdM = body.match(/prime.*?(\d+)%/i);
            if (pdM) prime_discount = pdM[1] + '%';
        }
    }

    // ── 评分分布（直方图） ──
    const rating_distribution = {};
    const histBars = document.querySelectorAll('#histogramTable .a-histogram-bar');
    if (histBars.length > 0) {
        histBars.forEach(bar => {
            const barEl = bar.querySelector('.a-bar-container');
            const countEl = bar.querySelector('.a-histogram-count');
            const barAria = barEl ? barEl.getAttribute('aria-label') || '' : '';
            const countText = countEl ? countEl.textContent.trim() : '';
            const starsM = barAria.match(/(\d+)星/);
            const pctM = barAria.match(/(\d+)%/);
            if (starsM) {
                const star = starsM[1] + 'star';
                const pct = pctM ? pctM[1] + '%' : '';
                const count = countText.replace(/[,，]/g, '').match(/(\d+)/);
                rating_distribution[star] = { pct: pct, count: count ? count[1] : countText };
            }
        });
    }

    // ── 五点描述（feature bullets）──
    const features = [];
    const featureSources = [
        () => Array.from(document.querySelectorAll('#feature-bullets li, #fb-inherited-content li, #important-information li')).map(li => li.textContent.trim()).filter(t => t && t.length > 10).slice(0, 5),
        () => Array.from(document.querySelectorAll('.a-unordered-list li')).filter(li => li.textContent.trim().length > 10 && !li.closest('[id*="detailBullets"]') && !li.closest('[id*="SalesRank"]')).map(li => li.textContent.trim()).slice(0, 5),
    ];
    for (const fn of featureSources) { const f = fn(); if (f.length >= 3) { features.push(...f); break; } }
    const uniqueFeatures = features.slice(0, 5);

    // ── 上架时间（Date first available）──
    let launchDate = '';
    const dateSources = [
        () => { const el = document.querySelector('#detailBulletsWrapper_feature_div, #productDetails_detailBullets_sections1'); if (!el) return ''; const m = el.textContent.match(/Date first available[^\n]*?(\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2})/i); return m ? m[1].trim() : ''; },
        () => { const els = document.querySelectorAll('#prodDetails td, #detailBullets_feature_div li, .detail-bullet'); for (const el of els) { const m = el.textContent.match(/Date first available[^\n]*?(\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2})/i); if (m) return m[1].trim(); } return ''; },
        () => { const m = body.match(/Date first available[^\n]{0,100}/i); return m ? m[0].replace(/Date first available[^\d]*/i, '').trim() : ''; },
    ];
    for (const fn of dateSources) { launchDate = fn(); if (launchDate) break; }

    const result = {
        title, price, rating, review_count, brand, soldBy,
        features: uniqueFeatures,
        launch_date: launchDate,
        main_image: mainImg,
        bsr: bsr, bsr_subcategory: bsrSubCategory, bsr_subrank: bsrSubRank, bsr_all_subranks: bsrAllSubRanks,
        badges: badges,
        deal_activity: deal_activity,
        coupon: coupon,
        prime_discount: prime_discount,
        rating_distribution: rating_distribution,
        snapshot_time: new Date().toISOString(),
    };
    return JSON.stringify(result);
})()
"""
    try:
        raw = browser.eval(js_bundle)
        if raw:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data
    except Exception as e:
        print("  JS提取错误: " + str(e))
    return {}


def extract_bsr_direct(browser):
    """直接从页面文本提 BSR（备用）"""
    js = r"""
(() => {
    const text = document.body.innerText || '';
    const m = text.match(/Best Sellers Rank[\s\S]{0,200}/);
    return m ? m[0].substring(0,300) : '';
})()
"""
    try:
        r = browser.eval(js)
        return r if r else ""
    except:
        return ""


def print_card(data):
    print("  商品标题: " + str(data.get("title","(无)")[:80]))
    print("  当前价格: " + str(data.get("price","")))
    print("  评分: " + str(data.get("rating","")))
    print("  评论数: " + str(data.get("review_count","")))
    print("  品牌: " + str(data.get("brand","")))
    print("  BSR: " + str(data.get("bsr_subrank","")) + " (" + str(data.get("bsr_subcategory","")[:40]) + ")")
    badge = data.get("badge","")
    if badge:
        print("  标签: " + badge)


def _fetch_related_asin_data(browser, related_list):
    """批量抓取关联ASIN实时数据（复用已有浏览器）"""
    results = []
    for rel in related_list:
        asin = rel.get("asin","")
        source = rel.get("source","")
        if not asin:
            continue
        print(f"\n  [关联] 抓取 {asin} ({source}) ...")
        try:
            amazon = AmazonBrowser(browser)
            amazon.search_for_asin(asin)
            browser.scroll_down(times=1, min_pause=0.3, max_pause=0.8)
            time.sleep(0.5)
            data = extract_asin_data(browser)
            results.append({
                "asin": asin, "source": source,
                "title": data.get("title",""),
                "price": data.get("price",""),
                "rating": data.get("rating",""),
                "reviews": data.get("review_count",""),
                "bsr": data.get("bsr_subrank",""),
                "brand": data.get("brand",""),
            })
        except Exception as e:
            print(f"  ⚠️ 抓取关联ASIN {asin} 失败: {e}")
            results.append({
                "asin": asin, "source": source,
                "title": "", "price": "", "rating": "", "reviews": "",
                "bsr": "", "brand": "",
            })
    return results


# ─── 主函数 ───

def check_asin(asin, search_keyword=None, use_sprite=True, mode="full"):
    """
    mode:
      "full"       - 完整流程（亚马逊 + 卖家精灵 + 快照）
      "amazon"     - 只查亚马逊（不调用卖家精灵）
      "discover"   - 只做竞品关联发现（通过卖家精灵查竞品），输出 JSON 到 stdout
    """
    print("\n" + "="*70)
    print("ASIN 监控检查")
    print("  ASIN: %s" % asin)
    print("  模式: %s" % mode)
    print("  时间: %s" % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("="*70)

    # ── discover 模式：只做竞品发现 ──
    if mode == "discover":
        import re as _re
        browser = CDPBrowser()
        browser.connect_tab(tab_url_filter="about:blank")
        if not browser.tab:
            browser.cmd("Target.createTarget", {"url": "about:blank"})
            time.sleep(0.5)
            browser.connect_tab(tab_url_filter="about:blank")
        try:
            sprite = SpriteBrowser(browser)
            result = sprite.lookup_competitor(asin)
            page_text = result.get("text", "") if isinstance(result, dict) else ""
            found = _re.findall(r'B[A-Z0-9]{9,10}', page_text)
            related = []
            seen = set()
            for a in found:
                a = a.strip()
                if a != asin and a not in seen and len(a) == 10 and a.startswith('B0'):
                    seen.add(a)
                    related.append({"asin": a, "source": "competitor"})
            related = related[:5]
            print("\n  [竞品发现] 主ASIN %s → %d 个关联ASIN: %s"
                  % (asin, len(related), [r["asin"] for r in related]))
            # 输出 JSON 到 stdout（供 run_monitor.py 捕获）
            print(json.dumps(related, ensure_ascii=False))
        finally:
            try:
                browser.close()
            except:
                pass
        return

    # ── amazon / full 模式 ──
    # 【强制保障】: 第一步就创建ASIN文件夹，方便调试，即使后面失败也有文件夹
    from browser.snapshot_storage import _asin_dir
    _asin_dir(asin)
    
    browser = CDPBrowser()
    browser.connect_tab(tab_url_filter="about:blank")
    if not browser.tab:
        browser.cmd("Target.createTarget", {"url": "about:blank"})
        time.sleep(0.5)
        browser.connect_tab(tab_url_filter="about:blank")

    amazon_data = {}
    sprite_data = {}

    # ─── Phase A: 亚马逊 ───
    print("\n" + "="*50)
    print("亚马逊前台浏览")
    print("="*50)

    try:
        amazon = AmazonBrowser(browser)
        amazon.browse_homepage()
        if random.random() < 0.15:
            amazon.browse_category()
        amazon.search_for_asin(asin, search_keyword)
        browser.scroll_down(times=1, min_pause=0.3, max_pause=0.8)

        # ── 【关键防呆】校验当前页面真的是目标 ASIN，否则强制纠正 ──
        # 根因：search_for_asin 点击搜索结果后不验证跳转，若标签页复用了上一个
        # ASIN 的详情页，会把上一个商品的 title/image/插件数据错配给当前 ASIN。
        def _verify_and_fix_asin(target_asin, max_retry=2):
            for attempt in range(max_retry + 1):
                cur = browser.eval("""(() => {
                    var m = (location.href.match(/\\/dp\\/([A-Z0-9]{10})/) || [])[1];
                    if (m) return m;
                    var c = document.querySelector('link[rel="canonical"]');
                    if (c) { var cm = (c.href.match(/\\/dp\\/([A-Z0-9]{10})/) || [])[1]; if (cm) return cm; }
                    var asinInput = document.querySelector('#ASIN, input[name="ASIN"]');
                    if (asinInput && asinInput.value) return asinInput.value;
                    return '';
                })()""") or ''
                cur = str(cur).strip().upper()
                if cur == target_asin.upper():
                    if attempt > 0:
                        print(f"  ✅ ASIN 已纠正到 {target_asin}")
                    return True
                print(f"  ⚠️ 页面 ASIN 不符：当前={cur or '未知'} 目标={target_asin}（第 {attempt+1} 次），强制跳转")
                browser.navigate(f"https://www.amazon.com/dp/{target_asin}", wait_min=3, wait_max=5)
                time.sleep(2)
            # 最终校验
            final = browser.eval("(() => (location.href.match(/\\/dp\\/([A-Z0-9]{10})/) || [])[1] || '')()") or ''
            ok = str(final).strip().upper() == target_asin.upper()
            if not ok:
                print(f"  ❌ ASIN 校验失败，最终页面={final}，将放弃本次抓取以避免错配")
            return ok

        _asin_ok = _verify_and_fix_asin(asin)
        if not _asin_ok:
            # 校验失败：不提取，直接抛错让上层走 fallback（保留上次快照），避免错配脏数据
            raise RuntimeError(f"ASIN 校验失败，页面非 {asin}，跳过提取避免数据错配")

        # ── 合并等待：页面就绪 + 插件就绪（amazon 模式也等插件，超时 90s） ──
        page_ready = False
        plugin_ready = False
        deadline = time.time() + 90
        while time.time() < deadline:
            elapsed = time.time() - (deadline - 90)

            # 检查页面元素（每轮都检查，不等待）
            if not page_ready:
                page_status = browser.eval("""(() => {
                    var titleEl = document.querySelector('#productTitle');
                    var titleOk = titleEl && titleEl.textContent.trim().length > 0;
                    var imgEl = document.querySelector('#landingImage');
                    var imgOk = imgEl && imgEl.complete && imgEl.naturalWidth > 0;
                    return { titleOk: titleOk, imgOk: imgOk };
                })()""")
                if page_status and page_status.get('titleOk') and page_status.get('imgOk'):
                    page_ready = True
                    print(f"  页面加载完成（耗时 {elapsed:.1f}s）")

            # 检查插件就绪（amazon/full 模式都要等插件）
            if not plugin_ready and mode in ("full", "amazon"):
                try:
                    candidate = extract_sprite_plugin_data(browser)
                    if candidate:
                        has_data = bool(
                            candidate.get('plugin_version') or
                            candidate.get('lqs') or
                            candidate.get('variant_count') or
                            (candidate.get('main_text') or '').strip()
                        )
                        if has_data:
                            plugin_ready = True
                            print(f"  插件就绪（耗时 {elapsed:.1f}s）")
                except Exception:
                    pass

            # 页面 + 插件都就绪才能退出；amazon 模式也要等插件
            if page_ready and plugin_ready:
                break

            # 每 5 秒打印一次进度
            if int(elapsed) % 5 == 0 and int(elapsed) > 0:
                print(f"  等待中... {elapsed:.0f}s (页面={'✓' if page_ready else '⏳'}, 插件={'✓' if plugin_ready else '⏳'})")

            time.sleep(1)
        else:
            print("  等待超时（90s），继续执行（页面={'✓' if page_ready else '✗'}, 插件={'✓' if plugin_ready else '✗'}）")

        # ── 统一提取：等所有条件都就绪后，一次性提取亚马逊数据 + 插件 DOM ──
        amazon_data = extract_asin_data(browser)
        if not amazon_data.get("bsr"):
            bsr = extract_bsr_direct(browser)
            if bsr:
                amazon_data["bsr"] = bsr
        print_card(amazon_data)

        if mode in ("full", "amazon"):
            if plugin_ready:
                plugin_data = extract_sprite_plugin_data(browser)
                if plugin_data:
                    # 【防呆】插件数据是异步刷新的，可能还停留在上一个 ASIN。
                    # 如果插件返回的 asin 与目标不符，丢弃插件数据，避免错配。
                    _plugin_asin = str(plugin_data.get('asin', '') or '').strip().upper()
                    if _plugin_asin and _plugin_asin != asin.upper():
                        print(f"  ⚠️ 插件数据 ASIN={_plugin_asin} 与目标 {asin} 不符，丢弃插件数据避免错配")
                    else:
                        for k, v in plugin_data.items():
                            amazon_data['sprite_' + k] = v
                        print("  插件数据提取完成")
            else:
                print("  插件未就绪，跳过插件数据提取")

        print("  亚马逊检查完成")
    except Exception as e:
        print("  亚马逊检查失败: %s" % e)

    # ─── Phase B: 卖家精灵（可选）───
    related_asins_meta = []
    sprite_data = None  # 【修复】必须提前定义，否则非full模式下未定义异常
    if use_sprite and mode == "full":
        print("\n" + "="*50)
        print("卖家精灵数据查询")
        print("="*50)
        try:
            sprite = SpriteBrowser(browser)
            sprite_data = sprite.full_asin_check(asin)
            print("  卖家精灵查询完成")
        except Exception as e:
            print("  卖家精灵失败: %s" % e)
            sprite_data = None

        # ── 关联 ASIN 发现 → 写入 asin_related_asins.json（统一由 run_monitor.py 处理，这里不再写入 _meta.json）──
        # 注：关联 ASIN 发现逻辑已移至 run_monitor.py + discover_related.py，
        # asin_monitor.py 此处只负责主 ASIN 的监控，不处理关联 ASIN 发现

    # ─── Phase C: 对比保存 ───
    print("\n" + "="*50)
    print("变化对比")
    print("="*50)

    # ── 提前导入模块，避免作用域错误
    from browser.snapshot_storage import load_latest_asin, save_asin_snapshot

    previous = load_latest_asin(asin)
    changes = {"has_changes": False, "changes": []}
    if previous:
        old_data = previous.get("data", {})
        report = diff_asin(old_data, amazon_data)
        changes = report
        if report["has_changes"]:
            print("  检测到变化!")
            for c in report["changes"]:
                print("    * %s" % c)
        else:
            print("  价格/评分/评论 均无变化")
    else:
        print("  首次记录")

    # ── 数据有效性检查：只要能提取到ASIN页面就保存，方便调试 ──
    has_title = bool(amazon_data.get('title', '').strip())
    has_price = bool(amazon_data.get('price', '').strip())
    has_image = bool(amazon_data.get('main_image', '').strip())
    if not (has_title or has_price or has_image):
        print("  ⚠️ 页面数据大部分为空，仍保存快照供调试")
    # 不再跳过，总是保存快照 → 即使空也能在processed生成文件夹，方便排查问题
    
    snapshot_data = {
        **amazon_data,
        "_sprite_text": sprite_data.get("competitor", {}).get("text", "")[:2000] if sprite_data else "",
        "_timestamp": datetime.now().isoformat(),
    }
    # ── 保留 Phase A3 写入的关键词分类标签（_asin_type / _source_keyword）─
    try:
        _prev_latest = load_latest_asin(asin)
        if _prev_latest:
            _prev_data = _prev_latest.get("data", _prev_latest) if isinstance(_prev_latest, dict) else {}
            for _k in ("_asin_type", "_source_keyword"):
                if _prev_data.get(_k) and not snapshot_data.get(_k):
                    snapshot_data[_k] = _prev_data[_k]
    except Exception:
        pass
    save_asin_snapshot(asin, snapshot_data)

    browser.close()

    # ─── 最终摘要 ───
    print("\n" + "="*50)
    print("ASIN: %s" % asin)
    print("价格: %s" % amazon_data.get("price",""))
    print("评分: %s %s (%s reviews)" % (
        amazon_data.get("rating",""),
        amazon_data.get("badge",""),
        amazon_data.get("review_count","")))
    print("排名: %s  (%s)" % (
        amazon_data.get("bsr_subrank",""),
        amazon_data.get("bsr_subcategory","")[:40]))
    if changes.get("has_changes"):
        print("变化: %s" % ", ".join(changes["changes"][:5]))
    print("="*50)


def main():
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("asin", nargs="?")
        parser.add_argument("--amazon", action="store_true")
        parser.add_argument("--discover", action="store_true")
        parser.add_argument("--status", action="store_true")
        parser.add_argument("--keyword", action="store_true")
        args = parser.parse_args()
    
        if not args.asin:
            print("用法: python asin_monitor.py ASIN [--amazon] [--discover] [--status]")
            sys.exit(1)
    
        mode = "full"
        if args.amazon:
            mode = "amazon"
        elif args.discover:
            mode = "discover"
    
        if args.status:
            from browser.snapshot_storage import load_latest_asin
            prev = load_latest_asin(args.asin)
            if prev:
                print("已有快照，时间: %s" % prev.get("_timestamp","未知"))
                print("价格: %s" % prev.get("data",{}).get("price",""))
            else:
                print("无快照记录")
            sys.exit(0)
    
        if args.keyword:
            import json as _json
            cfg_path = os.path.join(os.path.dirname(BASE), "data", "user_config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as _f:
                    _cfg = _json.load(_f)
            else:
                _cfg = {"keywords": []}
            _keywords = [k.get("main","") for k in _cfg.get("keywords",[]) if k.get("main","")]
            if not _keywords:
                print("no keywords in user_config.json")
                sys.exit(1)
            from browser.fetch_keyword_asins import fetch_keyword_asins
            _results = fetch_keyword_asins(_keywords)
            print("keyword asins results:", len(_results))
            sys.exit(0)
    
        check_asin(args.asin.strip(), use_sprite=True, mode=mode)
if __name__ == "__main__":
    main()
