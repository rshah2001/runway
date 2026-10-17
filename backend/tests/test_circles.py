"""Named circles: membership rules, and that a circle never carries anything about money."""

import json

import pytest
from fastapi.testclient import TestClient

from app import circles, main
from tests.test_privacy_alerts import auth_off  # noqa: F401 (fixture, used by name)

client = TestClient(main.app)


class Members:
    """In-memory circle_members + circles for the rule functions."""

    def __init__(self, states: dict[str, str], creator: str = "sam"):
        self.states, self.creator = dict(states), creator

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(circles, "_state", lambda conn, cid, slug: self.states.get(slug))
        monkeypatch.setattr(
            circles, "_set", lambda conn, cid, slug, state, invited_by=None: self.states.__setitem__(slug, state)
        )

    def execute(self, sql, params=None):  # only remove() reads created_by
        creator = self.creator

        class R:
            def fetchone(self):
                return {"created_by": creator}

        return R()


def test_only_members_invite_and_invites_are_answered_by_the_invited(monkeypatch) -> None:
    m = Members({"sam": "active", "maya": "active"})
    m.install(monkeypatch)
    with pytest.raises(circles.CircleRefused):
        circles.invite(m, "jordan", "c", "emma")  # not a member
    circles.invite(m, "maya", "c", "emma")
    assert m.states["emma"] == "invited"
    with pytest.raises(circles.CircleRefused):
        circles.answer(m, "maya", "c", True)  # maya has no invitation
    circles.answer(m, "emma", "c", True)
    assert m.states["emma"] == "active"


def test_only_the_creator_removes_and_nobody_removes_themselves(monkeypatch) -> None:
    m = Members({"sam": "active", "maya": "active", "jordan": "active"})
    m.install(monkeypatch)
    with pytest.raises(circles.CircleRefused):
        circles.remove(m, "maya", "c", "jordan")
    with pytest.raises(circles.CircleRefused):
        circles.remove(m, "sam", "c", "sam")
    circles.remove(m, "sam", "c", "jordan")
    assert m.states["jordan"] == "removed"


def test_anyone_can_leave(monkeypatch) -> None:
    m = Members({"sam": "active", "maya": "active"})
    m.install(monkeypatch)
    circles.leave(m, "maya", "c")
    assert m.states["maya"] == "left"


@pytest.mark.usefixtures("auth_off")
def test_you_see_your_circles_and_invitations_and_nothing_about_money() -> None:
    maya = client.get("/circles?persona=maya").json()
    assert {c["name"] for c in maya} == {"Family", "Weekend crew"}
    jordan = {c["name"]: c for c in client.get("/circles?persona=jordan").json()}
    assert jordan["Weekend crew"]["my_state"] == "invited" and jordan["Family"]["my_state"] == "active"
    text = json.dumps(maya).lower()
    assert "balance" not in text and "limit" not in text and "$" not in text
