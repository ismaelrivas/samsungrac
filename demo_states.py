"""
Test file designed to trigger different mutant states in Mutmut.
"""

import os

# 1. INVALID MUTANT / ERROR
# If Mutmut mutates this True to False, the condition triggers a RuntimeError at import time,
# causing Pytest to fail during test collection (Collection Error).
VALIDATION_FLAG = True
if not VALIDATION_FLAG:
    raise RuntimeError("Import failed due to mutation!")


# 2. LEGITIMATE KILLED
def legit_func(a, b):
    """Mutmut will mutate '+' to '-', causing the unit test assertion to fail."""
    return a + b


# 3. KILLED BY TIMEOUT (INFINITE LOOP)
def timeout_func():
    """
    The test calls this function. Mutmut will mutate `x -= 1` to `x += 1`.
    Since x will never be <= 0 when adding instead of subtracting, an infinite loop occurs,
    triggering the KILLED_RUNTIME_TIMEOUT mechanism in Phase 1 / 2.5.
    """
    x = 10
    while x > 0:
        x -= 1
    return x


# 4. UNTESTED
def untested_func():
    """
    This function is NOT called by any test file.
    Mutmut will mutate True to False or False to True, but since no test executes it,
    the resulting status will be UNTESTED.
    """
    flag = True
    return flag


# 5. 60 EXTRA LEGITIMATE KILLED
def massive_kill():
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
def segfault_func():
    """
    If Mutmut mutates x = 0 to x = 1 (or something making the condition true),
    Pytest will abruptly terminate via os._exit(3). The orchestrator detects the child
    process crash and classifies it as ERROR -> INVALID_MUTANT.
    """
    x = 0
    if x == 1:
        os._exit(3)
    return x


# 7. KILLED BY RUNTIME EXCEPTION
def exception_func(data):
    """
    Mutmut will mutate the integer 0 (index) to 1, or mutate the string key "value".
    Since the input dict has a specific structure, incorrect access raises TypeError
    or KeyError during test execution—crashing the worker before any assert runs.
    This exercises the KILLED_RUNTIME_EXCEPTION classification.
    """
    items = data.get("items", [])
    first = items[0]
    return first["value"] + 10


# 8. SLOW KILLED (Performance boundary)
def slow_boundary_func(n):
    """
    Under normal execution with n=5, runs 5 iterations (fast).
    Mutmut will mutate n * 2 to n ** 2 or n * 3, or mutate the `< limit`
    comparison. Some mutations cause the loop to run many more iterations
    (e.g., limit becomes 25 instead of 10), making the test slow enough
    to be flagged as SLOW_KILLED in Phase 2.5 but still terminates.
    """
    limit = n * 2
    total = 0
    i = 0
    while i < limit:
        total += i
        i += 1
    return total
