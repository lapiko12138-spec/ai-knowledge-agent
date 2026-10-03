# AI Knowledge Learning Product Blueprint

## 1. 播客样本结论

样本节目：[`HuggingFace 每日AI论文速递`](https://www.xiaoyuzhoufm.com/podcast/667d1ecfc13b46d76c3f64b8)

节目不是按“完整论文摘要”组织，而是一个分层编辑系统：

| 周期 | 输入 | 输出 | 作用 |
| --- | --- | --- | --- |
| 日更 | Hugging Face 当日论文 | 约 15 篇快速扫描，标题突出 2 篇 | 建立每日覆盖面 |
| 周更 | 一周重复出现及高热论文 | TOP5，保留 Hugging Face 热度 | 识别短期趋势 |
| 月更 | 月度累计信号 | TOP10 | 识别持续趋势 |

可复用的核心不是“播客形式”，而是四层漏斗：

1. **全量扫描**：不因个人偏好过早过滤。
2. **热度与相关性筛选**：社区热度只是一项信号，还要叠加个人相关性。
3. **教学拆解**：把论文拆成问题、方法、证据、限制、影响和新概念。
4. **概念入图**：只把稳定知识写入 Knowledge Graph，新闻与热度留在来源层。

## 2. 产品主干

### A. X 人物雷达

回答三个问题：

- 今天谁在讨论什么？
- 同一话题是事实、研究解释、观点还是预测？
- 哪些独立人物开始同时讨论同一概念？

人物不是一个名字列表。每个跟踪对象需要：

- 身份：研究者、工程师、Founder、Lab、教育者
- 稳定主题：长期关注的领域
- 信号类型：论文首发、工程经验、产品判断、行业预测
- 可信边界：一手事实、二手解释、个人观点
- 今日主题：帖子的核心命题
- 关联对象：论文、模型、公司和概念

### B. Hugging Face 论文雷达

每日论文先进入 Scan 层，最多 15 篇；选 2 篇进入 Focus 层。

每篇论文的教学拆解：

1. Research Question：它真正试图回答什么？
2. Previous Approach：以前为什么不够？
3. New Method：核心新方法是什么？
4. Mechanism：方法如何工作？
5. Evidence：哪些实验支撑结论？
6. Limitation：适用边界和失败条件是什么？
7. Potential Impact：可能改变什么技术或产品？
8. New Concepts：哪些概念需要建立或补充知识卡？
9. People / Lab：作者和机构为什么值得继续跟踪？

### C. 概念建图

新概念不直接成为独立卡片，先进入候选区：

- 已存在：补充论文和案例。
- 新解释：更新原知识卡。
- 下位概念：创建卡片并建立 `child_of`。
- 新概念：创建卡片并指定上位节点。
- 新关系：只增加 Relationship。

## 3. 每日学习流程

```text
实时输入
  ├─ X 人物讨论
  ├─ Hugging Face Daily Papers
  └─ Podcast / Lab Blog
        ↓
信号归一化
  ├─ Fact / Research / Interpretation / Opinion / Prediction
  └─ Person / Paper / Model / Company / Concept
        ↓
每日编辑漏斗
  ├─ Scan 15
  ├─ Focus 2
  └─ Deep Dive 1
        ↓
教学拆解
        ↓
概念候选与去重
        ↓
Knowledge Graph + 学习卡 + 飞书摘要
```

## 4. 学习优先级

论文热度不能直接等于学习优先级：

```text
Learning Priority =
Personal Relevance
× Knowledge Novelty
× Graph Connection
× Technical / Product Impact
× Evidence Confidence
```

Hugging Face upvotes、X 讨论数量和作者影响力只进入 `External Signal`，不替代上述学习评分。

## 5. Web 信息架构

### 今日

- 今日核心判断
- X 人物雷达
- Hugging Face Scan 15 / Focus 2
- 待入图概念
- 今日 Deep Dive

### 论文

- Daily / Weekly / Monthly
- Scan / Focus / Archived
- 教学拆解详情
- 作者与机构
- 概念候选

### 知识

- Knowledge Chunks
- Knowledge Map
- Learning Gaps
- 学习进度与笔记

### 来源

- 人物
- Lab / Company
- Podcast / Blog
- 连接状态与可信边界

## 6. 实施拆分

### Phase 1：可靠输入与阅读面

- Hugging Face Daily Papers 自动采集与缓存
- 论文 Scan / Focus 分层
- 论文教学详情
- 播客编辑模型固化
- X 人物配置与“未接入”真实状态

### Phase 2：智能拆解

- LLM 生成问题 / 方法 / 证据 / 限制
- 概念抽取与已有知识相似度检索
- 人物、机构、论文和概念实体对齐
- 候选概念人工确认后入图

### Phase 3：实时人物雷达

- 接入 X 官方 API 或用户授权的数据源
- 聚合同主题的多人物讨论
- Opinion / Fact 边界与来源引用
- 24 小时主题变化与重复信号

### Phase 4：学习闭环

- 每日 Deep Dive
- 间隔复习与理解程度
- Knowledge Gap 任务
- 飞书早报、晚间学习卡与周复盘

## 7. 当前边界

- Hugging Face 数据可直接公开读取，已实现自动采集。
- X 尚未配置官方 API，因此只建立人物清单与数据模型，不展示虚构实时帖子。
- Daily Papers 摘要可以支持初筛，但不能代替论文正文中的实验、限制和失败案例。
