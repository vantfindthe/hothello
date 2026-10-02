"""Colours, glyph sets and themes (oh-my-posh style powerline segments).

A theme is plain JSON-able data; user themes live in <config>/themes/*.json and
can be written by hand or imported from an oh-my-posh config.
"""

from __future__ import annotations

import colorsys
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths

RESET = "\x1b[0m"

ANSI_NAMES = [
    "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
    "bright_black", "bright_red", "bright_green", "bright_yellow",
    "bright_blue", "bright_magenta", "bright_cyan", "bright_white",
]
# xterm defaults, used only to approximate hex colours on 16-colour terminals.
_ANSI_RGB = [
    (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205),
    (0, 205, 205), (229, 229, 229), (127, 127, 127), (255, 0, 0), (0, 255, 0),
    (255, 255, 0), (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
]
_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

RGB = tuple[int, int, int]
Color = tuple[str, object] | None  # ("rgb", (r, g, b)) | ("ansi", index) | None = terminal default


def parse_color(spec: str | None) -> Color:
    if not spec or spec == "default":
        return None
    spec = spec.strip()
    if spec.lower() in ANSI_NAMES:
        return ("ansi", ANSI_NAMES.index(spec.lower()))
    m = _HEX.match(spec)
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return ("rgb", (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))


def _dist(a: RGB, b: RGB) -> float:
    rmean = (a[0] + b[0]) / 2
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return (2 + rmean / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rmean) / 256) * db * db


