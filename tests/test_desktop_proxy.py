from __future__ import annotations

from desktop_proxy import select_desktop_proxy


class StubAdapter:
    def __init__(self, *, available: bool, journal: bool, name: str) -> None:
        self._available = available
        self._journal = journal
        self.integration_name = name

    def is_available(self) -> bool:
        return self._available

    def has_journal(self) -> bool:
        return self._journal


def test_selects_kde_for_plasma_session():
    kde = StubAdapter(available=True, journal=False, name="KDE/KIO")
    gnome = StubAdapter(available=True, journal=False, name="GNOME")
    assert (
        select_desktop_proxy(
            env={"XDG_CURRENT_DESKTOP": "KDE"},
            kde_adapter=kde,
            gnome_adapter=gnome,
        )
        is kde
    )


def test_selects_gnome_for_gnome_session():
    kde = StubAdapter(available=True, journal=False, name="KDE/KIO")
    gnome = StubAdapter(available=True, journal=False, name="GNOME")
    assert (
        select_desktop_proxy(
            env={"XDG_CURRENT_DESKTOP": "GNOME"},
            kde_adapter=kde,
            gnome_adapter=gnome,
        )
        is gnome
    )


def test_pending_kde_recovery_journal_wins_over_desktop_hint():
    kde = StubAdapter(available=True, journal=True, name="KDE/KIO")
    gnome = StubAdapter(available=True, journal=False, name="GNOME")
    assert (
        select_desktop_proxy(
            env={"XDG_CURRENT_DESKTOP": "GNOME"},
            kde_adapter=kde,
            gnome_adapter=gnome,
        )
        is kde
    )


def test_unknown_desktop_prefers_only_available_adapter():
    kde = StubAdapter(available=True, journal=False, name="KDE/KIO")
    gnome = StubAdapter(available=False, journal=False, name="GNOME")
    assert (
        select_desktop_proxy(
            env={},
            kde_adapter=kde,
            gnome_adapter=gnome,
        )
        is kde
    )
