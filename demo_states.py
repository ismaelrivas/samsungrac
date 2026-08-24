from __future__ import annotations

import os
from typing import Any

# 1. INVALID MUTANT / ERROR
# If Mutmut mutates this True to False, the condition triggers a RuntimeError at import time,
# causing Pytest to fail during test collection (Collection Error).
VALIDATION_FLAG: bool = True
if not VALIDATION_FLAG:
    raise RuntimeError("Import failed due to mutation!")


# 2. LEGITIMATE KILLED
def legit_func(a: int, b: int) -> int:
    """Mutmut will mutate '+' to '-', causing the unit test assertion to fail."""
    return a + b


# 3. KILLED BY TIMEOUT (INFINITE LOOP)
def timeout_func() -> int:
    """
    The test calls this function. Mutmut will mutate `x -= 1` to `x += 1`.
    Since x will never be <= 0 when adding instead of subtracting, an infinite loop occurs,
    triggering the KILLED_RUNTIME_TIMEOUT mechanism in Phase 1 / 2.5.
    """
    x: int = 10
    while x > 0:
        x -= 1
    return x


# 4. UNTESTED
def untested_func() -> bool:
    """
    This function is NOT called by any test file.
    Mutmut will mutate True to False or False to True, but since no test executes it,
    the resulting status will be UNTESTED.
    """
    flag: bool = True
    return flag


# 5. 60 EXTRA LEGITIMATE KILLED
def massive_kill() -> list[bool]:
    """Generates 60 mutations (one for each True) that will be KILLED."""
    return [
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
    ]


# 6. INVALID MUTANT (WORKER CRASH)
def segfault_func() -> int:
    """
    If Mutmut mutates x = 0 to x = 1 (or something making the condition true),
    Pytest will abruptly terminate via os._exit(3). The orchestrator detects the child
    process crash and classifies it as ERROR -> INVALID_MUTANT.
    """
    x: int = 0
    if x == 1:
        os._exit(3)
    return x


# 7. KILLED BY RUNTIME EXCEPTION
def exception_func(data: dict[str, Any]) -> int:
    """
    Mutmut will mutate the integer 0 (index) to 1, or mutate the string key "value".
    Since the input dict has a specific structure, incorrect access raises TypeError
    or KeyError during test execution—crashing the worker before any assert runs.
    This exercises the KILLED_RUNTIME_EXCEPTION classification.
    """
    items: list[dict[str, Any]] = data.get("items", [])
    first: dict[str, Any] = items[0]
    result: int = first["value"] + 10
    return result


# 8. SLOW KILLED (Performance boundary)
def slow_boundary_func(n: int) -> int:
    """
    Under normal execution with n=5, runs 5 iterations (fast).
    Mutmut will mutate n * 2 to n ** 2 or n * 3, or mutate the `< limit`
    comparison. Some mutations cause the loop to run many more iterations
    (e.g., limit becomes 25 instead of 10), making the test slow enough
    to be flagged as SLOW_KILLED in Phase 2.5 but still terminates.
    """
    limit: int = n * 2
    total: int = 0
    i: int = 0
    while i < limit:
        total += i
        i += 1
    return total
