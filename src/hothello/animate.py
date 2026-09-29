"""Login animations.

The MOTD is rendered as usual, split into coloured cells, and revealed by an
effect.  Only cells that change are redrawn each frame (so it stays light over
SSH), any key skips to the end, and the real text is printed over the last
frame so scrollback, colours and links end up exactly as without animation.
"""

from __future__ import annotations

import math
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from typing import Callable, Iterator

from .textutil import char_width
from .themes import Painter, gradient

STYLES = {
    "none": "All at once, no animation",
    "lines": "Line by line, top to bottom",
    "slide": "Slides in from the right edge",
    "wipe": "Wiped in from left to right",
    "rain": "Rain drops: characters fall into place",
    "decode": "Scrambled characters decode into place",
    "nuke": "A bomb drops, the blast wave reveals everything",
    "random": "A different effect every login",
}
EFFECTS = ["lines", "slide", "wipe", "rain", "decode", "nuke"]
SPEEDS = {"fast": 0.6, "normal": 1.0, "slow": 1.7}
SECONDS = {"lines": 0.7, "slide": 0.8, "wipe": 0.7, "rain": 1.6, "decode": 1.5, "nuke": 2.2}
FPS = 30


@dataclass(frozen=True)
class Cell:
    style: str  # SGR sequence in force for this character ("" = terminal default)
    ch: str
    width: int = 1


Pos = tuple[int, int]
Frame = dict[Pos, Cell]

_ESCAPE = re.compile(r"\x1b\[([0-9;]*)m|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[A-Za-z]")


def _apply_sgr(params: str, parts: list[str], bg: bool) -> tuple[list[str], bool]:
    tokens = params.split(";") if params else ["0"]
    i = 0
    while i < len(tokens):
        n = int(tokens[i]) if tokens[i].isdigit() else 0
        if n == 0:
            parts, bg = [], False
            i += 1
            continue
        if n in (38, 48):
            kind = tokens[i + 1] if i + 1 < len(tokens) else ""
            span = 3 if kind == "5" else 5 if kind == "2" else 1
            parts = parts + [";".join(tokens[i:i + span])]
            bg = bg or n == 48
            i += span
            continue
        if 40 <= n <= 47 or 100 <= n <= 107:
            bg = True
        elif n == 49:
            bg = False
        parts = parts + [tokens[i]]
        i += 1
    return parts, bg


def parse_line(line: str) -> dict[int, Cell]:
    """Visible cells of one rendered line: {column: Cell}.  Plain spaces are
    omitted, but spaces with a background colour (powerline segments) are kept."""
    cells: dict[int, Cell] = {}
    parts: list[str] = []
    bg = False
    col = pos = 0
    while pos < len(line):
        if line[pos] == "\x1b":
            m = _ESCAPE.match(line, pos)
            if m:
                if m.group(0).endswith("m") and m.group(0).startswith("\x1b["):
                    parts, bg = _apply_sgr(m.group(1), parts, bg)
                pos = m.end()
                continue
        ch = line[pos]
        pos += 1
        w = char_width(ch)
        if w == 0:
            continue
        if ch != " " or bg:
            cells[col] = Cell(f"\x1b[{';'.join(parts)}m" if parts else "", ch, w)
        col += w
    return cells


def parse(text: str) -> tuple[list[str], Frame]:
    lines = text.rstrip("\n").split("\n")
    grid: Frame = {}
    for r, line in enumerate(lines):
        for c, cell in parse_line(line).items():
            grid[(r, c)] = cell
    return lines, grid


# -- effects: each yields n frames; the last frame is the finished picture ------------------------

def _ease(t: float) -> float:
    return 1 - (1 - t) ** 3


def fx_lines(cells: Frame, n: int, **_) -> Iterator[Frame]:
    rows = sorted({r for r, _ in cells})
    for i in range(n):
        shown = set(rows[: math.ceil((i + 1) / n * len(rows))])
        yield {p: c for p, c in cells.items() if p[0] in shown}


def fx_slide(cells: Frame, n: int, width: int, **_) -> Iterator[Frame]:
    for i in range(n):
        off = round(width * (1 - _ease((i + 1) / n)))
        yield {(r, c + off): cell for (r, c), cell in cells.items() if c + off + cell.width <= width}


def fx_wipe(cells: Frame, n: int, width: int, painter: Painter, ascii_only: bool, **_) -> Iterator[Frame]:
    left = min((c for _, c in cells), default=0)
    right = max((c + cell.width for (_, c), cell in cells.items()), default=width)
    rows = sorted({r for r, _ in cells})
    edge_cell = Cell(painter.sgr(fg=("rgb", (255, 255, 255)), bold=True), "|" if ascii_only else "▌")
    for i in range(n):
        edge = left + (right - left) * _ease((i + 1) / n)
        frame = {p: c for p, c in cells.items() if p[1] < edge}
        if i < n - 1:
            frame.update({(r, int(edge)): edge_cell for r in rows})
        yield frame


