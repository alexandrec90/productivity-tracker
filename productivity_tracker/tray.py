"""The overlay's notification-area icon: the way back to a hidden window, and its controls.

Left-click shows or hides the overlay; right-click has that, Start at login and Quit.

pystray runs its own message loop on its own thread, and Tk may only be touched from the
thread running `mainloop`, so the menu never calls the window. It queues a `Command`, and the
window's regular drain carries it out.
"""

import logging
import queue
from collections.abc import Sequence
from enum import Enum, auto
from typing import Any

from productivity_tracker import autostart

log = logging.getLogger("productivity_tracker.tray")

SIZE = 64
BACKGROUND = "#1e1f22"


class Command(Enum):
    TOGGLE = auto()
    QUIT = auto()


def icon_image(bars: Sequence[str]) -> Any:
    """A miniature of the overlay: a dark square with one coloured row per colour."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=12, fill=BACKGROUND)
    margin, gap = 10, 6
    height = (SIZE - 2 * margin - gap * (len(bars) - 1)) // len(bars)
    for row, color in enumerate(bars):
        top = margin + row * (height + gap)
        draw.rectangle((margin, top, SIZE - margin - 1, top + height - 1), fill=color)
    return image


def build_menu(pystray: Any, commands: "queue.Queue[Command]") -> Any:
    def toggle() -> None:
        commands.put(Command.TOGGLE)

    def quit_overlay() -> None:
        commands.put(Command.QUIT)

    def flip_login() -> None:
        try:
            if autostart.is_enabled("overlay"):
                autostart.disable("overlay")
            else:
                autostart.enable("overlay")
        except (OSError, ValueError) as exc:
            log.warning("could not change start at login: %s", exc)

    def login_is_on(_item: Any) -> bool:
        return autostart.is_enabled("overlay")

    return pystray.Menu(
        pystray.MenuItem("Show / hide", toggle, default=True),
        pystray.MenuItem("Start at login", flip_login, checked=login_is_on),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_overlay),
    )


def start_tray(commands: "queue.Queue[Command]", bars: Sequence[str]) -> Any | None:
    """The running icon, or None where there is none to be had: pystray is a Windows-only
    dependency. Without an icon nothing could bring a hidden window back, so the caller
    offers no way to hide it."""
    try:
        import pystray
    except ImportError as exc:
        log.warning("no tray icon: %s", exc)
        return None
    icon = pystray.Icon(
        "productivity-tracker", icon_image(bars), "Agents", build_menu(pystray, commands)
    )
    icon.run_detached()
    return icon
