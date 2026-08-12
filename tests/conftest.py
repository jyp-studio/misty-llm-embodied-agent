"""Fixtures shared by the perception tests.

Both perception test files need the same photograph and the same explanation
of why they skip. The skip message is the important one: a bare ``python3`` on
a developer machine has neither mediapipe nor opencv, and the rest of the
suite passes under it regardless, so a wrong interpreter looks exactly like a
healthy one. The message has to name the fix wherever it surfaces — see
AGENTS.md.
"""

from __future__ import annotations

import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

SKIP_REASON = (
    "mediapipe/opencv not importable — run under the project venv "
    "(.venv/bin/python), not a bare python3"
)


def _load(filename: str):
    cv2 = pytest.importorskip("cv2", reason=SKIP_REASON)
    path = FIXTURES / filename
    image = cv2.imread(str(path))
    assert image is not None, f"could not decode {path}"
    return image


@pytest.fixture(scope="session")
def portrait():
    """Someone looking straight at the camera. See fixtures/PROVENANCE.md."""
    return _load("frontal_face_portrait.jpg")


@pytest.fixture(scope="session")
def turned_portrait():
    """Someone with their head turned away, face still fully visible.

    The negative control for the gaze test. Without it, an ``is_looking`` that
    returned ``True`` unconditionally would pass every test in the suite.
    """
    return _load("turned_head_portrait.jpg")