def fx_rain(cells: Frame, n: int, rng: random.Random, **_) -> Iterator[Frame]:
    top = min((r for r, _ in cells), default=0)
    height = max((r for r, _ in cells), default=0) - top + 1
    speed = max(1.0, height / (0.4 * n))  # rows per frame
    start = {p: rng.uniform(0, 0.55 * n) for p in cells}
    for i in range(n):
        settled: Frame = {}
        falling: Frame = {}
        for (r, c), cell in cells.items():
            t = i - start[(r, c)]
            if t < 0:
                continue
            y = top + t * speed
            if y >= r or i == n - 1:
                settled[(r, c)] = cell
            else:
                falling[(int(y), c)] = cell
        settled.update(falling)
        yield settled


def fx_decode(cells: Frame, n: int, rng: random.Random, **_) -> Iterator[Frame]:
    noise = "!#$%&*+-/<=>?@[]^{}~0123456789ABCDEFXYZ"
    reveal = {p: rng.uniform(0.1, 0.9) * n for p in cells}
    scramble = {p: rng.choice(noise) for p in cells}
    for i in range(n):
        frame: Frame = {}
        for p, cell in cells.items():
            if i >= reveal[p] or i == n - 1:
                frame[p] = cell
            else:
                if rng.random() < 0.12:
                    scramble[p] = rng.choice(noise)
                frame[p] = Cell(cell.style, scramble[p] if cell.width == 1 else scramble[p] * 2, cell.width)
        yield frame


_FIRE = [(255, 255, 235), (255, 230, 90), (255, 150, 20), (220, 50, 10), (110, 15, 5)]


def fx_nuke(cells: Frame, n: int, width: int, height: int, painter: Painter, ascii_only: bool,
            rng: random.Random, focus: tuple[int, int] | None = None, **_) -> Iterator[Frame]:
    rows = [r for r, _ in cells] or [0]
    top, bottom = (focus[0], focus[1] - 1) if focus else (min(rows), max(rows))
    cols = [c for _, c in cells] or [0]
    cy, cx = (top + bottom) / 2, (min(cols) + max(cols)) / 2
    region = [(r, c) for r in range(min(rows), max(rows) + 1) for c in range(width)]
    dist = {p: math.hypot((p[1] - cx) / 2, p[0] - cy) for p in region}
    far = max(dist.values(), default=1) + 1
    ring = 3.0
    shades = "@#*+:." if ascii_only else "█▓▒░·."
    fire = [Cell(painter.sgr(fg=("rgb", gradient(_FIRE, k / 7))), shades[min(k, len(shades) - 1)])
            for k in range(8)]
    core = Cell(painter.sgr(fg=("rgb", _FIRE[0]), bold=True), "#" if ascii_only else "█")
    bomb = Cell(painter.sgr(fg=("rgb", (230, 230, 230)), bold=True), "v" if ascii_only else "▼")
    drop, flash = int(0.18 * n), int(0.32 * n)
    top_row = min(rows)
    for i in range(n):
        frame: Frame = {}
        if i < drop:  # the bomb falls towards the centre
            y = int(top_row + (cy - top_row) * (i + 1) / drop)
            frame[(y, int(cx))] = bomb
        elif i < flash:  # a growing fireball
            radius = 0.5 + 3.5 * (i - drop + 1) / (flash - drop)
            frame.update({p: core for p, d in dist.items() if d <= radius})
        elif i == n - 1:
            frame = dict(cells)
        else:  # the blast wave; everything behind it is revealed
            t = (i - flash + 1) / (n - flash - 1)
            radius = 4 + (far + ring) * (1 - (1 - t) ** 2)  # fast, then slowing, but no long idle tail
            for p, d in dist.items():
                if d < radius - ring:
                    if p in cells:
                        frame[p] = cells[p]
                elif d < radius:
                    depth = (radius - d) / ring  # 0 at the front of the wave, 1 at its back
                    frame[p] = fire[min(int(depth * 7), 7)]
                elif d < radius + 5 and rng.random() < 0.015:
                    frame[p] = fire[rng.randint(3, 6)]  # flying debris
        yield frame


FX: dict[str, Callable[..., Iterator[Frame]]] = {
    "lines": fx_lines, "slide": fx_slide, "wipe": fx_wipe,
    "rain": fx_rain, "decode": fx_decode, "nuke": fx_nuke,
}


# -- drawing ----------------------------------------------------------------------------------------

