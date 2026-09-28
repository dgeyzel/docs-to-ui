from app.prompts.diff import examples_text, line_diff


def test_line_diffs_mark_added_removed_and_unchanged_lines() -> None:
    diff = line_diff("one\ntwo\nthree", "one\n2\nthree")

    assert [(line.kind, line.text) for line in diff] == [
        ("@", "@@ -1,3 +1,3 @@"),
        (" ", "one"),
        ("-", "two"),
        ("+", "2"),
        (" ", "three"),
    ]


def test_identical_texts_have_no_diff() -> None:
    assert line_diff("same", "same") == []


def test_examples_are_rendered_as_stable_json() -> None:
    assert (
        examples_text([{"b": 1, "a": 2}]) == '[\n  {\n    "a": 2,\n    "b": 1\n  }\n]'
    )
