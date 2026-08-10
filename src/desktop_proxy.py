from __future__ import annotations

import os
from typing import Mapping

from gnome_proxy import GnomeProxyAdapter
from kde_proxy import KdeProxyAdapter


def _desktop_hint(env: Mapping[str, str] | None = None) -> str:
    environment = os.environ if env is None else env
    return " ".join(
        (
            environment.get("XDG_CURRENT_DESKTOP", ""),
            environment.get("XDG_SESSION_DESKTOP", ""),
            environment.get("DESKTOP_SESSION", ""),
        )
    ).casefold()


def select_desktop_proxy(
    *,
    env: Mapping[str, str] | None = None,
    kde_adapter: KdeProxyAdapter | None = None,
    gnome_adapter: GnomeProxyAdapter | None = None,
):
    """Select the safest desktop proxy adapter, prioritising crash recovery."""

    kde = kde_adapter or KdeProxyAdapter()
    gnome = gnome_adapter or GnomeProxyAdapter()

    # A pending journal always wins so a desktop/session switch cannot strand
    # proxy settings from the previous run.
    if kde.has_journal() and not gnome.has_journal():
        return kde
    if gnome.has_journal() and not kde.has_journal():
        return gnome

    hint = _desktop_hint(env)
    if "kde" in hint or "plasma" in hint:
        return kde
    if "gnome" in hint:
        return gnome

    if kde.is_available() and not gnome.is_available():
        return kde
    return gnome
