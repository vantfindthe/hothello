"""Draws the MOTD: powerline header, framed art with credit, and headlines."""

from __future__ import annotations

from .feeds import Headline
from .picker import Pick
from .scraper import art_url
from .textutil import cell_width, sanitize, truncate
from .themes import FRAME_CHARS, RESET, Glyphs, Painter, Theme, art_color_fn, parse_color


def hyperlink(text: str, url: str, enabled: bool) -> str:
    """OSC 8 hyperlink; only plain http(s) URLs are ever emitted."""
    if not enabled or not url or not url.lower().startswith(("http://", "https://")):
        return text
    url = sanitize(url).replace(" ", "%20")
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"


def format_age(seconds: float) -> str:
    if seconds < 3600:
        return f"{max(int(seconds // 60), 1)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


# -- header ------------------------------------------------------------------------

def header_line(items: list[tuple[str, str]], theme: Theme, glyphs: Glyphs, painter: Painter, cols: int) -> str:
    if not items:
        return ""
    if not painter.enabled:
        parts = [text for _, text in items]
        while len(parts) > 1 and cell_width(glyphs.dot.join(parts)) > cols:
            parts.pop()
        return truncate(glyphs.dot.join(parts), cols, glyphs.ellipsis)

    labels = []
    for icon_key, text in items:
        icon = glyphs.icon(icon_key)
        labels.append(f" {icon} {text} " if icon else f" {text} ")
    start, between, end = glyphs.separators(theme.separator)
    colors = [(parse_color(s[0]), parse_color(s[1] if len(s) > 1 else None)) for s in theme.segments]
    colors = colors or [(None, None)]

    def width(n: int) -> int:
        return sum(cell_width(lab) for lab in labels[:n]) + len(start) + len(between) * (n - 1) + len(end)

    n = len(labels)
    while n > 1 and width(n) > cols:
        n -= 1
    labels = labels[:n]
    if width(n) > cols:
        labels[0] = truncate(labels[0], cols - len(start) - len(end), glyphs.ellipsis)

    out = []
    if start:
        out.append(painter.sgr(fg=colors[0][0]) + start + RESET)
    for i, label in enumerate(labels):
        bg, fg = colors[i % len(colors)]
        out.append(painter.sgr(fg=fg, bg=bg) + label + RESET)
        if i + 1 < len(labels):
            if between:
                out.append(painter.sgr(fg=bg, bg=colors[(i + 1) % len(colors)][0]) + between + RESET)
        elif end:
            out.append(painter.sgr(fg=bg) + end + RESET)
    return "".join(out)


# -- art -----------------------------------------------------------------------------

def _colorize(line: str, y: int, color_at, painter: Painter, fallback) -> str:
    if not painter.enabled:
        return line
    if color_at is None:
        return painter.paint(line, fg=fallback)
    out, current = [], ""
    for x, ch in enumerate(line):
        if ch != " ":
            seq = painter.sgr(fg=color_at(x, y))
            if seq != current:
                out.append(seq or RESET)
                current = seq
        out.append(ch)
    if current:
        out.append(RESET)
    return "".join(out)


