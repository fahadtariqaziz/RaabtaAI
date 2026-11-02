"""Step 2.7 — citation schema and quotes."""

import uuid

from app.kb.citations import QUOTE_MAX, Citation, make_quote
from app.kb.search import SearchHit, expand, pack


def test_citation_label_and_quote() -> None:
    doc = uuid.uuid4()
    c = Citation(
        document_id=doc,
        title="ABC Prospectus",
        page=3,
        chunk_id=uuid.uuid4(),
        quote="Classes run Monday to Friday",
    )
    assert c.label() == "ABC Prospectus, p. 3"
    assert Citation(document_id=doc, title="Fee sheet").label() == "Fee sheet"
    assert Citation.model_validate_json(c.model_dump_json()) == c


def test_make_quote_prefers_matching_sentence_and_trims() -> None:
    text = "Welcome to ABC. Classes run Monday to Friday, 07:45 to 13:30. Uniform is grey."
    assert make_quote(text, ["monday"]) == "Classes run Monday to Friday, 07:45 to 13:30."
    assert make_quote(text) == text
    long = "word " * 200
    assert len(make_quote(long)) <= QUOTE_MAX


def test_search_hit_citation_and_packing() -> None:
    def hit(tokens: int) -> SearchHit:
        return SearchHit(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            title="T",
            page=2,
            heading="H",
            text="fee " * tokens,
            tokens=tokens,
        )

    h = hit(10)
    cit = h.citation(["fee"])
    assert (cit.chunk_id, cit.page, cit.title) == (h.chunk_id, 2, "T")
    kept, used = pack([hit(900), hit(900), hit(900)], budget=2000)
    assert len(kept) == 2 and used == 1800
    kept, used = pack([hit(5000)], budget=2000)
    assert len(kept) == 1 and used == 2000 and len(kept[0].text) < len("fee " * 5000)


def test_query_expansion_roman_urdu_and_urdu() -> None:
    assert {"admission", "fee"} <= set(expand("dakhla fees kitni hai"))
    assert {"admission", "fee"} <= set(expand("داخلہ فیس کتنی ہے؟"))
    assert "kitna" not in expand("fees kitni hai")  # stopword after normalization
