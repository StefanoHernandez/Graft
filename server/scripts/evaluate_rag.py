"""Run the evaluation corpus against a real provider and record what happened.

This is the only thing that can say whether Graft answers well. Unit tests use
fakes by design, so they prove the plumbing and nothing about quality.

    uv run python scripts/evaluate_rag.py \
        --cases tests/fixtures/rag/cases.json \
        --output /tmp/graft-rag-results.json

Reads the API key from the environment (`MISTRAL_API_KEY` by default) and never
writes it, or any part of it, to the output.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from graft.config import get_settings
from graft.ingestion.pipeline import ingest_document
from graft.ingestion.storage import save_source
from graft.models import Bot, Document
from graft.providers.config import EmbeddingConfig, LLMConfig
from graft.providers.factory import build_embedder, build_llm
from graft.providers.fingerprint import embedding_fingerprint
from graft.rag.prompt import ABSTENTION
from graft.rag.retrieval import retrieve
from graft.rag.service import answer_question

DEFAULT_PROVIDER = "mistral"
DEFAULT_CHAT_MODEL = "mistral-small-latest"
DEFAULT_EMBED_MODEL = "mistral-embed"


async def run(args: argparse.Namespace) -> dict:
    key = os.environ.get(args.key_env)
    if not key:
        raise SystemExit(f"{args.key_env} is not set; live evaluation needs a real provider")

    payload = json.loads(Path(args.cases).read_text())
    corpus = Path(args.corpus or payload["corpus"])
    if not corpus.is_absolute():
        corpus = Path(__file__).resolve().parents[1] / corpus

    embedding_config = EmbeddingConfig(
        provider=args.provider, model=args.embed_model, api_key=key, api_key_encrypted=False
    )
    llm_config = LLMConfig(
        provider=args.provider, model=args.chat_model, api_key=key, api_key_encrypted=False
    )
    fingerprint = embedding_fingerprint(embedding_config)

    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    storage_root = get_settings().storage_root

    bot = await _prepare_bot(maker, embedding_config, llm_config)
    documents = await _ingest(maker, bot, corpus, embedding_config, storage_root, args)

    results = []
    for attempt in range(1, args.passes + 1):
        for case in payload["cases"]:
            results.append(
                await _run_case(maker, bot, case, attempt, embedding_config, llm_config,
                                fingerprint, args)
            )
            await asyncio.sleep(args.pause)

    report = {
        "provider": args.provider,
        "chat_model": args.chat_model,
        "embedding_model": args.embed_model,
        "embedding_fingerprint": fingerprint,
        "min_score": args.min_score,
        "top_k": args.top_k,
        "passes": args.passes,
        "documents": documents,
        "results": results,
        "summary": summarize(results),
    }
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    await engine.dispose()
    return report


async def _prepare_bot(maker, embedding_config, llm_config) -> Bot:
    async with maker() as session:
        bot = Bot(
            name=f"eval-{uuid.uuid4().hex[:8]}",
            widget_key=f"eval_{uuid.uuid4().hex}",
            embedding_config=embedding_config.model_dump(),
            llm_config=llm_config.model_dump(),
            system_prompt="",
        )
        session.add(bot)
        await session.commit()
        return bot


async def _ingest(maker, bot, corpus: Path, embedding_config, storage_root, args) -> list[dict]:
    embedder = build_embedder(embedding_config)
    ingested = []
    for path in sorted(corpus.iterdir()):
        if path.suffix not in {".md", ".txt", ".pdf"}:
            continue
        async with maker() as session:
            document = Document(
                bot_id=bot.id, filename=path.name,
                mime_type="text/markdown" if path.suffix == ".md" else "text/plain",
                status="pending",
            )
            session.add(document)
            await session.flush()
            document.storage_key = save_source(storage_root, bot.id, document.id,
                                               path.read_bytes())
            await session.commit()
            document_id = document.id
        chunks = await ingest_document(
            maker, document_id, embedder, embedding_model=args.embed_model,
            storage_root=storage_root,
        )
        ingested.append({"filename": path.name, "chunks": chunks})
        print(f"ingested {path.name}: {chunks} chunks", file=sys.stderr)
    if hasattr(embedder, "aclose"):
        await embedder.aclose()
    return ingested


async def _run_case(maker, bot, case, attempt, embedding_config, llm_config, fingerprint,
                    args) -> dict:
    embedder = build_embedder(embedding_config, max_retries=args.max_retries)
    llm = build_llm(llm_config, max_retries=args.max_retries)
    started = time.perf_counter()
    first_token = None
    answer = ""
    citations: list[dict] = []
    grounding = None
    error = None
    retrieved: list[dict] = []

    try:
        async with maker() as session:
            vectors = await embedder.embed([case["question"]], model=args.embed_model)
            retrieval_done = time.perf_counter()
            hits = await retrieve(session, bot.id, fingerprint, vectors[0],
                                  top_k=args.top_k, min_score=-1.0)
            retrieved = [
                {"filename": hit.filename, "score": round(hit.score, 4),
                 "heading": hit.heading, "page": hit.page}
                for hit in hits
            ]
            async for event in answer_question(
                session, bot=bot, embedder=embedder, llm=llm, question=case["question"],
                history=[], fingerprint=fingerprint, embedding_model=args.embed_model,
                chat_model=args.chat_model, top_k=args.top_k, min_score=args.min_score,
            ):
                if event["event"] == "delta" and first_token is None:
                    first_token = time.perf_counter()
                elif event["event"] == "done":
                    answer = event["data"]["answer"]
                    citations = event["data"]["citations"]
                    grounding = event["data"]["grounding"]
                elif event["event"] == "error":
                    error = event["data"]["code"]
    except Exception as exc:  # noqa: BLE001 - a failed case is data, not a crash
        error = getattr(exc, "code", None) or type(exc).__name__
    finally:
        for client in (embedder, llm):
            if hasattr(client, "aclose"):
                await client.aclose()

    total = time.perf_counter() - started
    return {
        "id": case["id"],
        "pass": attempt,
        "category": case["category"],
        "question": case["question"],
        "must_abstain": case["must_abstain"],
        "expected_documents": case["expected_documents"],
        "expected_facts": case["expected_facts"],
        "retrieved": retrieved,
        "top_score": retrieved[0]["score"] if retrieved else None,
        "answer": answer,
        "citations": [{"id": c["id"], "filename": c["filename"], "page": c["page"]}
                      for c in citations],
        "grounding": grounding,
        "error": error,
        "abstained": _abstained(answer, grounding),
        "cited_expected": _cited_expected(citations, case["expected_documents"]),
        "seconds": {
            "retrieval": round(retrieval_done - started, 3),
            "first_token": round(first_token - started, 3) if first_token else None,
            "total": round(total, 3),
        },
        # Filled in by a human afterwards; the script does not grade prose.
        "human_review": None,
    }


def _abstained(answer: str, grounding: str | None) -> bool:
    return grounding == "no_context" or answer.strip() == ABSTENTION


def _cited_expected(citations: list[dict], expected: list[str]) -> bool | None:
    if not expected:
        return None
    cited = {c["filename"] for c in citations}
    return bool(cited & set(expected))


def summarize(results: list[dict]) -> dict:
    by_category: dict[str, dict] = {}
    for row in results:
        bucket = by_category.setdefault(
            row["category"], {"cases": 0, "abstained": 0, "cited_expected": 0, "errors": 0}
        )
        bucket["cases"] += 1
        bucket["abstained"] += int(row["abstained"])
        bucket["cited_expected"] += int(bool(row["cited_expected"]))
        bucket["errors"] += int(bool(row["error"]))
    return {
        "by_category": by_category,
        # The gate's hard numbers. Everything else needs a human.
        "absent_abstained": sum(
            1 for r in results if r["category"] == "absent" and r["abstained"]
        ),
        "absent_total": sum(1 for r in results if r["category"] == "absent"),
        "answerable_cited_expected": sum(
            1 for r in results if r["category"] == "answerable" and r["cited_expected"]
        ),
        "answerable_total": sum(1 for r in results if r["category"] == "answerable"),
        "invalid_citations": sum(1 for r in results if r["error"] == "invalid_citation"),
        "errors": sum(1 for r in results if r["error"]),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="tests/fixtures/rag/cases.json")
    parser.add_argument("--corpus", default=None)
    parser.add_argument("--output", default="/tmp/graft-rag-results.json")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--chat-model", default=DEFAULT_CHAT_MODEL)
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--key-env", default="MISTRAL_API_KEY")
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.5)
    parser.add_argument("--pause", type=float, default=3.0,
                        help="seconds between cases, to stay under a free-tier rate limit")
    parser.add_argument("--max-retries", type=int, default=5,
                        help="SDK retries per call; a free tier answers 429 often")
    return parser.parse_args(argv)


if __name__ == "__main__":
    report = asyncio.run(run(parse_args()))
    print(json.dumps(report["summary"], indent=2))
