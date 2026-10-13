from dataclasses import replace

from building_with_rag.ingest import BNS, IPC, parse_sections

BNS3 = replace(BNS, total_sections=3, body_marker=None)
IPC3 = replace(IPC, total_sections=3)


def test_inline_headings_and_chapter():
    lines = [
        (1, "CHAPTER I"),
        (1, "PRELIMINARY"),
        (1, "1. Short title.—This Act may be called X."),
        (1, "It extends to India."),
        (2, "2. Definitions.—In this Code,"),
        (2, "(a) foo means bar."),
        (2, "3. Punishment.—Whoever does it shall be punished."),
    ]
    sections = parse_sections(lines, IPC3)
    assert [s.number for s in sections] == [1, 2, 3]
    assert sections[0].chapter == "I"
    assert sections[0].chapter_title == "PRELIMINARY"
    assert sections[0].heading == "Short title"
    assert "extends to India" in sections[0].text
    assert "(a) foo means bar." in sections[1].text
    assert sections[1].lines[0][0] == 2


def test_inline_margin_copy_and_wrapped_heading():
    lines = [
        (1, "CHAPTER I"),
        (1, "INTRODUCTION"),
        (1, "Title and extent."),
        (1, "1. Title and extent.--This Act applies."),
        (1, "Punishment of offences committed within India."),
        (1, "2. Punishment of offences committed"),
        (1, "within India.--Every person shall be liable."),
    ]
    sections = parse_sections(lines, IPC3)
    assert [s.heading for s in sections] == [
        "Title and extent",
        "Punishment of offences committed within India",
    ]
    assert sections[0].text == "This Act applies."
    assert sections[1].text == "Every person shall be liable."


def test_heading_on_line_before_number():
    lines = [
        (1, "CHAPTER I"),
        (1, "PRELIMINARY"),
        (1, "Short title."),
        (1, "1. (1) This Act may be called X."),
        (1, "Definitions."),
        (1, "2. In this Sanhita, words mean what follows."),
        (2, "Punishment."),
        (2, "3. Whoever does it shall be punished."),
    ]
    sections = parse_sections(lines, BNS3)
    assert [s.heading for s in sections] == ["Short title", "Definitions", "Punishment"]
    assert "Definitions" not in sections[0].text
    assert sections[0].text == "(1) This Act may be called X."


def test_index_before_body_marker_is_skipped():
    index = [
        (1, "CHAPTER I"),
        (1, "PRELIMINARY"),
        (1, "1. Short title, commencement and application."),
        (1, "2. Definitions."),
        (1, "3. Punishment."),
    ]
    body = [
        (3, "CHAPTER I"),
        (3, "PRELIMINARY"),
        (3, "Short title"),
        (3, "1. (1) This Act may be called X."),
        (3, "Definitions."),
        (3, "2. In this Sanhita, words mean what follows."),
        (3, "Punishment."),
        (3, "3. Whoever does it shall be punished."),
    ]
    cfg = replace(BNS3, body_marker=r"^1\. \(1\) This Act may be called")
    sections = parse_sections(index + body, cfg)
    assert [s.number for s in sections] == [1, 2, 3]
    assert sections[0].heading == "Short title"
    assert sections[0].text == "(1) This Act may be called X."
