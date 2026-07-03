"""Throwaway test to verify branch protection actually blocks a merge when
CI fails. Not meant to be merged — delete this file once the demo PR has
served its purpose.
"""


def test_ci_demo_intentional_failure():
    assert 1 == 2, "intentional failure to verify CI blocks the merge"