def rgb_to_256(rgb: RGB) -> int:
    levels = [0, 95, 135, 175, 215, 255]

    def q(v: int) -> int:
        return 0 if v < 48 else 1 if v < 115 else (v - 35) // 40

    ci = [q(v) for v in rgb]
    cube = tuple(levels[i] for i in ci)
    avg = sum(rgb) // 3
    gi = 23 if avg > 238 else max(0, (avg - 3) // 10)
    gray = 8 + 10 * gi
    if _dist(rgb, cube) <= _dist(rgb, (gray, gray, gray)):
        return 16 + 36 * ci[0] + 6 * ci[1] + ci[2]
    return 232 + gi


def rgb_to_16(rgb: RGB) -> int:
    return min(range(16), key=lambda i: _dist(rgb, _ANSI_RGB[i]))


def to_hex(rgb: RGB) -> str:
    return "#%02x%02x%02x" % rgb


def lerp(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def gradient(stops: list[RGB], t: float) -> RGB:
    if len(stops) == 1:
        return stops[0]
    t = min(max(t, 0.0), 1.0) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    return lerp(stops[i], stops[i + 1], t - i)


def rainbow(i: float) -> RGB:
    r, g, b = colorsys.hsv_to_rgb((i % 1.0), 0.65, 1.0)
    return (round(r * 255), round(g * 255), round(b * 255))


class Painter:
    """Turns colours into SGR sequences for a given colour depth."""

    def __init__(self, depth: str):
        self.depth = depth  # truecolor | 256 | 16 | none
        self._cache: dict = {}

    @property
    def enabled(self) -> bool:
        return self.depth != "none"

    def _code(self, color: Color, background: bool) -> str:
        if color is None or self.depth == "none":
            return ""
        key = (color, background)
        if key in self._cache:
            return self._cache[key]
        kind, value = color
        if kind == "ansi":
            n = int(value)  # type: ignore[arg-type]
            code = str((40 if background else 30) + n) if n < 8 else str((100 if background else 90) + n - 8)
        elif self.depth == "truecolor":
            code = f"{48 if background else 38};2;{value[0]};{value[1]};{value[2]}"  # type: ignore[index]
        elif self.depth == "256":
            code = f"{48 if background else 38};5;{rgb_to_256(value)}"  # type: ignore[arg-type]
        else:
            n = rgb_to_16(value)  # type: ignore[arg-type]
            code = str((40 if background else 30) + n) if n < 8 else str((100 if background else 90) + n - 8)
        self._cache[key] = code
        return code

    def sgr(self, fg: Color = None, bg: Color = None, bold: bool = False) -> str:
        if self.depth == "none":
            return ""
        codes = [c for c in (("1" if bold else ""), self._code(fg, False), self._code(bg, True)) if c]
        return f"\x1b[{';'.join(codes)}m" if codes else ""

    def paint(self, text: str, fg: Color = None, bg: Color = None, bold: bool = False) -> str:
        seq = self.sgr(fg, bg, bold)
        return f"{seq}{text}{RESET}" if seq and text else text


# -- glyph sets ----------------------------------------------------------------------

SEPARATORS = {  # style: (start cap, between segments, end cap)
    "powerline": ("", "", ""),
    "round": ("", "", ""),
    "slant": ("", "", ""),
    "flame": ("", "", ""),
    "none": ("", "", ""),
}

NERD_ICONS = {
    "day": "", "night": "", "user": "", "host": "",
    "windows": "", "linux": "", "mac": "", "os": "",
    "datetime": "", "uptime": "", "shell": "",
    "category": "", "news": "", "kernel": "",
    "system": "", "load": "", "disk": "", "memory": "", "swap": "",
    "processes": "", "users": "", "network": "", "updates": "",
    "restart": "", "release": "", "login": "",
}


@dataclass
class Glyphs:
    name: str
    powerline: bool  # E0B0 family available
    nerd: bool  # full Nerd Font (icons, rounded/slanted separators)
    bullet: str
    ellipsis: str
    dot: str  # separator between header items when there is no colour

    def separators(self, style: str) -> tuple[str, str, str]:
        if not self.powerline:
            return SEPARATORS["none"]
        if not self.nerd and style != "none":
            return SEPARATORS["powerline"]
        return SEPARATORS.get(style, SEPARATORS["powerline"])

    def icon(self, key: str) -> str:
        return NERD_ICONS.get(key, "") if self.nerd else ""


GLYPH_SETS = {
    "nerd": Glyphs("nerd", True, True, "", "…", " · "),
    "powerline": Glyphs("powerline", True, False, "▸", "…", " · "),
    "unicode": Glyphs("unicode", False, False, "▸", "…", " · "),
    "ascii": Glyphs("ascii", False, False, "*", "...", " | "),
}


def resolve_glyphs(setting: str) -> Glyphs:
    if setting in GLYPH_SETS:
        return GLYPH_SETS[setting]
    env = os.environ
    if env.get("POSH_THEME") or env.get("POSH_SESSION_ID") or env.get("STARSHIP_SHELL") or env.get("NERD_FONT"):
        return GLYPH_SETS["nerd"]
    return GLYPH_SETS["nerd" if _prompt_engine_installed() else "unicode"]


def _prompt_engine_installed() -> bool:
    """oh-my-posh / starship on PATH (they need a Nerd Font anyway).  Searching a long
    PATH costs tens of milliseconds on Windows, so the answer is cached for a day."""
    import time

    cache = paths.cache_dir() / "detect.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if time.time() - data["at"] < 86400:
            return bool(data["prompt_engine"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    found = bool(shutil.which("oh-my-posh") or shutil.which("starship"))
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"prompt_engine": found, "at": time.time()}), encoding="utf-8")
    except OSError:
        pass
    return found


FRAME_CHARS = {  # tl, tr, bl, br, horizontal, vertical
    "single": "┌┐└┘─│",
    "rounded": "╭╮╰╯─│",
    "double": "╔╗╚╝═║",
    "heavy": "┏┓┗┛━┃",
    "ascii": "++++-|",
}


# -- themes --------------------------------------------------------------------------------

@dataclass
class Theme:
    key: str
    name: str
    separator: str = "powerline"
    segments: list[list[str]] = field(default_factory=lambda: [["blue", "bright_white"]])  # [bg, fg]
    art_style: str = "plain"  # plain | solid | gradient | rainbow
    art_colors: list[str] = field(default_factory=list)
    art_direction: str = "vertical"  # vertical | horizontal | diagonal
    frame: str | None = None
    title: str | None = None
    text: str | None = None
    muted: str | None = "bright_black"
    accent: str | None = None
    badges: list[list[str]] | None = None
    source: str = "built-in"

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("key")
        d.pop("source")
        return d

    @classmethod
    def from_dict(cls, key: str, data: dict, source: str = "built-in") -> "Theme":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k not in ("key", "source")}
        return cls(key=key, source=source, **known)


def _t(key: str, name: str, sep: str, segs: list, style: str, art: list, direction: str,
       frame: str, title: str, text: str, muted: str, accent: str) -> Theme:
    return Theme(key, name, sep, [list(s) for s in segs], style, art, direction, frame, title, text, muted, accent)


