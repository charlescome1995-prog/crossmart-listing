#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
亚马逊前台浏览器 - 模拟人类浏览行为
"""
import sys, os, json, random, time, re
sys.stdout.reconfigure(encoding='utf-8')
sys.dont_write_bytecode = True
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from browser.cdp_bridge import CDPBrowser, SCREENSHOT_DIR
from browser.human_timer import human_pause, read_pause, think_pause


_COMMON_SEARCHES = [
    "gift ideas", "best sellers", "new arrivals",
    "beauty products", "home kitchen", "electronics",
    "pet supplies", "office accessories", "travel gear",
    "fitness equipment", "storage bins", "bathroom organizer",
    "phone case", "wireless charger", "yoga mat",
    "water bottle", "desk lamp", "wall decor",
    "kitchen knife set", "makeup brush set",
]


class AmazonBrowser:
    """亚马逊前台浏览模拟器"""

    def __init__(self, browser: CDPBrowser):
        self.b = browser
        self.current_asin = None

    def browse_homepage(self):
        """逛首页"""
        print(f"\n  🌐 逛首页...")
        self.b.navigate("https://www.amazon.com/")
        read_pause()
        self.b.scroll_down(times=random.randint(1, 2))
        human_pause()
        if random.random() < 0.3:
            self.b.scroll_up()
        return self

    def browse_category(self):
        """逛一个随机类目"""
        cat = random.choice(_COMMON_SEARCHES)
        print(f"\n  🏷️ 逛类目: {cat}")
        self.b.navigate(f"https://www.amazon.com/s?k={cat.replace(' ', '+')}")
        read_pause()
        for _ in range(random.randint(0, 2)):
            self.b.scroll_down(times=2)
            human_pause(1, 3)
        return self

    def random_search(self, keyword=None):
        kw = keyword or random.choice(_COMMON_SEARCHES)
        print(f"\n  🔍 搜索: {kw}")
        self.b.navigate(f"https://www.amazon.com/s?k={kw.replace(' ', '+')}", wait_min=3, wait_max=6)
        self.b.scroll_down(times=random.randint(1, 3))
        human_pause(2, 5)
        return self

    def search_for_asin(self, asin, search_keyword=None):
        """搜索关键词后在结果页点击 ASIN 链接，而非直接跳转"""
        self.current_asin = asin
        kw = search_keyword or random.choice(_COMMON_SEARCHES)
        print(f"\n  🎯 搜索 '{kw}' 找 {asin}")
        self.b.navigate(f"https://www.amazon.com/s?k={kw.replace(' ', '+')}", wait_min=2, wait_max=4)
        self.b.scroll_down(times=random.randint(1, 2))
        human_pause(1, 3)
        clicked = self._click_asin_in_results(asin)
        if not clicked:
            print(f"  ⚠️ 搜索结果未找到 ASIN {asin}，fallback 直接跳转")
            self.b.navigate(f"https://www.amazon.com/dp/{asin}", wait_min=2, wait_max=4)
        read_pause()
        return self

    def _click_asin_in_results(self, asin):
        """从搜索结果页找目标 ASIN 并点击"""
        js = (
            "(() => {"
            "const links = document.querySelectorAll("
            "'a.a-link-normal.s-no-outline[href*=\"/dp/" + asin + "\"],"
            " a.a-link-normal[href*=\"/dp/" + asin + "?\"]');"
            "const natural = Array.from(links).filter(a => "
            "!a.closest('[class*=\"advertisement\"],[class*=\"Sponsored\"]') && "
            "a.href.includes('/dp/" + asin + "'));"
            "if (natural.length > 0) {"
            "const el = natural[0];"
            "el.scrollIntoView({behavior:'smooth', block:'center'});"
            "setTimeout(() => el.click(), 300);"
            "return JSON.stringify({ok: true});"
            "}"
            "return JSON.stringify({ok: false});"
            "})()"
        )
        import json as _j
        result = _j.loads(self.b.eval(js) or '{"ok":false}')
        if result.get('ok'):
            print(f"  🖱️ 点击搜索结果中的 ASIN {asin}")
            time.sleep(random.uniform(2, 4))
            return True
        return False

    def view_asin_detail(self, asin):
        self.current_asin = asin
        print(f"\n  📄 查看 ASIN {asin}")
        self.b.navigate(f"https://www.amazon.com/dp/{asin}", wait_min=2, wait_max=5)
        read_pause()
        return self

    def view_competitor(self, asin):
        print(f"\n  👀 顺便看竞品 {asin}")
        self.b.navigate(f"https://www.amazon.com/dp/{asin}", wait_min=2, wait_max=4)
        human_pause(2, 6)
        self.b.scroll_down(times=random.randint(1, 2))
        think_pause()
        return self

    def screenshot_asin(self):
        if not self.current_asin:
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"asin_{self.current_asin}_{ts}"
        path = self.b.screenshot(name)
        if path:
            self.b.scroll_up()
            human_pause(0.5, 1)
            self.b.screenshot(f"asin_{self.current_asin}_{ts}_detail")
        return path

    def screenshot_search_results(self, keyword):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_kw = re.sub(r'[^a-zA-Z0-9]', '_', keyword)[:30]
        self.b.screenshot(f"search_{safe_kw}_{ts}")
        return self

    def full_asin_check(self, asin, search_keyword=None, competitors=None):
        print(f"\n{'='*60}")
        print(f"🛒 检查 ASIN: {asin}")
        print(f"   {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}")

        # 极少逛首页
        if random.random() < 0.1:
            self.browse_homepage()

        self.search_for_asin(asin, search_keyword)
        self.b.scroll_down(times=random.randint(1, 2))
        think_pause()
        self.screenshot_asin()

        # 竞品浏览概率降低，且不看评论页
        if competitors and random.random() < 0.3:
            n = random.randint(1, min(2, len(competitors)))
            selected = random.sample(competitors, n)
            for comp in selected:
                self.view_competitor(comp)
        return self

    def full_keyword_check(self, keyword):
        print(f"\n{'='*60}")
        print(f"🔍 关键词市场: {keyword}")
        print(f"{'='*60}")

        if random.random() < 0.5:
            self.browse_homepage()

        self.random_search(keyword)

        if random.random() < 0.5:
            self._go_next_page()

        self.screenshot_search_results(keyword)

        if random.random() < 0.6:
            self._click_random_result()

        return self

    def _go_next_page(self):
        self.b.eval("""
            (() => {
                const n = document.querySelector('.s-pagination-next, [class*="pagination"] a:last-child');
                if (n) { n.click(); return true; }
                return false;
            })()
        """)
        human_pause(3, 6)
        self.b.scroll_down(times=random.randint(1, 2))

    def _click_random_result(self):
        js = """
        (() => {
            const links = document.querySelectorAll('a.a-link-normal.s-no-outline[href*="/dp/"], a.a-link-normal[href*="/dp/"]');
            const natural = Array.from(links).filter(a => !a.closest('[class*="advertisement"],[class*="Sponsored"]'));
            if (natural.length > 0) {
                const idx = Math.floor(Math.random() * Math.min(natural.length, 5));
                const title = natural[idx].querySelector('h2, span')?.textContent?.trim() || 'unknown';
                return JSON.stringify({index: idx, title: title.substring(0, 60), href: natural[idx].href});
            }
            return null;
        })()
        """
        import json as j
        result = j.loads(self.b.eval(js) or "null")
        if result:
            print(f"  🖱️ 点击结果: {result.get('title','')[:40]}")
            self.b.navigate(result["href"], wait_min=2, wait_max=4)
            read_pause()
            self.b.scroll_down(times=random.randint(1, 2))
            human_pause(1, 3)