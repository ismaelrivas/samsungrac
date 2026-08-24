"""
Tests for demo_states.py
"""


from custom_components.climate_ip.demo_states import (
    exception_func,
    legit_func,
    massive_kill,
    segfault_func,
    slow_boundary_func,
    timeout_func,
)


def test_legit_func():
    # Legitimate test for legit_func.
    # If Mutmut changes a + b to a - b (5 - 3 = 2), the assertion will fail.
    assert legit_func(5, 3) == 8


def test_timeout_func():
    # Test for timeout_func.
    # Expects 0 under normal execution.
    # If Mutmut mutates x -= 1 to x += 1, this test will never finish, triggering a timeout.
    assert timeout_func() == 0


# Note: untested_func() is intentionally left without test coverage.


def test_massive_kill():
    # There are 60 True booleans. Mutmut will try to change each one to False (60 mutants).
    # Since we evaluate all(), any mutation to False will fail this assertion.
    assert all(massive_kill())


def test_segfault_func():
    assert segfault_func() == 0


def test_exception_func():
    # Normal execution: items[0]["value"] == 42, so result == 52.
    # If Mutmut mutates the index 0 -> 1, IndexError is raised (only 1 element).
    # If Mutmut mutates the key "value" -> "XXvalueXX", KeyError is raised.
    # Both cases crash the worker -> KILLED_RUNTIME_EXCEPTION.
    data = {"items": [{"value": 42}]}
    assert exception_func(data) == 52


def test_slow_boundary_func():
    # Normal execution: n=5, limit=10, sums 0..9 = 45.
    # If Mutmut mutates n * 2 to n ** 2, limit becomes 25 -> 300 iterations (slow but terminates).
    # The test still passes eventually but triggers the SLOW_KILLED performance tag.
    assert slow_boundary_func(5) == 45
