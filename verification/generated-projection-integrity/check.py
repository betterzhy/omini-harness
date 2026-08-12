"""Executable fixture proving generated projection checks remain a verification concern."""


def check(expected: bytes, actual: bytes) -> bool:
    return expected == actual