BUILTIN_THEMES: dict[str, Theme] = {t.key: t for t in [
    _t("tokyo-night", "Tokyo Night", "round",
       [("#7aa2f7", "#1a1b26"), ("#bb9af7", "#1a1b26"), ("#7dcfff", "#1a1b26"),
        ("#9ece6a", "#1a1b26"), ("#e0af68", "#1a1b26"), ("#f7768e", "#1a1b26")],
       "gradient", ["#7dcfff", "#7aa2f7", "#bb9af7", "#f7768e"], "diagonal",
       "#565f89", "#7aa2f7", "#c0caf5", "#565f89", "#e0af68"),
    _t("catppuccin-mocha", "Catppuccin Mocha", "round",
       [("#cba6f7", "#11111b"), ("#f5c2e7", "#11111b"), ("#89b4fa", "#11111b"),
        ("#94e2d5", "#11111b"), ("#a6e3a1", "#11111b"), ("#fab387", "#11111b")],
       "gradient", ["#f5c2e7", "#cba6f7", "#89b4fa", "#94e2d5"], "vertical",
       "#6c7086", "#cba6f7", "#cdd6f4", "#7f849c", "#f9e2af"),
    _t("catppuccin-latte", "Catppuccin Latte (light)", "round",
       [("#8839ef", "#eff1f5"), ("#1e66f5", "#eff1f5"), ("#179299", "#eff1f5"),
        ("#40a02b", "#eff1f5"), ("#fe640b", "#eff1f5"), ("#d20f39", "#eff1f5")],
       "gradient", ["#8839ef", "#1e66f5", "#179299"], "vertical",
       "#9ca0b0", "#8839ef", "#4c4f69", "#8c8fa1", "#df8e1d"),
    _t("dracula", "Dracula", "powerline",
       [("#bd93f9", "#282a36"), ("#ff79c6", "#282a36"), ("#8be9fd", "#282a36"),
        ("#50fa7b", "#282a36"), ("#ffb86c", "#282a36"), ("#f1fa8c", "#282a36")],
       "gradient", ["#ff79c6", "#bd93f9", "#8be9fd"], "horizontal",
       "#6272a4", "#ff79c6", "#f8f8f2", "#6272a4", "#50fa7b"),
    _t("gruvbox", "Gruvbox", "powerline",
       [("#d79921", "#282828"), ("#98971a", "#282828"), ("#458588", "#ebdbb2"),
        ("#b16286", "#ebdbb2"), ("#689d6a", "#282828"), ("#d65d0e", "#282828")],
       "gradient", ["#fabd2f", "#fe8019", "#fb4934"], "vertical",
       "#7c6f64", "#fabd2f", "#ebdbb2", "#928374", "#8ec07c"),
    _t("nord", "Nord", "slant",
       [("#5e81ac", "#eceff4"), ("#81a1c1", "#2e3440"), ("#88c0d0", "#2e3440"),
        ("#8fbcbb", "#2e3440"), ("#a3be8c", "#2e3440"), ("#b48ead", "#2e3440")],
       "gradient", ["#8fbcbb", "#88c0d0", "#81a1c1", "#5e81ac"], "vertical",
       "#616e88", "#88c0d0", "#d8dee9", "#616e88", "#ebcb8b"),
    _t("solarized-dark", "Solarized Dark", "powerline",
       [("#268bd2", "#fdf6e3"), ("#2aa198", "#002b36"), ("#859900", "#002b36"),
        ("#b58900", "#002b36"), ("#cb4b16", "#fdf6e3"), ("#6c71c4", "#fdf6e3")],
       "gradient", ["#2aa198", "#268bd2", "#6c71c4", "#d33682"], "diagonal",
       "#586e75", "#268bd2", "#93a1a1", "#586e75", "#b58900"),
    _t("synthwave", "Synthwave '84", "flame",
       [("#ff7edb", "#262335"), ("#36f9f6", "#262335"), ("#fede5d", "#262335"),
        ("#f97e72", "#262335"), ("#72f1b8", "#262335"), ("#b893ce", "#262335")],
       "rainbow", [], "diagonal",
       "#ff7edb", "#36f9f6", "#ffffff", "#848bbd", "#fede5d"),
    _t("matrix", "Matrix", "slant",
       [("#00ff41", "#0d0208"), ("#008f11", "#e0ffe0"), ("#003b00", "#00ff41")],
       "gradient", ["#b6ffb6", "#00ff41", "#008f11"], "vertical",
       "#008f11", "#00ff41", "#b6ffb6", "#2e7d32", "#00ff41"),
    _t("amber-crt", "Amber CRT", "powerline",
       [("#ffb000", "#1a1000"), ("#cc8400", "#1a1000"), ("#7a5200", "#ffcc66")],
       "solid", ["#ffb000"], "vertical",
       "#7a5200", "#ffcc00", "#ffb000", "#8a6a2a", "#ffcc00"),
    _t("classic", "Classic (your terminal's 16 colours)", "powerline",
       [("blue", "bright_white"), ("magenta", "bright_white"), ("cyan", "black"),
        ("green", "black"), ("yellow", "black"), ("red", "bright_white")],
       "solid", ["bright_cyan"], "vertical",
       "bright_black", "bright_cyan", "default", "bright_black", "yellow"),
    _t("mono", "Monochrome", "powerline",
       [("white", "black"), ("bright_black", "bright_white")],
       "plain", [], "vertical",
       "bright_black", "default", "default", "bright_black", "default"),
]}

