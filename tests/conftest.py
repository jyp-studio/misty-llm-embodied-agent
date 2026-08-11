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


@pytest.fixture(scope="session")
def portrait():
    """The fixture photograph, as OpenCV loads it. See fixtures/PROVENANCE.md."""
    cv2 = pytest.importorskip("cv2", reason=SKIP_REASON)
    path = FIXTURES / "frontal_face_portrait.jpg"
    image = cv2.imread(str(path))
    assert image is not None, f"could not decode {path}"
    return image
