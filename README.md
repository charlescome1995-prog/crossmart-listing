# CrossMart Listing Builder

根据关键词找对标 ASIN，再基于对标 ASIN 特点用 AI 设计英文 Amazon Listing。

线上页面：https://charlescome1995-prog.github.io/crossmart-listing/frontend/listing.html

## 两步流程

**STEP 1 — 关键词 → 对标 ASIN**
- 用 Edge 唯一默认账户打开亚马逊搜索关键词
- 抓取前 N 个 ASIN（区分自然位 / 广告位）
- 逐个抓详情：标题、五点、价格、评分、评论数、品牌、BSR、徽章
- 按「评论数 40% + 评分 30% + 自然位 20% + 信息完整度 10%」选出对标 ASIN
- 输出 `backend/data/output/benchmark-<keyword>.json`

**STEP 2 — 对标 ASIN → 设计 Listing**
- 汇总对标共性（高频卖点词、价格带、标题结构、五点要素）
- 喂火山方舟 LLM，生成英文：Title / 5 Bullets / Description (A+) / Search Terms / 差异化建议
- 输出 `frontend/data/listing-data.json`（前端读这个）

## 用法

```powershell
# 设置火山方舟 API Key（STEP2 需要）
$env:ARK_API_KEY = "ark-..."

# 一键跑两步
python backend\run_listing.py "happy light"

# 只跑某一步
python backend\run_listing.py "happy light" --step 1
python backend\run_listing.py "happy light" --step 2

# 参数
python backend\run_listing.py "happy light" --max 15 --top 6

# 部署
git add -A; git commit -m "listing: happy light"; git push
# 然后 Ctrl+F5 刷新前端
```

## 🔥 铁律：浏览器抓取只用 Edge 唯一默认账户

见 `backend/browser/README_IRON_RULE.md`。所有抓取必须通过
`browser.edge_session.open_edge()`（端口 9225，不指定 profile）。

## 结构

```
crossmart-listing/
├── index.html                  # 跳转到 frontend/listing.html
├── backend/
│   ├── config.py
│   ├── run_listing.py          # 一键入口（STEP1+STEP2）
│   ├── step1_find_benchmark.py # 关键词→对标 ASIN
│   ├── step2_build_listing.py  # 对标 ASIN→Listing
│   ├── llm_client.py + llm_config.py   # 火山方舟
│   ├── browser/                # Edge 唯一默认账户铁律底座
│   └── data/output/            # benchmark/listing 存档
└── frontend/
    ├── listing.html
    └── data/listing-data.json
```
