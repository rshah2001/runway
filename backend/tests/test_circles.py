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
        self.invited_by: dict[str, str] = {}
        self.notes: list[tuple[str, str, str]] = []  # (for whom, kind, by whom)

        def _set(conn, cid, slug, state, invited_by=None):
            self.states[slug] = state
            if invited_by:
                self.invited_by[slug] = invited_by

        monkeypatch.setattr(circles, "_set", _set)
        monkeypatch.setattr(
            circles.inbox, "add", lambda conn, slug, kind, cid, actor: self.notes.append((slug, kind, actor))
        )
        monkeypatch.setattr(
            circles.inbox, "sent_recently", lambda conn, actor: sum(1 for n in self.notes if n[2] == actor)
        )

    def execute(self, sql, params=None):  # remove() reads created_by; leave()/remove() revoke links
        creator = self.creator
        if "circle_invites" in sql:
            self.revoked = getattr(self, "revoked", []) + [params]
        inviter = self.invited_by.get(params[1]) if params and len(params) > 1 else None

        class R:
            def fetchone(self):
                return {"created_by": creator, "invited_by": inviter}

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


def test_a_removed_or_declined_person_can_only_be_asked_again_by_the_creator(monkeypatch) -> None:
    m = Members({"sam": "active", "maya": "active", "jordan": "removed", "emma": "declined"})
    m.install(monkeypatch)
    for slug in ("jordan", "emma"):
        with pytest.raises(circles.CircleRefused):
            circles.invite(m, "maya", "c", slug)  # a member can't undo the creator's removal or nag a "no"
    circles.invite(m, "sam", "c", "jordan")  # the creator can
    assert m.states["jordan"] == "invited"


def test_a_creator_who_left_cannot_remove_people(monkeypatch) -> None:
    m = Members({"sam": "left", "maya": "active"})
    m.install(monkeypatch)
    with pytest.raises(circles.CircleRefused):
        circles.remove(m, "sam", "c", "maya")


class Links(Members):
    """Members plus one invite link that's valid unless `expired`."""

    def __init__(self, states, *, expired: bool = False):
        super().__init__(states)
        self.expired = expired

    def install(self, monkeypatch) -> None:
        super().install(monkeypatch)
        info = None if self.expired else {"circle_id": "c", "name": "Family", "made_by": "Sam"}
        monkeypatch.setattr(circles, "link_info", lambda conn, token: info)


def test_an_invite_link_joins_you_to_the_circle(monkeypatch) -> None:
    m = Links({"sam": "active"})
    m.install(monkeypatch)
    assert circles.join_by_link(m, "alex", "tok") == "c" and m.states["alex"] == "active"


def test_an_expired_or_turned_off_link_joins_nobody(monkeypatch) -> None:
    m = Links({"sam": "active"}, expired=True)
    m.install(monkeypatch)
    with pytest.raises(circles.CircleRefused):
        circles.join_by_link(m, "alex", "tok")


def test_someone_the_creator_removed_cannot_come_back_through_a_link(monkeypatch) -> None:
    m = Links({"sam": "active", "jordan": "removed"})
    m.install(monkeypatch)
    with pytest.raises(circles.CircleRefused):
        circles.join_by_link(m, "jordan", "tok")


def test_only_members_can_make_a_link(monkeypatch) -> None:
    m = Members({"sam": "active"})
    m.install(monkeypatch)
    with pytest.raises(circles.CircleRefused):
        circles.make_link(m, "jordan", "c")


def test_leaving_or_being_removed_turns_off_your_links(monkeypatch) -> None:
    m = Members({"sam": "active", "maya": "active", "jordan": "active"})
    m.install(monkeypatch)
    circles.leave(m, "maya", "c")
    circles.remove(m, "sam", "c", "jordan")
    assert m.revoked == [("c", "maya"), ("c", "jordan")]


def test_being_added_notifies_you_and_your_answer_notifies_them(monkeypatch) -> None:
    m = Members({"sam": "active", "maya": "active"})
    m.install(monkeypatch)
    circles.invite(m, "maya", "c", "emma")
    circles.answer(m, "emma", "c", accept=True)
    assert m.notes == [("emma", "circle_invite", "maya"), ("maya", "circle_joined", "emma")]


def test_a_no_is_also_told_back(monkeypatch) -> None:
    m = Members({"sam": "active"})
    m.install(monkeypatch)
    circles.invite(m, "sam", "c", "jordan")
    circles.answer(m, "jordan", "c", accept=False)
    assert m.notes[-1] == ("sam", "circle_declined", "jordan")


def test_joining_by_link_tells_the_creator(monkeypatch) -> None:
    m = Links({"sam": "active"})
    m.install(monkeypatch)
    circles.join_by_link(m, "alex", "tok")
    assert m.notes == [("sam", "circle_joined", "alex")]


def test_invitations_are_capped_per_hour(monkeypatch) -> None:
    m = Members({"maya": "active"})
    m.install(monkeypatch)
    for i in range(circles.INVITES_PER_HOUR):
        circles.invite(m, "maya", "c", f"p{i}")
    with pytest.raises(circles.CircleRefused):
        circles.invite(m, "maya", "c", "one-more")


def test_someone_who_declined_is_not_pinged_again(monkeypatch) -> None:
    m = Members({"sam": "active", "jordan": "declined"})
    m.install(monkeypatch)
    circles.invite(m, "sam", "c", "jordan")  # the creator may ask again…
    assert m.states["jordan"] == "invited" and m.notes == []  # …but no pop-up or push
