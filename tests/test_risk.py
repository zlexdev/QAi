from __future__ import annotations

from qai.engine.risk import is_allowlisted, is_destructive


def test_destructive_keywords_fire_english() -> None:
    assert is_destructive("Delete account")
    assert is_destructive("Withdraw funds")
    assert is_destructive("Pay now")


def test_destructive_keywords_fire_russian() -> None:
    assert is_destructive("Удалить аккаунт")
    assert is_destructive("Оплатить заказ")
    assert is_destructive("Вывести средства")


def test_plain_labels_do_not_false_positive() -> None:
    assert not is_destructive("Submit")
    assert not is_destructive("Next")
    assert not is_destructive("Learn more")
    assert not is_destructive(None)


def test_allowlist_overrides_by_selector() -> None:
    allowlist = frozenset({"#confirm-delete"})
    assert is_allowlisted("#confirm-delete", allowlist)
    assert not is_allowlisted("#other-button", allowlist)
