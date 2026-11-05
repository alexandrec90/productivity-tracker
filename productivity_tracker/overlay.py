"""The always-on-top overlay: one row per task, coloured by what its agents are doing, with
today's prompts per task, and a scoreboard of today against your best day below.

Run it on the PC you sit at (the laptop):

    python -m productivity_tracker.autostart start overlay

Left-click a row to focus one of its sessions; click again for the next one. Right-click
toggles the task between active and inactive. Drag the header to move it. The header's dash
hides it to the tray icon, whose left-click brings it back.
"""

import logging
import queue
import socket
import sys
import threading
import time
import tkinter as tk
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from productivity_tracker.client import TrackerClient
from productivity_tracker.config import Settings
from productivity_tracker.focus import focus_session
from productivity_tracker.status import Color, focus_order, next_session
from productivity_tracker.tray import Command, start_tray

log = logging.getLogger("productivity_tracker.overlay")

PALETTE = {
    Color.GREEN: "#2ecc71",
    Color.YELLOW: "#f1c40f",
    Color.RED: "#e74c3c",
    Color.GRAY: "#5c6370",
}
BG = "#1e1f22"
ROW_BG = "#2b2d31"
ROW_HOVER = "#36393f"
TEXT = "#e6e6e6"
MUTED = "#80848e"
GOLD = PALETTE[Color.YELLOW]
FONT = ("Segoe UI", 10)
SMALL = ("Segoe UI", 9)
SMALL_BOLD = ("Segoe UI", 9, "bold")


@dataclass(frozen=True)
class Row:
    task_id: int
    name: str
    active: bool
    color: Color
    sessions: int
    prompts_today: int = 0


@dataclass(frozen=True)
class Stat:
    """One scoreboard column: today's figure against the best day before it."""

    label: str
    today: str
    best: str
    record: bool


@dataclass(frozen=True)
class Scoreboard:
    stats: tuple[Stat, ...]
    waited: str


def format_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}" if hours else f"{minutes}m"


def _stat(label: str, today: str, best: str, record: bool) -> Stat:
    return Stat(label, f"\N{BLACK STAR} {today}" if record else today, best, record)


def _beats(today: float, best: float) -> bool:
    # Beating a record of nothing (the first day) is no record.
    return best > 0 and today > best


class OverlayModel:
    """Everything the overlay decides, without Tk, so it is testable."""

    def __init__(self) -> None:
        self.tasks: list[Mapping[str, Any]] = []
        self.stats: Mapping[str, Any] | None = None
        self.online = False
        self._last_focused: dict[int, str] = {}

    def update(self, state: Mapping[str, Any] | None) -> None:
        """A fresh /state, or None when the server could not be reached. The last rows stay
        on screen while offline; the header says they are stale."""
        self.online = state is not None
        if state is not None:
            self.tasks = list(state["tasks"])
            self.stats = state.get("stats")

    def rows(self) -> list[Row]:
        return [
            Row(
                t["id"],
                t["name"],
                t["active"],
                Color(t["color"]),
                len(t["sessions"]),
                t.get("prompts_today", 0),
            )
            for t in self.tasks
        ]

    def scoreboard(self) -> Scoreboard | None:
        if self.stats is None:
            return None
        today, best = self.stats["today"], self.stats["best"]
        streak, best_streak = self.stats["streak"], self.stats["best_streak"]
        return Scoreboard(
            stats=(
                _stat(
                    "prompts",
                    str(today["prompts"]),
                    str(best["prompts"]),
                    _beats(today["prompts"], best["prompts"]),
                ),
                _stat(
                    "agent time",
                    format_duration(today["busy_seconds"]),
                    format_duration(best["busy_seconds"]),
                    _beats(today["busy_seconds"], best["busy_seconds"]),
                ),
                _stat(
                    "parallel",
                    str(today["peak_busy"]),
                    str(best["peak_busy"]),
                    _beats(today["peak_busy"], best["peak_busy"]),
                ),
                # The longest streak includes the current one, so matching it is the record.
                _stat("streak", f"{streak}d", f"{best_streak}d", 1 < streak == best_streak),
            ),
            waited=f"agents waited on you {format_duration(today['waiting_seconds'])} today",
        )

    def target_for_click(self, task_id: int) -> Mapping[str, Any] | None:
        task = next((t for t in self.tasks if t["id"] == task_id), None)
        if task is None:
            return None
        order = focus_order(Color(task["color"]), task["sessions"])
        session = next_session(order, self._last_focused.get(task_id))
        if session is not None:
            self._last_focused[task_id] = session["session_id"]
        return session

    def toggle(self, task_id: int) -> bool | None:
        """Flip a task's active flag locally, so the row greys out at once; returns the new
        flag for the server, or None for an unknown task."""
        for i, task in enumerate(self.tasks):
            if task["id"] == task_id:
                active = not task["active"]
                color = Color.GRAY if not active else Color.RED
                self.tasks[i] = {**task, "active": active, "color": color}
                return active
        return None