class Screen:
    """Draws frames into a reserved block of the terminal, sending only changes."""

    def __init__(self, out, height: int):
        self.out = out
        self.shown: Frame = {}
        self.cursor: Pos = (0, 0)
        # Reserve the block (scrolling if needed), then return to its top-left corner.
        out.write("\x1b[?25l" + "\n" * height + f"\x1b[{height}A\r")

    def _move(self, to: Pos) -> str:
        (r0, c0), (r, c) = self.cursor, to
        s = f"\x1b[{r - r0}B" if r > r0 else f"\x1b[{r0 - r}A" if r < r0 else ""
        if c != c0:
            s += "\r" + (f"\x1b[{c}C" if c else "")
        return s

    def draw(self, frame: Frame) -> None:
        changes = [(p, c) for p, c in frame.items() if self.shown.get(p) != c]
        changes += [(p, Cell("", " " * c.width, c.width)) for p, c in self.shown.items() if p not in frame]
        if not changes:
            return
        changes.sort(key=lambda pc: pc[0])
        buf, style = [], None
        for pos, cell in changes:
            if pos != self.cursor:
                buf.append(self._move(pos))
            if cell.style != style:
                buf.append("\x1b[0m" + cell.style)
                style = cell.style
            buf.append(cell.ch)
            self.cursor = (pos[0], pos[1] + cell.width)
        buf.append("\x1b[0m")
        self.out.write("".join(buf))
        self.out.flush()
        self.shown = dict(frame)

    def finish(self, lines: list[str]) -> None:
        """Print the real MOTD over the animation (keeps links, clears leftovers)."""
        self.out.write(self._move((0, 0)).replace("\r", "") + "\r"
                       + "".join(line + "\x1b[0m\x1b[K\n" for line in lines) + "\x1b[?25h")
        self.out.flush()


class Keys:
    """Any key press skips the animation; the tty is always restored."""

    def __init__(self, realtime: bool):
        self.realtime = realtime
        self.fd: int | None = None
        self.saved = None

    def __enter__(self) -> "Keys":
        if self.realtime and os.name != "nt":
            try:
                import termios
                import tty

                if sys.stdin.isatty():
                    self.fd = sys.stdin.fileno()
                    self.saved = termios.tcgetattr(self.fd)
                    tty.setcbreak(self.fd)
            except Exception:
                self.fd = None
        return self

    def __exit__(self, *exc) -> None:
        if self.fd is not None and self.saved is not None:
            import termios

            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    def wait(self, seconds: float) -> bool:
        """Sleep up to `seconds`; True if a key was pressed (and swallowed)."""
        if not self.realtime:
            return False
        if os.name == "nt":
            import msvcrt

            end = time.monotonic() + seconds
            while True:
                if msvcrt.kbhit():
                    while msvcrt.kbhit():
                        msvcrt.getwch()
                    return True
                left = end - time.monotonic()
                if left <= 0:
                    return False
                time.sleep(min(left, 0.01))
        if self.fd is not None:
            import select

            ready, _, _ = select.select([self.fd], [], [], max(seconds, 0))
            if ready:
                os.read(self.fd, 1024)
                return True
            return False
        time.sleep(max(seconds, 0))
        return False


def resolve(style: str, rng: random.Random | None = None) -> str:
    if style == "random":
        return (rng or random).choice(EFFECTS)
    return style if style in FX else "none"


def play(text: str, *, style: str, width: int, term_rows: int | None, painter: Painter,
         ascii_only: bool = False, speed: str = "normal", only: tuple[int, int] | None = None,
         focus: tuple[int, int] | None = None, out=None, realtime: bool = True,
         seed: int | None = None) -> bool:
    """Show `text` with an animation.  Falls back to printing it plainly when the
    effect is "none", output isn't a terminal, or the MOTD is taller than the
    screen.  `only` limits the effect to a line range (the rest appears at once);
    `focus` is the line range the nuke aims for.  Returns True if it animated."""
    out = out or sys.stdout
    rng = random.Random(seed)
    style = resolve(style, rng)
    lines, grid = parse(text)
    height = len(lines)
    tty = getattr(out, "isatty", lambda: False)()
    if style == "none" or not tty or not term_rows or height >= term_rows or not grid:
        out.write(text)
        out.flush()
        return False

    if only:
        animated = {p: c for p, c in grid.items() if only[0] <= p[0] < only[1]}
        static = {p: c for p, c in grid.items() if p not in animated}
    else:
        animated, static = grid, {}
    n = max(8, round(SECONDS[style] * SPEEDS.get(speed, 1.0) * FPS))
    effect = FX[style](animated, n, width=width, height=height, painter=painter,
                       ascii_only=ascii_only, rng=rng, focus=focus)
    screen = Screen(out, height)
    try:
        with Keys(realtime) as keys:
            start = time.monotonic()
            for i, frame in enumerate(effect):
                screen.draw({**static, **frame})
                if keys.wait(start + (i + 1) / FPS - time.monotonic()):
                    break
    finally:
        screen.finish(lines)
    return True
