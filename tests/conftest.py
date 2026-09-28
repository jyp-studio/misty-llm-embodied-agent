"""Fixtures shared across the test suite.

Both perception test files need the same photograph and the same explanation
of why they skip. The skip message is the important one: a bare ``python3`` on
a developer machine has neither mediapipe nor opencv, and the rest of the
suite passes under it regardless, so a wrong interpreter looks exactly like a
healthy one. The message has to name the fix wherever it surfaces — see
AGENTS.md.

The other shared concern is configuration isolation: ``Settings`` reads
``.env`` and every ``MISTY_*`` variable in the environment, so a developer who
has either would see tests that assert on the defaults go red for reasons that
have nothing to do with the code. ``_settings_read_no_ambient_config`` cuts
both channels for the whole suite.
"""

from __future__ import annotations

import os
import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def _settings_read_no_ambient_config(monkeypatch):
    """Make ``Settings()`` mean "the declared defaults", in every test.

    Two channels feed a ``Settings`` instance from outside the process, and
    both have to be cut or the assertions on default values below become
    assertions about whoever happens to be running them:

    * the ``MISTY_*`` environment variables, cleared here;
    * ``.env``, which ``model_config`` names and which is gitignored — so it is
      exactly the file a reviewer would have and CI would not.

    A test that wants either back can still have it: ``monkeypatch.setenv``
    inside the test body runs after this fixture, which is how
    ``test_env_overrides`` still exercises the environment-variable path.
    """
    from misty_agent.config import Settings

    for name in [k for k in os.environ if k.startswith("MISTY_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)

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