class OverlayWindow:
    def __init__(
        self,
        root: tk.Tk,
        client: TrackerClient,
        model: OverlayModel,
        local_host: str,
        poll_seconds: float,
        commands: "queue.Queue[Command] | None" = None,
        can_hide: bool = False,
    ) -> None:
        self.root = root
        self.client = client
        self.model = model
        self.local_host = local_host
        self.poll_seconds = poll_seconds
        self.states: queue.Queue[Mapping[str, Any] | None] = queue.Queue()
        self.commands: queue.Queue[Command] = commands or queue.Queue()
        self.hidden = False
        self._signature: object = None
        self._board: Scoreboard | None = None
        self._drag = (0, 0)
        self._placed = False

        root.title("Agents")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.93)
        root.configure(bg=BG)

        header = tk.Frame(root, bg=BG)
        header.pack(fill="x")
        self.title = tk.Label(header, text="Agents", bg=BG, fg=MUTED, font=FONT, anchor="w")
        self.title.pack(side="left", padx=(8, 0), pady=2)
        close = tk.Label(header, text="x", bg=BG, fg=MUTED, font=FONT, cursor="hand2")
        close.pack(side="right", padx=8)
        close.bind("<Button-1>", lambda _e: root.destroy())
        # Only with a tray icon: the window has no taskbar button, so nothing else could
        # bring it back.
        if can_hide:
            hide = tk.Label(header, text="\N{EN DASH}", bg=BG, fg=MUTED, font=FONT, cursor="hand2")
            hide.pack(side="right")
            hide.bind("<Button-1>", lambda _e: self.toggle_visible())
        for widget in (header, self.title):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._on_drag)

        # Column captions, laid out like a row so they line up with the numbers below.
        captions = tk.Frame(root, bg=BG)
        captions.pack(fill="x", padx=4)
        tk.Frame(captions, bg=BG, width=6).pack(side="left", fill="y")
        tk.Label(captions, text="", bg=BG, font=FONT, width=24).pack(side="left", padx=(6, 0))
        tk.Label(captions, text="agents", bg=BG, fg=MUTED, font=FONT, width=6).pack(
            side="right", padx=6
        )
        tk.Label(captions, text="prompts", bg=BG, fg=MUTED, font=FONT, width=7).pack(side="right")

        self.rows = tk.Frame(root, bg=BG)
        self.rows.pack(fill="both", padx=4, pady=(0, 4))
        self.footer = tk.Frame(root, bg=BG)
        self.footer.pack(fill="x", padx=8, pady=(0, 6))

        threading.Thread(target=self._poll_forever, daemon=True).start()
        root.after(100, self._drain)

    def _poll_forever(self) -> None:
        while True:
            try:
                self.states.put(self.client.state())
            except (OSError, ValueError):
                # Unreachable (URLError is an OSError), refused, or not JSON: all "offline".
                self.states.put(None)
            time.sleep(self.poll_seconds)

    def toggle_visible(self) -> None:
        if self.hidden:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
        else:
            self.root.withdraw()
        self.hidden = not self.hidden

    def _drain(self) -> None:
        while not self.commands.empty():
            if self.commands.get_nowait() is Command.QUIT:
                # Nothing may be scheduled on a destroyed root, so no `after` below.
                self.root.destroy()
                return
            self.toggle_visible()
        fresh, latest = False, None
        while not self.states.empty():
            fresh, latest = True, self.states.get_nowait()
        if fresh:
            self.model.update(latest)
            self.render()
        self.root.after(250, self._drain)

    def render(self) -> None:
        # Each part is rebuilt only when what it shows changed: the state arrives every
        # couple of seconds, and the scoreboard's figures move by the minute.
        rows = self.model.rows()
        signature = (self.model.online, rows)
        if signature != self._signature:
            self._signature = signature
            self._render_rows(rows)
        board = self.model.scoreboard()
        if board != self._board:
            self._board = board
            self._render_board(board)
        if not self._placed:
            self._place_top_right()

    def _render_rows(self, rows: list[Row]) -> None:
        self.title.configure(
            text="Agents" if self.model.online else "Agents (offline)",
            fg=MUTED if self.model.online else PALETTE[Color.RED],
        )
        for child in self.rows.winfo_children():
            child.destroy()
        if not rows:
            tk.Label(self.rows, text="no tasks yet", bg=BG, fg=MUTED, font=FONT).pack(padx=8)
        for row in rows:
            self._render_row(row)

    def _render_board(self, board: Scoreboard | None) -> None:
        for child in self.footer.winfo_children():
            child.destroy()
        if board is None:
            return
        for line, caption in enumerate(("", "today", "best")):
            tk.Label(self.footer, text=caption, bg=BG, fg=MUTED, font=SMALL, anchor="w").grid(
                row=line, column=0, sticky="w"
            )
        for column, stat in enumerate(board.stats, start=1):
            cells = (
                (stat.label, MUTED, SMALL),
                (stat.today, GOLD if stat.record else TEXT, SMALL_BOLD if stat.record else SMALL),
                (stat.best, MUTED, SMALL),
            )
            for line, (text, fg, font) in enumerate(cells):
                tk.Label(self.footer, text=text, bg=BG, fg=fg, font=font).grid(
                    row=line, column=column, padx=4
                )
        tk.Label(self.footer, text=board.waited, bg=BG, fg=MUTED, font=SMALL, anchor="w").grid(
            row=3, column=0, columnspan=len(board.stats) + 1, sticky="w", pady=(2, 0)
        )

    def _render_row(self, row: Row) -> None:
        frame = tk.Frame(self.rows, bg=ROW_BG, cursor="hand2")
        frame.pack(fill="x", pady=1)
        # An inactive task gets no indicator at all, only grey text.
        bar = PALETTE[row.color] if row.active else ROW_BG
        tk.Frame(frame, bg=bar, width=6).pack(side="left", fill="y")
        name = tk.Label(
            frame,
            text=row.name,
            bg=ROW_BG,
            fg=TEXT if row.active else MUTED,
            font=FONT,
            anchor="w",
            width=24,
        )
        name.pack(side="left", padx=(6, 0), pady=3)
        count = tk.Label(
            frame,
            text=str(row.sessions) if row.sessions else "",
            bg=ROW_BG,
            fg=MUTED,
            font=FONT,
            width=6,
        )
        count.pack(side="right", padx=6)
        prompts = tk.Label(
            frame,
            text=str(row.prompts_today) if row.prompts_today else "",
            bg=ROW_BG,
            fg=MUTED,
            font=FONT,
            width=7,
        )
        prompts.pack(side="right")
        self._bind_row(row.task_id, (frame, name, count, prompts))

    def _bind_row(self, task_id: int, widgets: tuple[tk.Misc, ...]) -> None:
        def click(_event: tk.Event) -> None:
            self.on_click(task_id)

        def toggle(_event: tk.Event) -> None:
            self.on_toggle(task_id)

        def hover(_event: tk.Event) -> None:
            _shade(widgets, ROW_HOVER)

        def leave(_event: tk.Event) -> None:
            _shade(widgets, ROW_BG)

        for widget in widgets:
            widget.bind("<Button-1>", click)
            widget.bind("<Button-3>", toggle)
            widget.bind("<Enter>", hover)
            widget.bind("<Leave>", leave)

    def on_click(self, task_id: int) -> None:
        session = self.model.target_for_click(task_id)
        if session is not None:
            # Synchronously, while this process still holds the foreground the click gave
            # it: Windows refuses SetForegroundWindow to a process that does not.
            focus_session(session, self.local_host)

    def on_toggle(self, task_id: int) -> None:
        active = self.model.toggle(task_id)
        if active is None:
            return
        self.render()
        threading.Thread(target=self._send_toggle, args=(task_id, active), daemon=True).start()

    def _send_toggle(self, task_id: int, active: bool) -> None:
        try:
            self.client.set_active(task_id, active)
        except (OSError, ValueError) as exc:
            # The next poll shows the server's flag, undoing the local flip.
            log.warning("could not set task %s active=%s: %s", task_id, active, exc)

    def _place_top_right(self) -> None:
        self.root.update_idletasks()
        x = self.root.winfo_screenwidth() - self.root.winfo_reqwidth() - 24
        self.root.geometry(f"+{x}+48")
        self._placed = True

    def _start_drag(self, event: tk.Event) -> None:
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _on_drag(self, event: tk.Event) -> None:
        dx, dy = self._drag
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")


def _shade(widgets: tuple[tk.Misc, ...], color: str) -> None:
    for widget in widgets:
        widget["bg"] = color


def _dpi_aware() -> None:
    # Without it Windows bitmap-scales the window on a high-DPI laptop screen: blurry text.
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        # shcore arrived in Windows 8.1; older Windows simply stays DPI-unaware.
        pass


def main() -> None:
    _dpi_aware()
    settings = Settings()
    root = tk.Tk()
    commands: queue.Queue[Command] = queue.Queue()
    tray = start_tray(commands, [PALETTE[c] for c in (Color.GREEN, Color.YELLOW, Color.RED)])
    OverlayWindow(
        root,
        TrackerClient(settings.tracker_url, settings.tracker_token),
        OverlayModel(),
        socket.gethostname(),
        settings.poll_interval_seconds,
        commands,
        tray is not None,
    )
    root.mainloop()
    if tray is not None:
        tray.stop()


if __name__ == "__main__":
    main()
