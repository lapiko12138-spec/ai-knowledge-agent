# AI Knowledge Agent

An Obsidian-first workflow for turning AI papers, posts, podcasts, videos, and
articles into durable Knowledge Chunks, explicit graph relationships, learning
gaps, daily digests, weekly reviews, and Feishu Card 2.0 messages.

## Design

- **Source notes are evidence records.** News, opinions, and low-value items can
  remain sources without becoming knowledge.
- **Knowledge Chunks are atomic.** Each card has a stable ID, canonical key,
  level, priority, source history, and Obsidian Wikilinks.
- **Deduplication happens before creation.** Exact titles, canonical keys, and
  aliases update existing cards. Similar titles are held for review.
- **The graph is native to Obsidian.** Relationships are readable Wikilinks,
  while `99 System/index.json` provides deterministic automation state.
- **Feishu is a delivery layer.** Full knowledge remains local; Feishu receives
  a compact daily card.

## Quick Start

The default vault is `~/Downloads/obsidian`.

```bash
python3 -m ai_knowledge_agent init
python3 -m ai_knowledge_agent ingest examples/ingest.example.json
python3 -m ai_knowledge_agent search "KV Cache"
python3 -m ai_knowledge_agent daily --date 2026-10-03
python3 -m ai_knowledge_agent weekly --week-end 2026-10-03
```

启动中文交互学习台：

```bash
python3 -m ai_knowledge_agent serve
```

默认地址为 `http://127.0.0.1:8765`。如果端口被占用，服务会自动尝试后续端口。
网页直接读取 Obsidian 索引，并将学习状态、理解程度和笔记写入
`AI Knowledge/99 System/learning-progress.json`。当知识库为空时，页面使用不落盘的
示例知识展示完整交互。

“今日雷达”会自动读取并缓存 Hugging Face Daily Papers，将论文分为
每日 5/8/10 篇与 `Focus 2`，并以中英双语标题、研究问题、核心方法、实验结论、限制
与概念候选展示。人物雷达支持逐条已阅；配置 X 官方 API 后，每日任务会刷新关注人物
近 7 天原帖。Bearer Token 可通过 `X_BEARER_TOKEN` 环境变量提供，或写入本机
`~/Library/Application Support/AI Knowledge Agent/x-bearer-token`。未配置时页面会明确
显示缓存快照及截止日期。详细产品拆分见
[`docs/product-blueprint.md`](docs/product-blueprint.md)。

安装每日自动更新（macOS，默认每天 08:00）：

```bash
python3 -m ai_knowledge_agent schedule install --hour 8 --minute 0
python3 -m ai_knowledge_agent schedule status
```

计划任务使用 `launchd`，登录或重启后自动补漏，并使用互斥锁防止重复运行。状态保存到
`AI Knowledge/99 System/daily-update-status.json`；日志位于同目录下的 `logs/`。
为绕过 macOS 对后台进程写入 Downloads 的限制，真实数据保存在
`~/Library/Application Support/AI Knowledge Agent/Obsidian/AI Knowledge`，原 Obsidian
路径保留符号链接，Obsidian 内的使用路径不变。

知识快照会在每日更新后自动推送到 GitHub。网页中的学习进度、笔记和人物雷达已阅状态
保存后也会立即刷新快照并推送；通知接收人、日志、锁文件和临时文件始终只保留在本机。

启用每日飞书学习提醒：

```bash
python3 -m ai_knowledge_agent notification configure \
  --user-id ou_xxx \
  --as bot
python3 -m ai_knowledge_agent notification test --dry-run
python3 -m ai_knowledge_agent notification test --confirm-send
python3 -m ai_knowledge_agent notification status
```

通知卡片包含今日 Deep Dive、论文列表和未读人物观点。配置保存在本机
`AI Knowledge/99 System/notification-config.json`，不会进入 GitHub 知识快照；每天使用
日期幂等键发送，避免同一天重复提醒。使用 `notification disable` 可暂停推送。

Generate a card JSON:

```bash
python3 -m ai_knowledge_agent card \
  --date 2026-10-03 \
  --output daily-card.json
```

Preview a Feishu send:

```bash
python3 -m ai_knowledge_agent send-daily \
  --date 2026-10-03 \
  --user-id ou_xxx \
  --as bot \
  --dry-run
```

A live send additionally requires `--confirm-send`. This forces explicit review
of the recipient, content, and identity. Bot identity is the default because the
current user token does not include `im:message.send_as_user`.

Use another vault with either:

```bash
python3 -m ai_knowledge_agent --vault "/path/to/vault" init
export AI_KNOWLEDGE_VAULT="/path/to/vault"
```

## Input Contract

Ingestion accepts JSON from a file or stdin. See
[`examples/ingest.example.json`](examples/ingest.example.json).

The research agent should complete these stages before ingestion:

1. Classify value as A–G and mark fact/research/interpretation/opinion/prediction.
2. Extract reusable understanding rather than an article summary.
3. Split content into independent, stable chunks.
4. Search existing chunks and assign canonical keys, aliases, parents, and
   typed connections.
5. Score relevance, novelty, connection, and impact from 0–5.

`G` chunks are skipped. A similar title is not created automatically; it appears
under `review_required`. After review, either reuse the existing
`canonical_key`, or ingest with `--allow-similar` when it is genuinely distinct.

## Vault Layout

```text
AI Knowledge/
├── 00 Inbox/
├── 10 Sources/
├── 20 Knowledge Chunks/
├── 30 Knowledge Maps/
├── 40 Daily Digests/
├── 50 Weekly Reviews/
└── 99 System/
```

Run tests with:

```bash
python3 -m unittest discover -s tests -v
```
