"""知识库管理：播种到可写目录、导入日更文件并用配置的 LLM 蒸馏为增量情报。"""
from __future__ import annotations

import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

UPDATES_NAME = "UPDATES.md"
UPDATES_HEADER = "# 知识库增量情报（导入面经日更文件蒸馏生成，面试官优先使用）\n"
# 这一个数字同时管三件事，不许再各管各的：文件保留多少、去重时回看多少、注入提示词多少。
# 三者相等 =「存下来的」永远等于「用得上的」。之前是 80000/12000/30000，导致 4 天前的内容
# 会被当新的重复收录，10 天前的躺在文件里却永远进不了提示词。
# 之所以敢全量注入：提示词命中缓存，实测 1.6 万 token 和 20 token 的延迟一样。
MAX_UPDATES_CHARS = 60000   # UPDATES.md 总量上限（保新弃旧），约 20 天
# 注入提示词的「正文」只取最近这么多字符，更早的只在目录里留一行摘要。
# 不是怕撑爆窗口（跑满也才 ~71k tokens，对 1M 窗口是 7%），是怕稀释：
# 情报 55k 压着人格卡+题库 16k，面试官的注意力会被面经带偏。
INTEL_BODY_CHARS = 20000    # 约 7 天的全文
MAX_IMPORT_CHARS = 300000   # 单次导入原文上限

# ---- 联网搜索域名白名单（只写域名，不带 http/https；子域名自动包含）----
# 面经与技术社区
SEARCH_DOMAINS_CN = [
    "zhihu.com",          # 知乎
    "nowcoder.com",       # 牛客网
    "xiaohongshu.com",    # 小红书
    "v2ex.com",           # V2EX
    "juejin.cn",          # 掘金
    "csdn.net",           # CSDN
    "cnblogs.com",        # 博客园
    "segmentfault.com",   # 思否
    "jianshu.com",        # 简书
    "bilibili.com",       # B 站（面经视频/专栏）
    "mp.weixin.qq.com",   # 微信公众号文章
    # 行业动态
    "qbitai.com",         # 量子位
    "jiqizhixin.com",     # 机器之心
    "infoq.cn",           # InfoQ 中文
    "36kr.com",           # 36 氪
]

# 国外平台：暂不启用，保留备用（想开就并进 SEARCH_ALLOWED_DOMAINS）
SEARCH_DOMAINS_INTL = [
    "reddit.com",
    "news.ycombinator.com",
    "stackoverflow.com",
    "medium.com",
    "github.com",
    "arxiv.org",
]

# 实际生效的白名单：只搜中文平台
SEARCH_ALLOWED_DOMAINS = SEARCH_DOMAINS_CN

DISTILL_SYSTEM = """你是模拟面试官的知识库编辑。用户会给你一份「AI Agent 实习准备」日更文档，你从中提取对模拟面试官**当下有用的增量内容**，输出紧凑的 Markdown。

只提取这四类（没有的类别直接省略）：
1. **新增面试题**：一行一题，格式「题目 —— 公司来源｜频率（必考/高频/偶尔）｜答案要点（一句话）」
2. **新场景设计题素材**：面试官可以拿来搭台子的业务场景（业务背景+量级数字+考察点）
3. **行业新事件及其面试考点**：事件一句话 + 面试官可以怎么问
4. **新手撕题**：题名 + 考察点，不要贴完整代码

硬性要求：
- 忽略学习路线、资源清单、历史累积统计、风险提示等与出题无关的部分
- 忽略文档里明显是往期已收录的内容（标了"保留""历史归档"的部分）
- 总输出不超过 3500 字，宁缺毋滥，只留面试官出题用得上的
- 不要开场白和总结，直接输出内容
- **第一行固定输出主题摘要**，格式 `主题：关键词 / 关键词 / 关键词`（3-5 个词，不超过 30 字，
  取最有出题价值的公司名与技术点），空一行再写正文。这行会被抽出来做情报目录。"""


RESEARCH_SYSTEM = """你是模拟面试官的每日情报官。用 web_search 工具搜索**近 3 天**中文互联网上新出现的 AI Agent 开发方向面经与行业动态，产出给面试官出题用的增量情报。

搜索范围已被限制在中文平台（知乎、牛客网、小红书、V2EX、掘金、CSDN、博客园、思否、简书、B站、微信公众号，以及量子位/机器之心/InfoQ中文/36氪），搜不到结果时换关键词，不要试图去英文站。

搜索策略（执行 4-8 次搜索）：
- "Agent 面经 牛客" / "AI Agent 面试 一面 二面"（加上当前月份）
- "大模型应用开发 面经"（知乎/掘金/CSDN）
- "AI Agent 面试" 小红书 / V2EX（求职、offer 讨论帖里常有一手面经）
- 大厂关键词轮换：字节/美团/阿里/腾讯/蚂蚁/京东/百度 + "Agent 面经"
- "AI Agent" 行业重大发布（近3天）

输出格式（紧凑 Markdown，总量不超过 3000 字）：
1. **新增面试题**：一行一题「题目 —— 公司｜频率（必考/高频/偶尔）｜答案要点一句话」
2. **新场景设计题素材**：可搭台子的业务场景（背景+量级+考察点）
3. **行业新事件及面试考点**：事件一句话 + 可以怎么问
4. **新手撕题**：题名 + 考察点

硬性要求：
- 用户会提供已收录情报的清单，**只输出未收录的新内容**，重复的丢弃
- 每条注明来源平台；搜索结果的发布时间不确定时标注"（时间待核）"
- 确实没有新内容就只输出一行：「今日无新增面经，行业无重大变化。」
- 不要开场白、不要总结、不要建议
- **第一行固定输出主题摘要**，格式 `主题：关键词 / 关键词 / 关键词`（3-5 个词，不超过 30 字，
  取最有出题价值的公司名与技术点），空一行再写正文。这行会被抽出来做情报目录。
  （"今日无新增"的情况不需要主题行。）"""



def site_stats(sources: list[dict]) -> list[dict]:
    """把引用到的网页按站点归并计数，多的排前面：[{"host": "zhihu.com", "count": 5}]。"""
    hosts = []
    for src in sources or []:
        host = urlparse(src.get("url", "")).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if not host:
            continue
        # 子域名归并到白名单里的主站，zhuanlan.zhihu.com 和 zhihu.com 算一家
        hosts.append(next(
            (d for d in SEARCH_ALLOWED_DOMAINS if host == d or host.endswith("." + d)),
            host,
        ))
    return [{"host": h, "count": n} for h, n in Counter(hosts).most_common()]