def art_block(pick: Pick, theme: Theme, art_style: str, glyphs: Glyphs, painter: Painter,
              cols: int, display: dict, links: bool) -> list[str]:
    art, lines = pick.art, pick.lines
    if art is None or not lines:
        return []
    w = max(cell_width(line) for line in lines)
    h = len(lines)
    style = theme.art_style if art_style in ("", "theme", None) else art_style
    color_at = art_color_fn(style, theme.art_colors, theme.art_direction, w, h)
    text_color = parse_color(theme.text)
    body = [_colorize(line, y, color_at, painter, text_color) + " " * (w - cell_width(line))
            for y, line in enumerate(lines)]

    frame = display.get("frame", "none")
    if glyphs.name == "ascii" and frame != "none":
        frame = "ascii"
    chars = FRAME_CHARS.get(frame)
    sep = " - " if glyphs.name == "ascii" else " · "
    title_on = display.get("title", True)
    credit_on = display.get("credit", True)
    title = (art.title or "untitled") if title_on else ""
    url = art_url(art.id)
    short_url = url.split("://", 1)[1]
    frame_c, title_c, muted_c = parse_color(theme.frame), parse_color(theme.title), parse_color(theme.muted)

    if chars:
        tl, tr, bl, br, hz, vt = chars
        full_credit = f"{art.artist}{sep}{short_url}" if art.artist else short_url
        # Widen the frame (up to the screen) so small art still gets its title and credit.
        wanted = max(cell_width(title), cell_width(full_credit) if credit_on else 0) + 4
        inner = max(w + 2, min(wanted, cols - 2))
        block_w = inner + 2
        pad = " " * max((cols - block_w) // 2, 0) if display.get("align") == "center" else ""
        top_label = truncate(title, inner - 4, glyphs.ellipsis) if title and inner >= 7 else ""
        if top_label:
            top = (painter.paint(tl + hz + " ", frame_c) + painter.paint(top_label, title_c, bold=True)
                   + painter.paint(" " + hz * (inner - 3 - cell_width(top_label)) + tr, frame_c))
        else:
            top = painter.paint(tl + hz * inner + tr, frame_c)
        credit = ""
        if credit_on:
            for option in (full_credit, art.artist, ""):
                if option and cell_width(option) <= inner - 4:
                    credit = option
                    break
        if credit:
            bottom = (painter.paint(bl + hz * (inner - 3 - cell_width(credit)) + " ", frame_c)
                      + hyperlink(painter.paint(credit, muted_c), url, links)
                      + painter.paint(" " + hz + br, frame_c))
        else:
            bottom = painter.paint(bl + hz * inner + br, frame_c)
        left = (inner - w) // 2
        side_l = painter.paint(vt, frame_c) + " " * left
        side_r = " " * (inner - w - left) + painter.paint(vt, frame_c)
        return [pad + top] + [pad + side_l + line + side_r for line in body] + [pad + bottom]

    center = display.get("align") == "center"
    pad_n = max((cols - w) // 2, 0) if center else 0
    out = [" " * pad_n + line for line in body]
    if title_on or credit_on:
        by = f" by {art.artist}" if art.artist else ""
        if title and credit_on:
            text = f"{title}{by}{sep}{short_url}"
        elif title:
            text = title
        else:
            text = f"{art.artist}{sep}{short_url}" if art.artist else short_url
        credit = truncate(text, cols, glyphs.ellipsis)
        credit_pad = max((cols - cell_width(credit)) // 2, 0) if center else 0
        out.append(" " * credit_pad + hyperlink(painter.paint(credit, muted_c), url if credit_on else "", links))
    return out


# -- news ------------------------------------------------------------------------------

def news_block(headlines: list[Headline], theme: Theme, glyphs: Glyphs, painter: Painter, cols: int,
               news_cfg: dict, links: bool, now: float) -> list[str]:
    if not headlines:
        return []
    muted_c, text_c, accent_c = (parse_color(c) for c in (theme.muted, theme.text, theme.accent))
    out = [_heading("news", "Headlines", theme, glyphs, painter, cols)]

    show_source = news_cfg.get("show_source", True)
    show_age = news_cfg.get("show_age", True)
    badge_colors = [(parse_color(b[0]), parse_color(b[1] if len(b) > 1 else None))
                    for b in (theme.badges or theme.segments)] or [(None, None)]
    badge_w = min(max(cell_width(h.badge) for h in headlines), 10)
    sources: dict[str, int] = {}
    for h in headlines:
        idx = sources.setdefault(h.source, len(sources))
        age = f" {glyphs.dot.strip()} {format_age(now - h.published)}" if show_age and h.published else ""
        badge = ""
        if show_source:
            badge_text = truncate(h.badge, badge_w, "")
            if painter.enabled:
                bg, fg = badge_colors[idx % len(badge_colors)]
                badge = painter.paint(f" {badge_text.ljust(badge_w)} ", fg=fg, bg=bg)
            else:
                badge = f"[{badge_text}]".ljust(badge_w + 2)
        lead = cell_width(glyphs.bullet) + 1 + (badge_w + 3 if show_source else 0)
        room = cols - lead - cell_width(age)
        if room < 12:
            age, room = "", cols - lead
        title = truncate(h.title, room, glyphs.ellipsis)
        line = (painter.paint(glyphs.bullet, accent_c) + " " + (badge + " " if show_source else "")
                + hyperlink(painter.paint(title, text_c), h.link, links) + painter.paint(age, muted_c))
        out.append(line)
    return out


# -- system ------------------------------------------------------------------------------

def _heading(label_key: str, label: str, theme: Theme, glyphs: Glyphs, painter: Painter, cols: int) -> str:
    icon = glyphs.icon(label_key)
    text = f"{icon} {label}" if icon else label
    out = painter.paint(text, parse_color(theme.title), bold=True)
    rule = cols - cell_width(text) - 1
    if rule > 0:
        out += " " + painter.paint(("-" if glyphs.name == "ascii" else "─") * rule, parse_color(theme.muted))
    return out


def system_block(info, system_cfg: dict, theme: Theme, glyphs: Glyphs, painter: Painter, cols: int,
                 tz: str | None = None, private: bool = False) -> list[str]:
    """Ubuntu-login-message-style facts as a themed grid, plus alert lines.

    Privacy mode keeps only harmless percentages and counts: no addresses, no
    last-login source, no hardware totals and no patch / restart status."""
    from .sysinfo import local_time
    from .sysstat import ITEMS, human

    if info is None:
        return []
    items = [k for k in ITEMS if k in system_cfg.get("items", ITEMS)]
    bars = system_cfg.get("bars", True)
    muted, text_c, accent = parse_color(theme.muted), parse_color(theme.text), parse_color(theme.accent)
    ok, crit = parse_color(theme.title), parse_color("bright_red")

    cells: list[tuple[str, str, str, float | None]] = []  # icon key, label, value, percent
    for key in items:
        if key == "load" and info.load:
            cells.append(("load", "Load", " ".join(f"{v:.2f}" for v in info.load), None))
        elif key in ("disk", "memory", "swap") and getattr(info, key):
            used, total = getattr(info, key)
            pct = used / total * 100 if total else 0.0
            cells.append((key, {"disk": "Disk /", "memory": "Memory", "swap": "Swap"}[key],
                          f"{pct:.0f}%" if private else f"{pct:.0f}% of {human(total)}", pct))
        elif key == "processes" and info.processes is not None:
            cells.append(("processes", "Processes", str(info.processes), None))
        elif key == "users" and info.users is not None:
            cells.append(("users", "Users", str(info.users), None))
        elif key == "network" and not private:
            cells += [("network", iface, addr, None) for iface, addr in info.addresses]

    lines: list[str] = []
    if cells:
        bar_w = 10 if bars else 0
        on, off = ("#", "-") if glyphs.name == "ascii" else ("▰", "▱")
        label_w = max(cell_width(label) for _, label, _, _ in cells)
        icon_w = 2 if glyphs.nerd else 0

        def cell(icon_key: str, label: str, value: str, pct: float | None) -> tuple[str, int]:
            parts, width = [], 0
            if icon_w:
                parts.append(painter.paint(glyphs.icon(icon_key) + " ", muted))
                width += icon_w
            parts.append(painter.paint(label.ljust(label_w), muted) + "  ")
            width += label_w + 2
            if pct is not None and bar_w:
                filled = min(max(round(pct / 100 * bar_w), 0), bar_w)
                color = crit if pct >= 90 else accent if pct >= 75 else ok
                parts.append(painter.paint(on * filled, color) + painter.paint(off * (bar_w - filled), muted) + " ")
                width += bar_w + 1
            parts.append(painter.paint(value, text_c))
            return "".join(parts), width + cell_width(value)

        rendered = [cell(*c) for c in cells]
        cell_w = max(w for _, w in rendered)
        gap, indent = 4, 2
        columns = max(1, min(3, (cols - indent + gap) // (cell_w + gap)))
        rows = -(-len(rendered) // columns)
        for r in range(rows):
            row, used = " " * indent, indent
            for c in range(columns):
                i = c * rows + r
                if i >= len(rendered):
                    break
                text, w = rendered[i]
                if used + w > cols:
                    break
                pad = " " * (cell_w + gap - w) if c < columns - 1 else ""
                row += text + pad
                used += w + len(pad)
            lines.append(row.rstrip())

    alerts: list[tuple[str, str, object]] = []
    sep = " - " if glyphs.name == "ascii" else " · "
    if system_cfg.get("alerts", True) and not private:
        if info.updates:
            msg = f"{info.updates} updates can be applied"
            if info.security:
                msg += f" ({info.security} security)"
            if info.esm:
                msg += f"{sep}{info.esm} more with ESM Apps"
            alerts.append(("updates", msg + f"{sep}apt list --upgradable", accent))
        elif info.esm:
            alerts.append(("updates", f"{info.esm} security updates available with ESM Apps", accent))
        if info.restart:
            why = f" ({', '.join(info.restart_pkgs[:2])}{', ...' if len(info.restart_pkgs) > 2 else ''})" \
                if info.restart_pkgs else ""
            alerts.append(("restart", "System restart required" + why, crit))
        if info.release:
            alerts.append(("release", info.release, accent))
    bullet = glyphs.bullet
    for icon_key, msg, color in alerts:
        icon = glyphs.icon(icon_key) or bullet
        lines.append("  " + painter.paint(truncate(f"{icon} {msg}", cols - 2, glyphs.ellipsis), color,
                                          bold=icon_key == "restart"))
    if system_cfg.get("last_login", True) and info.last_login and not private:
        import time as _time

        when, host = info.last_login
        stamp = _time.strftime("%a %d %b %H:%M", local_time(when, tz))
        icon = glyphs.icon("login")
        msg = f"{icon + ' ' if icon else ''}Last login {stamp}" + (f" from {host}" if host else "")
        lines.append("  " + painter.paint(truncate(msg, cols - 2, glyphs.ellipsis), muted))
    if not lines:
        return []
    return [_heading("system", "System", theme, glyphs, painter, cols)] + lines


def compose(*, header: str, system: list[str], art: list[str], notice: list[str],
            news: list[str]) -> tuple[str, dict[str, tuple[int, int]]]:
    """-> (text, {section: (first line, end line)}); animations use the ranges."""
    lines: list[str] = []
    where: dict[str, tuple[int, int]] = {}
    if header:
        where["header"] = (0, 1)
        lines += [header, ""]
    for name, section in (("system", system), ("art", art or notice), ("news", news)):
        if not section:
            continue
        if len(lines) > (2 if header else 0):
            lines.append("")
        where[name] = (len(lines), len(lines) + len(section))
        lines += section
    return "\n".join(lines) + "\n", where


BANNER = r"""
 __  __  ___ _____ ___    _
|  \/  |/ _ \_   _|   \ _| |_
| |\/| | (_) || | | |) |_   _|
|_|  |_|\___/ |_| |___/  |_|
""".strip("\n")


def first_run_notice(painter: Painter, theme: Theme, glyphs: Glyphs, cols: int) -> list[str]:
    note = "No art cached yet - fetching some in the background (or run: motdplus refresh)"
    out = []
    if cols >= 32:
        color_at = art_color_fn(theme.art_style, theme.art_colors, theme.art_direction, 30, 4)
        out += [_colorize(line, y, color_at, painter, parse_color(theme.text)) for y, line in enumerate(BANNER.split("\n"))]
        out.append("")
    out.append(painter.paint(truncate(note, cols, glyphs.ellipsis), parse_color(theme.muted)))
    return out

