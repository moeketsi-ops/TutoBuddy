"""Load OCR'd past-paper text into Postgres as document_sections, tagged
(best-effort) to a Grade 8 Mathematics topic and embedded for retrieval by
app/tutor/rag.py's get_past_paper_excerpts().

    docker compose run --rm seed python -m seed.load_past_papers

Source: seed/past_papers/*.json, copied in from the founder's own OCR run
(ingestion/ocr_pdf.py in the standalone curriculum-engine repo — see project
doc tutobuddy-past-papers-ocr-pipeline.md). Each file is
{source_pdf, page_count, pages: [{page, text, tables}]} — one row per PAGE,
not per question: the OCR pass did not segment individual questions.

IMPORTANT — read tutobuddy-past-papers-ocr-pipeline.md before treating this
content as ground truth. OCR quality is good for prose but garbles maths
notation (fractions, exponents, multi-step arithmetic — e.g. one memo page
came out as "9.2 25 4.1.1 iad 3 oe" for what should have been a clean
fraction calculation). Every row loaded here is used downstream ONLY as
loose style/topic reference for generating a NEW practice question (see
app.tutor.prompts.practice_system) — never quoted to a learner as fact.

The topic tagging below is a simple keyword match, not verified page by
page — expect some mistagged/untagged pages. Untagged pages still work:
get_past_paper_excerpts() also filters by grade and ranks by embedding
similarity, so a mistagged page just falls back to being found (or not) by
similarity alone.

Idempotent by title: skips a JSON file whose document title has already
been loaded, so re-running after adding more papers to seed/past_papers/
only loads the new ones.

Requires seed/load_curriculum.py to have already run (needs the Grade 8 /
Mathematics rows it creates).
"""

import asyncio
import json
from pathlib import Path

from app.adapters.embeddings import embed
from app.db import ensure_schema, get_pool, vector_literal

HERE = Path(__file__).parent
PAPERS_DIR = HERE / "past_papers"

GRADE_NUMBER = 8
SUBJECT = "Mathematics"

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "Whole numbers": ["whole number", "hcf", "lcm", "common factor", "common multiple"],
    "Exponents": ["exponent", "power of", "index law", "laws of exponents"],
    "Construction of Geometric Figures": ["construct", "compass", "bisector"],
    "Geometry of 2D Shapes": ["quadrilateral", "polygon", "2d shape"],
    "Common Fractions": ["fraction"],
    "Decimal Fractions": ["decimal"],
    "Geometry of Straight Lines": ["straight line", "transversal", "parallel line"],
    "Geometry of 3D Objects": ["prism", "cylinder", "net of", "3d object"],
    "Numeric and Geometric Patterns": ["pattern", "sequence", "flow diagram"],
    "Functions and Relationships": ["input", "output", "table below"],
    "Algebraic Expressions": ["algebraic expression", "like terms", "coefficient", "simplify"],
    "Algebraic Equations": ["solve for", "equation"],
    "Graphs": ["cartesian", "plot the"],
    "Area and Perimeter": ["perimeter", "area of"],
    "Integers": ["integer"],
    "Transformation Geometry": ["reflection", "rotation", "translation", "enlarge"],
    "Surface Area and Volume": ["surface area", "volume"],
    "Collect, Organize and Summarize Data": ["tally", "survey", "collect data"],
    "Represent Data": ["bar graph", "pie chart", "histogram"],
    "Interpret, Analyse and Report Data": ["mean", "median", "mode", "range"],
    "Probability": ["probability", "outcome"],
}


def _guess_topic(text: str, topic_ids: dict[str, int]) -> int | None:
    lowered = text.lower()
    for name, keywords in TOPIC_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return topic_ids.get(name)
    return None


async def main() -> None:
    await ensure_schema()
    pool = await get_pool()
    async with pool.acquire() as conn:
        grade_id = await conn.fetchval(
            "SELECT id FROM grades WHERE grade_number = $1", GRADE_NUMBER
        )
        subject_id = await conn.fetchval(
            "SELECT id FROM subjects WHERE lower(name) = lower($1)", SUBJECT
        )
        if grade_id is None or subject_id is None:
            raise RuntimeError(
                "No Grade 8 / Mathematics rows found -- run "
                "`docker compose run --rm seed python -m seed.load_curriculum` first."
            )
        topic_rows = await conn.fetch(
            "SELECT id, name FROM topics WHERE grade_id = $1 AND subject_id = $2",
            grade_id, subject_id,
        )
        topic_ids = {r["name"]: r["id"] for r in topic_rows}

        n_docs = n_skipped = n_pages = n_tagged = 0
        for path in sorted(PAPERS_DIR.glob("*.json")):
            data = json.loads(path.read_text())
            title = path.stem.replace("-", " ").replace("_", " ")

            existing = await conn.fetchval(
                "SELECT id FROM documents WHERE title = $1", title
            )
            if existing:
                n_skipped += 1
                continue

            doc_id = await conn.fetchval(
                """
                INSERT INTO documents (title, document_type, file_path, grade_id, subject_id)
                VALUES ($1, 'past_paper', $2, $3, $4)
                RETURNING id
                """,
                title, data.get("source_pdf"), grade_id, subject_id,
            )
            n_docs += 1
            for page in data["pages"]:
                text = page["text"].strip()
                if not text:
                    continue
                topic_id = _guess_topic(text, topic_ids)
                if topic_id:
                    n_tagged += 1
                vec = vector_literal(await embed(text))
                await conn.execute(
                    """
                    INSERT INTO document_sections
                        (document_id, page_number, content, topic_id, embedding)
                    VALUES ($1, $2, $3, $4, $5::vector)
                    """,
                    doc_id, page["page"], text, topic_id, vec,
                )
                n_pages += 1

    print(
        f"Loaded {n_docs} past-paper documents ({n_skipped} already loaded, skipped), "
        f"{n_pages} OCR'd pages ({n_tagged} keyword-tagged to a topic, best-effort). "
        f"Reminder: OCR quality is unverified for maths notation -- see "
        f"tutobuddy-past-papers-ocr-pipeline.md. This content is used only as style/"
        f"topic reference for generated practice questions, never quoted as fact."
    )


if __name__ == "__main__":
    asyncio.run(main())
