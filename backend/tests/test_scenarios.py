"""Time Machine: your own forecast under four what-ifs, honest and private."""

from datetime import date
from decimal import Decimal as D

from fastapi.testclient import TestClient

from app import main
from app.scenarios import Inputs, build
from tests.test_safety_net import PAYDAY, TODAY, proj

client = TestClient(main.app)


def test_one_supporter_alone_falls_short_and_the_circle_covers_it() -> None:
    s = build(Inputs(proj("maya", 165), [("Sam", D(90)), ("Emma", D(45))], authorized=D(495), need=D(135)))
    by = {x.key: x for x in s.scenarios}
    assert set(by) == {"A", "B", "C"}  # the safe split covers it all: no "unsafe" scenario to show
    assert not by["A"].covered and by["A"].low.balance == 165
    assert by["B"].label == "Only Sam" and by["B"].low.balance == 255 and not by["B"].covered
    assert by["C"].covered and by["C"].low.balance == 300


def test_help_goes_back_on_payday() -> None:
    s = build(Inputs(proj("maya", 165), [("Sam", D(90))], authorized=D(150), need=D(135)))
    b = next(x for x in s.scenarios if x.key == "B")
    on = {p.date: p.balance for p in b.points}
    assert on[TODAY] == 1090 and on[PAYDAY] == 900  # +90 from today until payday, back after


def test_unsafe_help_shows_only_when_the_safe_split_falls_short_and_names_nobody() -> None:
    s = build(Inputs(proj("maya", 165), [("Sam", D(90))], authorized=D(450), need=D(135)))
    d = next(x for x in s.scenarios if x.key == "D")
    assert d.blocked and d.help == 135 and d.covered
    assert "Jordan" not in d.note and "Sam" not in d.note  # never who was held back, or why


def test_route_returns_only_my_own_forecast() -> None:
    body = client.get("/forecast/scenarios?persona=maya").json()
    assert {x["key"] for x in body["scenarios"]} >= {"A"}
    assert body["floor"] == 300 and date.fromisoformat(body["scenarios"][0]["points"][0]["date"]) >= TODAY
