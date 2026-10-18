"""Circle notification words — names and the circle only, never money."""

from app import inbox


def test_words_on_each_notification() -> None:
    assert inbox.text("circle_invite", "Sam", "Family") == "Sam added you to Family"
    assert inbox.text("circle_joined", "Maya", "Family") == "Maya joined Family"
    assert inbox.text("circle_declined", "Jordan", "Weekend crew") == "Jordan didn't join Weekend crew"


def test_you_are_never_notified_about_yourself() -> None:
    class Boom:
        def execute(self, *a):  # pragma: no cover - must not be called
            raise AssertionError("wrote a self-notification")

    inbox.add(Boom(), "maya", "circle_joined", "c", "maya")
