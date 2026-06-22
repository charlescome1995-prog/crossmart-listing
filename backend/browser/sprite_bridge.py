#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
卖家精灵插件交互层
控制Edge标签页，在卖家精灵网站内查数据
"""
import sys, os, json, random, time, re
sys.stdout.reconfigure(encoding='utf-8')
sys.dont_write_bytecode = True
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from browser.cdp_bridge import CDPBrowser, SCREENSHOT_DIR
from browser.human_timer import read_pause, human_pause, think_pause

SPRITE_BASE = "https://www.sellersprite.com"
SPRITE_ROUTES = {
    "competitor": "/v3/competitor-lookup",
    "keyword_research": "/v2/keyword-research",
    "keyword_miner": "/v3/keyword-miner",
    "ads_insights": "/v3/ads-insights",
    "product_search": "/v3/product-research",
    "reversing": "/v3/reversing",
}


class SpriteBrowser:
    """卖家精灵浏览器封装"""

    def __init__(self, browser: CDPBrowser):
        self.b = browser

    def goto(self, page_key):
        path = SPRITE_ROUTES.get(page_key)
        if not path:
            raise ValueError(f"未知页面: {page_key}")
        self.b.navigate(f"{SPRITE_BASE}{path}", wait_min=2, wait_max=5)
        read_pause()
        return self

    def search_asin_input(self, asin):
        js = f"""
        (() => {{
            const inputs = document.querySelectorAll('input[type="text"], input:not([type="hidden"])');
            let target = null;
            for (const inp of inputs) {{
                if (inp.placeholder && inp.placeholder.toLowerCase().includes('asin')) {{ target = inp; break; }}
            }}
            if (!target) {{
                for (const inp of inputs) {{
                    const s = window.getComputedStyle(inp);
                    if (s.display !== 'none' && s.visibility !== 'hidden') {{ target = inp; break; }}
                }}
            }}
            if (!target) return false;
            target.focus();
            target.value = '';
            const text = {json.dumps(asin)};
            for (let i = 0; i < text.length; i++) {{
                target.value += text[i];
                target.dispatchEvent(new Event('input', {{bubbles: true}}));
            }}
            return true;
        }})()
        """
        return self.b.eval(js)

    def click_search_btn(self):
        js = """
        (() => {
            const btns = document.querySelectorAll('button, .el-button, [class*="btn"], [role="button"]');
            for (const btn of btns) {
                const t = (btn.textContent || '').trim();
                if (t.includes('查询') || t.includes('搜索') || t.includes('Search') ||
                    t.includes('获取') || t.includes('Analyze')) {
                    btn.click(); return true;
                }
            }
            return false;
        })()
        """
        return self.b.eval(js)

    def get_page_text(self):
        js = """
        (() => {
            const cells = document.querySelectorAll('td, .el-table__cell, [class*="cell"]');
            return Array.from(cells).slice(0, 200).map(c => (c.textContent || '').trim()).filter(Boolean).join(' | ');
        })()
        """
        return self.b.eval(js) or ""

    def lookup_competitor(self, asin):
        print(f"\n  📊 卖家精灵查竞品: {asin}")
        self.goto("competitor")
        self.search_asin_input(asin)
        human_pause(1, 2)
        self.click_search_btn()
        time.sleep(3)
        self.b.scroll_down(times=1)
        human_pause(0.5, 1)
        return {"asin": asin, "text": self.get_page_text()[:3000], "timestamp": datetime.now().isoformat()}

    def lookup_keywords(self, asin):
        print(f"\n  🔑 关键词反查: {asin}")
        self.goto("reversing")
        self.search_asin_input(asin)
        human_pause(1, 2)
        self.click_search_btn()
        time.sleep(3)
        return {"asin": asin, "text": self.get_page_text()[:3000], "timestamp": datetime.now().isoformat()}

    def lookup_ads(self, asin):
        print(f"\n  📢 广告洞察: {asin}")
        self.goto("ads_insights")
        self.search_asin_input(asin)
        human_pause(1, 2)
        self.click_search_btn()
        time.sleep(3)
        return {"asin": asin, "text": self.get_page_text()[:2000], "timestamp": datetime.now().isoformat()}

    def full_asin_check(self, asin):
        print(f"\n{'='*60}")
        print(f"📊 卖家精灵 - 查ASIN {asin}")
        print(f"{'='*60}")
        data = {"competitor": self.lookup_competitor(asin)}
        if random.random() < 0.8:
            data["keywords"] = self.lookup_keywords(asin)
        if random.random() < 0.5:
            data["ads"] = self.lookup_ads(asin)
        return data

    def find_related_asins(self, asin, max_results=4):
        """
        从卖家精灵查竞品页面提取关联ASIN列表。
        返回最多 max_results 个关联ASIN的列表。
        """
        print("\n  [精灵] 查找关联ASIN: %s" % asin)
        
        # 先查竞品
        result = self.lookup_competitor(asin)
        page_text = result.get("text", "") if isinstance(result, dict) else ""
        
        # 从页面文本提取所有B0开头的ASIN
        found = re.findall(r'B[A-Z0-9]{9,10}', page_text)
        
        # 去重，排除主ASIN自己
        related = []
        for a in found:
            a_clean = a.strip()
            if a_clean != asin and a_clean not in related:
                # 验证是不是B0开头+10位（标准亚马逊ASIN格式）
                if len(a_clean) == 10 and a_clean.startswith('B0'):
                    related.append(a_clean)
        
        # 如果从竞品页面没找到足够多，尝试从关键词反查页面
        if len(related) < max_results:
            print("  [精灵] 竞品页面ASIN不够，尝试关键词反查页面...")
            try:
                kw_result = self.lookup_keywords(asin)
                kw_text = kw_result.get("text", "") if isinstance(kw_result, dict) else ""
                more = re.findall(r'B[A-Z0-9]{9,10}', kw_text)
                for a in more:
                    a_clean = a.strip()
                    if a_clean != asin and a_clean not in related and len(a_clean) == 10 and a_clean.startswith('B0'):
                        related.append(a_clean)
            except:
                pass
        
        # 如果提取不到（页面还没加载完等），返回空列表，不报错
        if not related:
            print("  [精灵] 未找到关联ASIN（页面可能未加载完成）")
            return []
        
        result = related[:max_results]
        print("  [精灵] 找到 %d 个关联ASIN: %s" % (len(result), result))
        return result

    def search_keyword(self, keyword):
        print(f"\n  🔍 卖家精灵关键词: {keyword}")
        self.goto("keyword_research")
        # 关键词搜在输入框
        js = f"""
        (() => {{
            const inputs = document.querySelectorAll('input[type="text"], input:not([type="hidden"])');
            for (const inp of inputs) {{
                const s = window.getComputedStyle(inp);
                if (s.display !== 'none' && s.visibility !== 'hidden') {{
                    inp.focus();
                    inp.value = '';
                    const text = {json.dumps(keyword)};
                    for (let i = 0; i < text.length; i++) {{
                        inp.value += text[i];
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                    }}
                    return true;
                }}
            }}
            return false;
        }})()
        """
        self.b.eval(js)
        human_pause(1, 2)
        self.click_search_btn()
        time.sleep(3)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_kw = re.sub(r'[^a-zA-Z0-9]', '_', keyword)[:20]
        return {"keyword": keyword, "text": self.get_page_text()[:3000], "timestamp": datetime.now().isoformat()}
