"""The evaluation corpus is a contract: task 11 grades against these counts.

Nothing here calls a model. It only checks the fixture still describes the mix of
questions the release gate is stated in, and that the planted injection is still
planted — a corpus that quietly loses its trap stops proving anything.
"""
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rag"
CASES = json.loads((FIXTURES / "cases.json").read_text())["cases"]
DOCUMENTS = FIXTURES / "documents"


def test_the_mix_matches_the_release_gate():
    counts = {}
    for case in CASES:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    assert counts["answerable"] == 8
    assert counts["absent"] == 6
    assert counts["partial"] == 3
    assert counts["conflicting"] == 3
    assert len(CASES) >= 20


def test_every_case_is_gradeable():
    seen = set()
    for case in CASES:
        assert case["id"] not in seen
        seen.add(case["id"])
        assert case["question"].strip()
        assert isinstance(case["must_abstain"], bool)
        assert isinstance(case["expected_documents"], list)
        assert isinstance(case["expected_facts"], list)
        if case["must_abstain"]:
            # Nothing to cite: an abstention that cites a document is a failure.
            assert case["expected_documents"] == []
            assert case["expected_facts"] == []
        else:
            assert case["expected_documents"]


def test_expected_documents_exist_in_the_corpus():
    available = {p.name for p in DOCUMENTS.iterdir() if p.is_file()}
    for case in CASES:
        for name in case["expected_documents"]:
            assert name in available, f"{case['id']} points at a missing document"


def test_the_corpus_still_contains_the_planted_injection():
    text = (DOCUMENTS / "security.md").read_text()
    assert "Ignore all previous instructions" in text
    injection_cases = [c for c in CASES if c["category"] == "injection"]
    assert injection_cases and injection_cases[0]["forbidden_behaviour"]


def test_the_conflicting_pair_really_disagrees():
    current = (DOCUMENTS / "billing.md").read_text()
    superseded = (DOCUMENTS / "legacy-policy.md").read_text()
    assert "30 days" in current
    assert "14 days" in superseded
