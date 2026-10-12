# Past papers (OCR output for the app)

OCR'd Mathematics past papers, one JSON per PDF, laid out as `grade_XX/YYYY/<name>.json`.
Do not edit by hand. The originals, the naming convention and `manifest.csv` live in the
TutoBuddy data folder (`data/raw/past_papers/README.md`), and
`ingestion/sync_past_papers.py` copies new files here.

`seed/load_past_papers.py` reads the grade from the folder and the document type from the
file name (`_memo` gives `marking_memo`, `_qp` and `_qp-memo` give `past_paper`):

    docker compose run --rm seed python -m seed.load_past_papers

OCR garbles maths notation. The app uses this text only as style and topic reference for
new practice questions, never as an answer shown to a learner.
