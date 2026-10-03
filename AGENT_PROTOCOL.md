# AI Research and Knowledge Protocol

## Objective

Build an evolving AI mental model, not a news archive. The durable outputs are:

- Atomic Knowledge Chunks
- Typed knowledge relationships
- Learning gaps and open questions
- Daily incremental digests
- Weekly synthesis and learning priorities

Always apply: **Chunk before summarize.**

## Source Workflow

### 1. Value Gate

Classify each item before extracting chunks:

- `A` New knowledge
- `B` New explanation of known knowledge
- `C` Extension of existing knowledge
- `D` News or event
- `E` Opinion or judgment
- `F` Case
- `G` No durable value yet

Do not force `D`, `E`, or `G` into a Knowledge Chunk. Preserve the source and its
evidence boundary when it remains useful.

For X content, explicitly distinguish fact, research, interpretation, opinion,
and prediction. For podcasts, extract only specific facts, concepts, cases,
mental-model changes, and research questions.

### 2. Second-Order Understanding

For durable material, answer:

- What is it?
- Which problem does it solve, and why is that problem important?
- How does it work?
- How does it differ from prior approaches?
- Which capability does it enable?
- What could it affect?
- Which existing knowledge does it connect to?

Do not merely restate the source.

### 3. Chunking

Each chunk must be:

- Small enough to understand independently
- Complete enough to use without the source
- Stable enough to retain long term

One paper, episode, article, video, or thread may produce zero, one, or many
chunks. Never default to one source equals one chunk.

### 4. Deduplication and Linking

Search before creating:

1. Existing concept: update sources, examples, or explanation.
2. New understanding of an existing concept: update the same card.
3. Child concept: create a card and add `child_of`.
4. New concept: create a card.
5. Previously missing connection: add a typed relationship.

Prefer relationship types from the data dictionary. Use `related_to` only when a
more precise relation is not defensible.

### 5. Priority

Score every accepted chunk from 0–5:

`Priority = Relevance × Novelty × Connection × Impact`

Prefer concepts that connect several established nodes over isolated novelty.

## Knowledge Chunk Fields

Required:

- Title
- Category
- Concept
- Problem
- Mechanism
- Why it matters
- Example
- Connections and parents
- Level (`L1`–`L4`)
- Source
- First-seen date
- Three to eight keywords
- Priority factors

## Reports

Daily output contains:

1. Three to five developments worth knowing
2. New Knowledge Chunks
3. Existing Knowledge Updated
4. New connections
5. One Deep Dive
6. Open Questions

Weekly output must synthesize rather than concatenate:

1. What was actually learned
2. Repeated topics and emerging trends
3. Knowledge chains taking shape
4. Knowledge Gaps
5. At most three next topics

## Storage and Delivery

Obsidian is the system of record. Feishu cards are compact delivery views and
must not become a second knowledge database.