DEFAULT_THEME = "tokyo-night"


def user_themes() -> dict[str, Theme]:
    out: dict[str, Theme] = {}
    folder = paths.themes_dir()
    if not folder.is_dir():
        return out
    for f in sorted(folder.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out[f.stem] = Theme.from_dict(f.stem, data, source=str(f))
        except (OSError, ValueError, TypeError):
            continue
    return out


def all_themes() -> dict[str, Theme]:
    return {**BUILTIN_THEMES, **user_themes()}


def get_theme(key: str) -> Theme:
    if key in BUILTIN_THEMES:
        return BUILTIN_THEMES[key]
    path = paths.themes_dir() / f"{key}.json"
    try:
        return Theme.from_dict(key, json.loads(path.read_text(encoding="utf-8")), source=str(path))
    except (OSError, ValueError, TypeError):
        return BUILTIN_THEMES[DEFAULT_THEME]


def save_user_theme(theme: Theme) -> Path:
    folder = paths.themes_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{theme.key}.json"
    path.write_text(json.dumps(theme.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


# -- oh-my-posh import --------------------------------------------------------------------------

_OMP_NAMES = {
    "black": "black", "red": "red", "green": "green", "yellow": "yellow", "blue": "blue",
    "magenta": "magenta", "cyan": "cyan", "white": "white", "darkgray": "bright_black",
    "lightred": "bright_red", "lightgreen": "bright_green", "lightyellow": "bright_yellow",
    "lightblue": "bright_blue", "lightmagenta": "bright_magenta", "lightcyan": "bright_cyan",
    "lightwhite": "bright_white",
}
_OMP_INIT = re.compile(r"oh-my-posh(?:\.exe)?\s+init\s+\S+.*?(?:--config|-c)[\s=]+['\"]?([^'\"\s|;)]+)", re.I)


def detect_omp_config() -> str | None:
    """Best guess at the oh-my-posh config this user runs: $POSH_THEME, or the
    --config argument of the `oh-my-posh init` line in a shell profile."""
    if env := os.environ.get("POSH_THEME"):
        return env
    home = Path.home()
    candidates = [home / ".bashrc", home / ".zshrc", home / ".config" / "fish" / "config.fish"]
    if os.name == "nt":
        from .hooks import documents_dir
        docs = documents_dir()
        for folder in ("WindowsPowerShell", "PowerShell"):
            candidates += [docs / folder / "Microsoft.PowerShell_profile.ps1", docs / folder / "profile.ps1"]
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        if m := _OMP_INIT.search(text):
            return os.path.expandvars(m.group(1))
    return None


def _load_omp(source: str) -> dict:
    path = Path(os.path.expandvars(source)).expanduser()
    if path.is_file():
        raw = path.read_text(encoding="utf-8-sig")
        if path.suffix.lower() == ".toml":
            import tomllib
            return tomllib.loads(raw)
        if path.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore[import-not-found]
            except ImportError as e:
                raise ValueError("YAML themes need PyYAML (pip install pyyaml), or export to JSON") from e
            return yaml.safe_load(raw)
        return json.loads(raw)
    exe = shutil.which("oh-my-posh")
    if not exe:
        raise ValueError(f"{source!r} is not a file and oh-my-posh is not on PATH")
    proc = subprocess.run(
        [exe, "config", "export", "--config", source, "--format", "json"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ValueError((proc.stderr or proc.stdout or "oh-my-posh config export failed").strip()[:300])
    return json.loads(proc.stdout)


def theme_from_omp(data: dict, key: str, name: str) -> Theme:
    palette = data.get("palette") or {}

    def resolve(value, depth: int = 0) -> str | None:
        if not isinstance(value, str) or depth > 4:
            return None
        v = value.strip()
        if v.startswith("p:"):
            return resolve(palette.get(v[2:]), depth + 1)
        if _HEX.match(v):
            return v if v.startswith("#") else "#" + v
        return _OMP_NAMES.get(v.lower().replace("_", ""))

    segments: list[list[str]] = []
    accents: list[str] = []
    glyphs = ""
    for block in data.get("blocks", []):
        for seg in block.get("segments", []):
            glyphs += "".join(str(seg.get(k, "")) for k in ("powerline_symbol", "leading_diamond", "trailing_diamond"))
            bg, fg = resolve(seg.get("background")), resolve(seg.get("foreground"))
            if bg:
                pair = [bg, fg or "#ffffff"]
                if not segments or segments[-1] != pair:
                    segments.append(pair)
            elif fg:
                accents.append(fg)
    if not segments:
        if not accents:
            raise ValueError("no usable colours found in that oh-my-posh config")
        segments = [[c, "#000000"] for c in accents[:6]]

    if "" in glyphs or "" in glyphs:
        separator = "round"
    elif any(g in glyphs for g in ("", "", "", "")):
        separator = "slant"
    elif "" in glyphs or "" in glyphs:
        separator = "flame"
    else:
        separator = "powerline"

    bgs = [s[0] for s in segments]

    def vivid(spec: str) -> float:
        c = parse_color(spec)
        if not c or c[0] != "rgb":
            return 0.0
        r, g, b = (v / 255 for v in c[1])  # type: ignore[union-attr]
        return colorsys.rgb_to_hsv(r, g, b)[1]

    art = [c for c in dict.fromkeys(bgs + accents) if vivid(c) > 0.35][:4] or bgs[:3]
    grays = [c for c in bgs if vivid(c) < 0.15]
    return Theme(
        key=key, name=name, separator=separator, segments=segments,
        art_style="gradient" if len(art) > 1 else "solid", art_colors=art, art_direction="diagonal",
        frame=grays[0] if grays else "bright_black", title=art[0], text="default",
        muted="bright_black", accent=(accents or art)[0], source="oh-my-posh",
    )


def import_omp(source: str) -> Theme:
    data = _load_omp(source)
    stem = Path(source).name.split(".")[0] or "theme"
    key = "omp-" + re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    theme = theme_from_omp(data, key, f"oh-my-posh: {stem}")
    save_user_theme(theme)
    return theme


# -- art colouring -----------------------------------------------------------------------------

def art_color_fn(style: str, colors: list[str], direction: str, width: int, height: int):
    """-> f(x, y) giving a Color for the character at column x, row y (or None)."""
    parsed = [parse_color(c) for c in colors]
    if style == "rainbow":
        spread = max(width + height * 2, 1)
        return lambda x, y: ("rgb", rainbow((x + y * 2) / spread * 1.3))
    if style == "plain" or not parsed or all(p is None for p in parsed):
        return None
    if style == "solid" or len(parsed) == 1:
        c = parsed[0]
        return lambda x, y: c
    stops = [p[1] for p in parsed if p and p[0] == "rgb"]
    if len(stops) != len(parsed):  # named colours can't be blended: stripe by row
        return lambda x, y: parsed[y % len(parsed)]
    w, h = max(width - 1, 1), max(height - 1, 1)
    steps = 48  # quantise so neighbouring cells share an escape sequence
    table = [("rgb", gradient(stops, i / steps)) for i in range(steps + 1)]  # type: ignore[arg-type]
    if direction == "horizontal":
        return lambda x, y: table[round(x / w * steps)]
    if direction == "diagonal":
        return lambda x, y: table[round((x / w + y / h) / 2 * steps)]
    return lambda x, y: table[round(y / h * steps)]

