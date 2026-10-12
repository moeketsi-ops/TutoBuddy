"""Load OCR'd past-paper text into Postgres as document_sections, tagged
(best-effort) to a Mathematics topic of the paper's grade and embedded for retrieval by
app/tutor/rag.py's get_past_paper_excerpts().

    docker compose run --rm seed python -m seed.load_past_papers

Source: seed/past_papers/grade_XX/YYYY/<province>_<session>_<paper>_<kind>.json,
copied in by ingestion/sync_past_papers.py in the TutoBuddy data repo (naming
convention and manifest.csv: data/raw/past_papers/README.md there). The grade
comes from the folder, the year from the year folder, and the document type
from the kind (memo -> marking_memo; qp and qp-memo -> past_paper). Each file is
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
been loaded, so re-running after adding more papers only loads the new ones.
Rows loaded before the grade-folder layout (Oct 2026) are renamed in place via
LEGACY_TITLES, so they are not loaded twice.

Requires seed/load_curriculum.py to have already run (needs the grade /
Mathematics rows it creates). A grade folder whose curriculum isn't loaded is
skipped with a warning.

The keyword table below is Grade 8 only. Other grades fall back to matching a
topic's own name in the page text, which is rougher.
"""

import asyncio
import json
from pathlib import Path

from app.adapters.embeddings import embed
from app.db import ensure_schema, get_pool, vector_literal

HERE = Path(__file__).parent
PAPERS_DIR = HERE / "past_papers"

SUBJECT = "Mathematics"

# Old flat-layout title -> new path stem, so a DB loaded before Oct 2026 keeps
# its rows (and their embeddings) instead of loading the same papers twice.
LEGACY_TITLES: dict[str, str] = {
    "EC ORT Maths Grade 8 June 2024 QP and Memo": "grade_08/2024/ec-ort_jun-exam_p1_qp-memo",
    "FS Maths Grade 8 MOCK November 2025 P1 and Memo": "grade_08/2025/fs_nov-mock_p1_qp-memo",
    "FS Maths Grade 8 MOCK November 2025 P2 and Memo": "grade_08/2025/fs_nov-mock_p2_qp-memo",
    "GP Maths Grade 8 Revision TEST Term 1 2025 and Memo": "grade_08/2025/gp_t1-revision_p1_qp-memo",
    "GR 8 MATH MARCH CONTROLLED TEST 1": "grade_08/2024/ec_mar-test_p1_qp",
    "GR 8 MATH MARCH CONTROLLED TEST MEMORANDUM 1": "grade_08/2024/ec_mar-test_p1_memo",
    "KZN Maths Grade 8 November 2023 P1 and Memo": "grade_08/2023/kzn_nov-exam_p1_qp-memo",
    "KZN Maths Grade 8 November 2023 P2 and Memo": "grade_08/2023/kzn_nov-exam_p2_qp-memo",
    "LP VW Maths Grade 8 March 2024 QP and Memo": "grade_08/2024/lp-vw_mar-test_p1_qp-memo",
    "Maths Grade 8 June 2025 QP and Memo": "grade_08/2025/unk_jun-exam_p1_qp-memo",
}

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


def _guess_topic(text: str, topic_ids: dict[str, int], grade: int) -> int | None:
    lowered = text.lower()
    if grade == 8:
        for name, keywords in TOPIC_KEYWORDS.items():
            if any(kw in lowered for kw in keywords):
                return topic_ids.get(name)
        return None
    for name, tid in topic_ids.items():
        if name.lower() in lowered:
            return tid
    return None


def paper_meta(path: Path) -> dict | None:
    """grade_08/2024/ec_mar-test_p1_qp.json -> grade, year, kind, title."""
    rel = path.relative_to(PAPERS_DIR)
    grade = int(rel.parts[0].removeprefix("grade_"))
    year = int(rel.parts[1])
    kind = path.stem.rsplit("_", 1)[-1]
    if kind in ("ab", "erratum"):
        return None  # answer books and errata are catalogued, not loaded
    if kind not in ("qp", "memo", "qp-memo"):
        raise ValueError(f"{rel}: file name must end in _qp, _memo or _qp-memo")
    return {
        "grade": grade,
        "year": year,
        "document_type": "marking_memo" if kind == "memo" else "past_paper",
        "title": rel.with_suffix("").as_posix(),
    }


async def _grade_context(conn, grade: int):
    grade_id = await conn.fetchval("SELECT id FROM grades WHERE grade_number = $1", grade)
    if grade_id is None:
        return None
    # One Mathematics subject row exists per phase (Senior Phase, FET Phase),
    # so pick the one in this grade's phase.
    subject_id = await conn.fetchval(
        "SELECT s.id FROM subjects s JOIN grades g ON g.phase_id = s.phase_id "
        "WHERE g.id = $1 AND lower(s.name) = lower($2)",
        grade_id, SUBJECT,
    )
    if subject_id is None:
        return None
    rows = await conn.fetch(
        "SELECT id, name FROM topics WHERE grade_id = $1 AND subject_id = $2",
        grade_id, subject_id,
    )
    return grade_id, subject_id, {r["name"]: r["id"] for r in rows}


async def main() -> None:
    await ensure_schema()
    pool = await get_pool()
    async with pool.acquire() as conn:
        for old, new in LEGACY_TITLES.items():
            await conn.execute(
                "UPDATE documents SET title = $2, document_type = $3, year = $4, file_path = $5 "
                "WHERE title = $1 AND NOT EXISTS (SELECT 1 FROM documents WHERE title = $2)",
                old, new,
                "marking_memo" if new.endswith("_memo") else "past_paper",
                int(new.split("/")[1]), new + ".pdf",
            )

        contexts: dict[int, tuple | None] = {}
        n_docs = n_skipped = n_pages = n_tagged = 0
        for path in sorted(PAPERS_DIR.glob("grade_*/[0-9][0-9][0-9][0-9]/*.json")):
            meta = paper_meta(path)
            if meta is None:
                continue
            g = meta["grade"]
            if g not in contexts:
                contexts[g] = await _grade_context(conn, g)
                if contexts[g] is None:
                    print(f"WARN Grade {g} / {SUBJECT} curriculum not loaded, skipping its papers")
            if contexts[g] is None:
                continue
            grade_id, subject_id, topic_ids = contexts[g]

            existing = await conn.fetchval(
                "SELECT id FROM documents WHERE title = $1", meta["title"]
            )
            if existing:
                n_skipped += 1
                continue

            data = json.loads(path.read_text(encoding="utf-8"))
            doc_id = await conn.fetchval(
                """
                INSERT INTO documents (title, document_type, year, file_path, grade_id, subject_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                meta["title"], meta["document_type"], meta["year"],
                data.get("source_pdf"), grade_id, subject_id,
            )
            n_docs += 1
            for page in data["pages"]:
                text = page["text"].strip()
                if not text:
                    continue
                topic_id = _guess_topic(text, topic_ids, g)
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
