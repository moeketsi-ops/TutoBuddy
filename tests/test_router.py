"""Router tier: Jev response parsing + acceptance policy (no network)."""

from app.adapters.router import accept, jev_request, parse_jev_response

DOCUMENTED_SHAPE = {
    "model": "jev-1.13.0",
    "answers": {"intent": {"type": "choice", "choice": "quiz",
                           "probabilities": {"homework": 0.1, "quiz": 0.85, "smalltalk": 0.03, "admin": 0.02},
                           "confidence": 0.82}},
    "usage": {"input_tokens": 57, "output_tokens": 0},
}
FLAT_SHAPE = {"intent": {"type": "choice", "probabilities": {"homework": 0.7, "quiz": 0.3}, "confidence": 0.4}}


def test_parses_documented_shape():
    r = parse_jev_response(DOCUMENTED_SHAPE)
    assert (r["label"], r["confidence"], r["input_tokens"]) == ("quiz", 0.82, 57)


def test_parses_flat_shape_and_derives_label_from_probabilities():
    r = parse_jev_response(FLAT_SHAPE)
    assert r["label"] == "homework" and r["input_tokens"] == 0


def test_low_confidence_or_unknown_label_is_rejected():
    assert accept(parse_jev_response(DOCUMENTED_SHAPE), 0.6)
    assert not accept(parse_jev_response(FLAT_SHAPE), 0.6)          # 0.4 < 0.6
    assert not accept({"label": "banter", "confidence": 0.99}, 0.6)  # not one of INTENTS


def test_request_uses_all_four_intents():
    q = jev_request("quiz me")["questions"]["intent"]
    assert q["type"] == "choice" and set(q["criteria"]) == {"homework", "quiz", "smalltalk", "admin"}
