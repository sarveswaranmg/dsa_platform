from app.compare import outputs_match
from app.contracts import CompareMode


def test_exact_matches_identical() -> None:
    assert outputs_match(b"6\n", b"6\n", CompareMode.EXACT)


def test_exact_rejects_trailing_whitespace() -> None:
    assert not outputs_match(b"6\n", b"6\n\n", CompareMode.EXACT)
    assert not outputs_match(b"6 \n", b"6\n", CompareMode.EXACT)


def test_whitespace_tolerates_trailing_newline_and_spacing() -> None:
    assert outputs_match(b"6\n", b"6\n\n", CompareMode.WHITESPACE)
    assert outputs_match(b"1 2 3\n", b"1  2   3\n", CompareMode.WHITESPACE)
    assert outputs_match(b"1\n2\n3\n", b"1 2 3", CompareMode.WHITESPACE)


def test_whitespace_still_rejects_different_tokens() -> None:
    assert not outputs_match(b"1 2 3\n", b"1 2 4\n", CompareMode.WHITESPACE)
    assert not outputs_match(b"6\n", b"7\n", CompareMode.WHITESPACE)
