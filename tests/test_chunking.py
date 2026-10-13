from building_with_rag import mongodb_schema as schema
from building_with_rag.chunking import embedding_input, split_text


def test_short_text_is_one_chunk():
    assert split_text("Short section.") == ["Short section."]


def test_long_text_splits_with_overlap_and_no_loss():
    text = " ".join(f"Sentence number {i} is here." for i in range(400))
    chunks = split_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= schema.CHUNK_SIZE for c in chunks)
    assert chunks[0].startswith("Sentence number 0")
    assert chunks[-1].endswith("Sentence number 399 is here.")
    # consecutive chunks share some text (overlap)
    assert chunks[1][:40] in chunks[0]


def test_split_is_deterministic():
    text = "word " * 2000
    assert split_text(text) == split_text(text)


def test_ids_are_deterministic():
    assert schema.chunk_id("bns:103", 2) == "bns:103#c2"
    assert schema.embedding_id("bns:103#c2") == "bns:103#c2@voyage-3.5@1024"
    assert schema.source_id("ipc") == "source:ipc"


def test_embedding_input_prefix():
    section = {"section_id": "ipc:354a", "act_label": "Indian Penal Code, 1860", "heading": "X"}
    out = embedding_input(section, "body")
    assert out == "Indian Penal Code, 1860, Section 354A: X\n\nbody"


def test_vector_index_definition_uses_fields_array():
    definition = schema.vector_index_definition()
    assert "mappings" not in definition
    vector = definition["fields"][0]
    assert vector == {
        "type": "vector",
        "path": "vector",
        "numDimensions": 1024,
        "similarity": "cosine",
    }
    assert [f["path"] for f in definition["fields"][1:]] == [
        "act",
        "chapter",
        "status",
        "access_level",
    ]
