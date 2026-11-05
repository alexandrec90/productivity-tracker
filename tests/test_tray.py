"""The tray icon, through a stand-in for pystray: it is a Windows-only dependency, and a real
icon needs a desktop session."""

import queue
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from productivity_tracker import tray
from productivity_tracker.tray import Command, build_menu, icon_image, start_tray


class Item:
    def __init__(self, text: str, action: Any, default: bool = False, checked: Any = None) -> None:
        self.text = text
        self.action = action
        self.default = default
        self.checked = checked


class Menu:
    SEPARATOR = object()

    def __init__(self, *items: Any) -> None:
        self.items = items


class Icon:
    def __init__(self, name: str, image: Any, title: str, menu: Menu) -> None:
        self.name = name
        self.image = image
        self.title = title
        self.menu = menu
        self.detached = False

    def run_detached(self) -> None:
        self.detached = True


FAKE_PYSTRAY = SimpleNamespace(Menu=Menu, MenuItem=Item, Icon=Icon)


class Login:
    """Stands in for `autostart`."""

    def __init__(self, on: bool = False, fail: bool = False) -> None:
        self.on = on
        self.fail = fail

    def is_enabled(self, name: str) -> bool:
        assert name == "overlay"
        return self.on

    def enable(self, name: str) -> None:
        if self.fail:
            raise OSError("registry says no")
        self.on = True

    def disable(self, name: str) -> None:
        self.on = False


def item(menu: Menu, text: str) -> Item:
    return next(i for i in menu.items if isinstance(i, Item) and i.text == text)


def test_the_default_action_toggles_through_the_queue():
    commands: queue.Queue[Command] = queue.Queue()
    menu = build_menu(FAKE_PYSTRAY, commands)

    show = item(menu, "Show / hide")
    assert show.default  # What a left-click on the icon runs.
    show.action()

    assert commands.get_nowait() is Command.TOGGLE


def test_quit_goes_through_the_queue():
    commands: queue.Queue[Command] = queue.Queue()
    item(build_menu(FAKE_PYSTRAY, commands), "Quit").action()
    assert commands.get_nowait() is Command.QUIT


def test_start_at_login_shows_and_flips_the_setting(monkeypatch):
    login = Login()
    monkeypatch.setattr(tray, "autostart", login)
    entry = item(build_menu(FAKE_PYSTRAY, queue.Queue()), "Start at login")

    assert entry.checked(entry) is False
    entry.action()
    assert entry.checked(entry) is True
    entry.action()
    assert login.on is False


def test_a_registry_failure_is_logged_not_raised(monkeypatch, caplog):
    monkeypatch.setattr(tray, "autostart", Login(fail=True))
    item(build_menu(FAKE_PYSTRAY, queue.Queue()), "Start at login").action()
    assert "could not change start at login" in caplog.text


def test_a_refused_enable_is_logged_not_raised(monkeypatch, caplog):
    def refuse(name: str) -> None:
        raise ValueError("a git worktree")

    login = Login()
    monkeypatch.setattr(login, "enable", refuse)
    monkeypatch.setattr(tray, "autostart", login)
    item(build_menu(FAKE_PYSTRAY, queue.Queue()), "Start at login").action()
    assert "a git worktree" in caplog.text


def test_menu_callbacks_take_no_arguments():
    # pystray picks how to call an action from its argument count; a default argument
    # would be taken for the icon it passes.
    for entry in build_menu(FAKE_PYSTRAY, queue.Queue()).items:
        if isinstance(entry, Item):
            assert entry.action.__code__.co_argcount == 0


def test_start_tray_runs_the_icon_detached(monkeypatch):
    monkeypatch.setitem(sys.modules, "pystray", FAKE_PYSTRAY)
    monkeypatch.setattr(tray, "icon_image", lambda bars: "image")

    icon = start_tray(queue.Queue(), ["#000000"])

    assert isinstance(icon, Icon)
    assert icon.detached
    assert icon.image == "image"


def test_start_tray_without_pystray_is_none(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "pystray", None)  # None makes `import` raise ImportError.
    assert start_tray(queue.Queue(), ["#000000"]) is None
    assert "no tray icon" in caplog.text


def test_the_icon_draws_a_row_per_colour():
    pytest.importorskip("PIL", reason="pillow is a Windows-only dependency")
    image = icon_image(["#ff0000", "#00ff00", "#0000ff"])

    assert image.size == (tray.SIZE, tray.SIZE)
    assert image.getpixel((0, 0))[3] == 0  # The rounded corner is transparent.
    colours = {image.getpixel((tray.SIZE // 2, y))[:3] for y in range(tray.SIZE)}
    assert {(255, 0, 0), (0, 255, 0), (0, 0, 255)} <= colours
