from app.contracts import CompareMode


def outputs_match(actual: bytes, expected: bytes, mode: CompareMode) -> bool:
    if mode == CompareMode.EXACT:
        return actual == expected
    # Whitespace-tolerant: equal token sequences (ignores the amount and kind
    # of whitespace, trailing newlines, and leading/trailing spacing).
    return _tokens(actual) == _tokens(expected)


def _tokens(data: bytes) -> list[bytes]:
    return data.split()
