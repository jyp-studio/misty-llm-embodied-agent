"""The care card exposes the same Skill acceptance run as the tests."""

import json

from misty_agent.demo import answer


def test_care_card_runs_calming_support_and_shows_loaded_skill_and_actual_tools():
    payload = json.loads(answer("GET", "/scenarios").body)
    assert len(payload) == 3
    care = next(case for case in payload if case["name"] == "crying-care")
    assert any(item["key"] == "calming-support" for item in care["fixtures"])
    response = answer("POST", "/scenarios/crying-care/run", b'{"fixture":"calming-support"}')
    assert response.status == 200
    run = json.loads(response.body)
    assert run["execution"]["provenance"]["input_kind"] == "text"
    assert run["execution"]["provenance"]["kind"] == "scripted_run"
    beats = run["execution"]["flow"]
    assert next(beat for beat in beats if beat["kind"] == "cue")["headline"] == "明確互動請求"
    assert any("請協助我冷靜" in beat["headline"] for beat in beats if beat["kind"] == "input")
    kinds = [beat["kind"] for beat in beats]
    assert kinds.index("skills_available") < kinds.index("skill_activation")
    offered = next(beat for beat in beats if beat["kind"] == "skills_available")
    assert "supportive-interaction" in offered["detail"]
    assert "Ask what kind of company" not in offered["detail"]
    assert next(beat for beat in beats if beat["kind"] == "skill_activation")["headline"] == "supportive-interaction"
    assert any(beat["kind"] == "skill_resource" for beat in beats)
    heard = next(beat for beat in beats if beat["kind"] == "listening")
    assert heard["headline"] == "安靜陪我就好"
    assert "heard" in heard["detail"]
    assert any("安靜陪我" in beat["headline"] for beat in beats)
    moments = run["episodes"][0]["storyboard"]["moments"]
    assert any(moment["active_skills"] == ["supportive-interaction"] for moment in moments)
    assert moments[-1]["active_skills"] == []
    assert run["episodes"][0]["outcome"]["outcome"] == "done"
