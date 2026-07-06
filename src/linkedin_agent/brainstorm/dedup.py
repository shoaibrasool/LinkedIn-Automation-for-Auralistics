import logging
from datetime import datetime, timezone

from linkedin_agent.config import (
    get_pinecone_api_key,
    get_pinecone_embed_model,
    get_pinecone_index_name,
)

logger = logging.getLogger(__name__)

PINECONE_DIMENSIONS = {
    "multilingual-e5-large": 1024,
    "llama-text-embed-v2": 1024,
    "voyage-2": 1024,
    "text-embedding-ada-002": 1536,
}

SIMILARITY_THRESHOLD = 0.85


def _get_pinecone_client():
    from pinecone import Pinecone, ServerlessSpec

    api_key = get_pinecone_api_key()
    index_name = get_pinecone_index_name()
    model = get_pinecone_embed_model()

    pc = Pinecone(api_key=api_key)

    existing = [i.name for i in pc.indexes.list()]
    if index_name not in existing:
        dim = PINECONE_DIMENSIONS.get(model, 1024)
        pc.indexes.create(
            name=index_name,
            dimension=dim,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        logger.info("Created Pinecone index '%s' (dim=%d)", index_name, dim)

    return pc, pc.index(index_name), model


def dedup_angles(angles: list[dict]) -> list[dict]:
    try:
        pc, index, model = _get_pinecone_client()
    except Exception as e:
        logger.warning("Pinecone not configured or unreachable (%s); skipping dedup", e)
        return angles

    if not angles:
        return []

    texts = [f"{a.get('hook', '')} {a.get('premise', '')}" for a in angles]

    try:
        embedding_response = pc.inference.embed(
            model=model,
            inputs=[{"text": t} for t in texts],
            parameters={"input_type": "passage", "truncate": "END"},
        )
        embeddings = [e["values"] for e in embedding_response.data]
    except Exception as e:
        logger.warning("Embedding failed (%s); skipping dedup", e)
        return angles

    deduped = []
    for i, angle in enumerate(angles):
        if not embeddings[i]:
            deduped.append(angle)
            continue

        try:
            results = index.query(
                vector=embeddings[i],
                top_k=1,
                include_metadata=False,
            )
            if results.matches and results.matches[0].score > SIMILARITY_THRESHOLD:
                logger.info(
                    "Skipping angle '%s' — similar to existing vector (score=%.3f)",
                    angle.get("hook", "")[:40],
                    results.matches[0].score,
                )
                continue
        except Exception as e:
            logger.warning("Query failed for angle %d (%s); including anyway", i, e)

        deduped.append(angle)

    skipped = len(angles) - len(deduped)
    if skipped:
        logger.info("Dedup removed %d/%d angles", skipped, len(angles))

    return deduped


def upsert_angle_vectors(angles: list[dict], idea_id: str | None = None) -> None:
    try:
        pc, index, model = _get_pinecone_client()
    except Exception as e:
        logger.warning("Pinecone not configured (%s); skipping vector upsert", e)
        return

    if not angles:
        return

    texts = [f"{a.get('hook', '')} {a.get('premise', '')}" for a in angles]

    try:
        embedding_response = pc.inference.embed(
            model=model,
            inputs=[{"text": t} for t in texts],
            parameters={"input_type": "passage", "truncate": "END"},
        )
        embeddings = [e["values"] for e in embedding_response.data]
    except Exception as e:
        logger.warning("Embedding failed (%s); skipping vector upsert", e)
        return

    vectors = []
    for i, angle in enumerate(angles):
        if not embeddings[i]:
            continue
        vector_id = f"{idea_id or 'unknown'}_{i}"
        vectors.append({
            "id": vector_id,
            "values": embeddings[i],
            "metadata": {
                "angle_hook": angle.get("hook", ""),
                "angle_premise": angle.get("premise", ""),
                "stance": angle.get("stance", ""),
                "original_idea_id": idea_id or "",
                "status": "drafted",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        })

    if vectors:
        try:
            index.upsert(vectors=vectors, namespace="angles")
            logger.info("Upserted %d angle vectors to Pinecone", len(vectors))
        except Exception as e:
            logger.warning("Pinecone upsert failed (%s)", e)
