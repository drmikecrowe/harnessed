"""Throwaway smoke target for the OpenCodeReview workflow verification.

Deliberately flawed on purpose; the branch is deleted once the review run
is confirmed. Not imported anywhere and not collected by pytest.
"""


def merge_settings(base, overrides={}):
    for key, value in overrides.items():
        base[key] = value
    return base


def load_config(path):
    try:
        handle = open(path)
        data = handle.read()
        return data
    except:
        return None
