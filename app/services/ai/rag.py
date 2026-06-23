"""RAG over GLOBAL, pedagogical-only content (vocabulary, grammar, idioms…).

Student data is NEVER indexed here. Ingestion only stores `verified` educational
material; search embeds the query and runs cosine ANN via the `match_rag_chunks`
Postgres function. `chunk_text` and `build_context` are pure (unit-tested); the
embed/insert/search paths do I/O.
"""

from __future__ import annotations

from app.services import supabase_admin as db
from app.services.openai_client import embed, embed_batch

CHUNK_MAX_CHARS = 900
CHUNK_OVERLAP = 120
CONTEXT_MAX_CHARS = 1800


def chunk_text(text: str, max_chars: int = CHUNK_MAX_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Pack paragraphs into chunks <= max_chars (hard-splitting very long ones)."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    buf = ""
    for para in (p.strip() for p in text.split("\n") if p.strip()):
        if len(para) > max_chars:
            if buf:
                chunks.append(buf)
                buf = ""
            step = max(1, max_chars - overlap)
            for i in range(0, len(para), step):
                chunks.append(para[i : i + max_chars])
            continue
        if len(buf) + len(para) + 1 <= max_chars:
            buf = f"{buf}\n{para}".strip()
        else:
            if buf:
                chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)
    return chunks


def build_context(chunks: list[dict], max_chars: int = CONTEXT_MAX_CHARS) -> tuple[str, list[dict]]:
    """Format retrieved chunks into a numbered context block + the used sources.
    Pure: no I/O."""
    used: list[dict] = []
    blocks: list[str] = []
    total = 0
    for i, c in enumerate(chunks or [], 1):
        content = (c.get("content") or "").strip()
        if not content:
            continue
        block = f"[{i}] (tópico: {c.get('topic')}, nível: {c.get('level')})\n{content}"
        if blocks and total + len(block) > max_chars:
            break
        blocks.append(block)
        used.append(c)
        total += len(block)
    return "\n\n".join(blocks), used


async def search(
    query: str,
    *,
    topic: str | None = None,
    level: str | None = None,
    language: str | None = None,
    k: int = 4,
) -> list[dict]:
    """Embed the query and return the top-k verified pedagogical chunks."""
    if not (query or "").strip():
        return []
    vector = await embed(query)
    res = await db.rpc(
        "match_rag_chunks",
        {
            "query_embedding": vector,
            "match_count": k,
            "filter_topic": topic,
            "filter_level": level,
            "filter_language": language,
        },
    )
    return res if isinstance(res, list) else []


async def ingest_document(doc: dict) -> int:
    """Insert one pedagogical document + its embedded chunks. Returns chunk count.

    doc: {title, topic, level?, language?, source?, verified?, content, metadata?}
    """
    document = await db.insert(
        "rag_documents",
        {
            "title": doc["title"],
            "topic": doc["topic"],
            "level": doc.get("level", "A1"),
            "language": doc.get("language", "en-pt"),
            "source": doc.get("source", "internal_curriculum"),
            "verified": bool(doc.get("verified", False)),
            "content": doc["content"],
            "metadata": doc.get("metadata", {}),
        },
    )
    if not document:
        return 0
    chunks = chunk_text(doc["content"])
    if not chunks:
        return 0
    vectors = await embed_batch(chunks)
    for i, (content, vector) in enumerate(zip(chunks, vectors)):
        await db.insert(
            "rag_chunks",
            {
                "document_id": document["id"],
                "chunk_index": i,
                "content": content,
                "embedding": vector,
                "topic": doc["topic"],
                "level": doc.get("level", "A1"),
                "language": doc.get("language", "en-pt"),
                "verified": bool(doc.get("verified", False)),
                "metadata": doc.get("metadata", {}),
            },
        )
    return len(chunks)
