"""
Tests for demo_states.py
"""
import pytest
from custom_components.climate_ip.demo_states import legit_func, timeout_func

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

from custom_components.climate_ip.demo_states import massive_kill, segfault_func

def test_massive_kill():
    # There are 60 True booleans. Mutmut will try to change each one to False (60 mutants).
    # Since we evaluate all(), any mutation to False will fail this assertion.
    assert all(massive_kill())

def test_segfault_func():
    assert segfault_func() == 0
