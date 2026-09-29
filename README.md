# hothello

A different piece of ASCII art at every login, picked from
[Christopher Johnson's ASCII Art Collection](https://asciiart.website/browse.php),
with news headlines underneath and an oh-my-posh-style header, all fitted to your screen.

## Install

```bash
cd ~/hothello
python3 -m venv .venv            # on Ubuntu without python3-venv: python3 -m venv --without-pip .venv
                                 #   && curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
.venv/bin/pip install -e .
.venv/bin/hothello install       # adds the login hook and downloads a first batch of art + news
```

Then open the settings UI:

```bash
.venv/bin/hothello
```

## The settings UI

| Tab | What you control |
|---|---|
| **Art** | Which of the ~630 categories to cycle (space checks a category or a whole group; nothing checked = all), shuffle / rotate / random, every login / hourly / daily, prefer bigger pieces, hide flagged content, fetch more now |
| **Display** | Screen size: fit the terminal, fit width only, or fixed presets (40x12 for phones up to 200x60), custom size, smallest art worth showing, rows kept for your prompt, frame style, alignment, crop-or-skip when nothing fits, art name / source on or off, **login animation** (style, speed, all or art only) |
| **News** | 37 built-in feeds (BBC, NPR, Guardian, NYT, Al Jazeera, DW, PBS, Economist, Ars Technica, Nature, NASA ...), your own RSS/Atom feeds (checked before they're added), how many headlines, per-source cap, max age, refresh interval, clickable OSC 8 links |
| **System** | A themed version of Ubuntu's login message: load, disk / memory / swap with usage bars, processes, users, IP addresses, pending updates, *restart required*, new-release notice and last login. Includes the `~/.hushlogin` switch that hides the plain system version so it isn't shown twice, and **privacy mode** for screen recordings |
| **Theme** | 12 themes (Tokyo Night, Catppuccin, Dracula, Gruvbox, Nord, Solarized, Synthwave, Matrix, Amber CRT ...), glyph set (Nerd Font / Powerline / Unicode / ASCII), colour depth (truecolor / 256 / 16 / none), art colouring (gradient, rainbow ...), header segments (incl. kernel), greeting, date format, timezone, **import an oh-my-posh theme** |
| **Install** | Login hooks for bash, zsh, fish and PowerShell, and the system-wide `/etc/update-motd.d` hook |

Keys: `p` full-screen preview at your real terminal size · `a` play the animation · `n` next art · `f` fetch art and news · `q` quit.

## How it works

* **At login** the hook runs `hothello show`: stdlib only, reads the local SQLite cache, prints, and exits
  (about 60 ms). It never touches the network, and it never fails your login: errors are swallowed
  (set `HOTHELLO_DEBUG=1` to see them). It only runs in interactive shells, so `ssh host cmd`, scp and
  deploy scripts are unaffected.
* **In the background** it starts `hothello refresh --if-due` (detached) when news is older than the refresh
  interval, when the unseen pool of fitting art runs low, or when you pick categories that were never fetched.
* **Art source**: public `cat.php` pages, each of which serves 20 random pieces of a category, fetched a few
  pages at a time with a pause between requests and an honest User-Agent. The cache grows gradually;
  the site's width/height and content flags are used for fitting and filtering.
* **Fitting**: everything (header, framed art, headlines, prompt rows) is budgeted into the screen size.
  On short screens headlines are dropped before the art is; if nothing cached fits, the closest piece is
  centre-cropped (or skipped, if you prefer).
* **Shuffle** never repeats a piece until every fitting piece in your selection has been shown.

## Commands

Everything in the settings UI can also be done from the command line. Commands that take a choice list the
options with a small live example when you leave the choice off, and accept any unique prefix
(`hothello theme gruv`).

```
hothello                         settings UI (also: hothello config)
hothello show | preview          print the MOTD; preview doesn't use up the art
                                 --private, --animate STYLE, --no-animate, --width/--height, --color, --glyphs

hothello features                every feature and whether it's on
hothello on|off|toggle NAME ...  show / hide features:  art headlines system header title credit frame
                                 badges ages links bars alerts lastlogin network privacy animation color
                                 flagged hushlogin   (e.g.  hothello off headlines credit)

hothello privacy [on|off]        for screen recordings: hides user and host names, IP addresses, the
                                 last-login address, OS/kernel versions, uptime, memory/disk totals and
                                 patch status  (--alias NAME; one session: HOTHELLO_PRIVACY=1)

hothello theme [NAME]            themes with examples     (--import-omp [NAME|PATH] for oh-my-posh)
hothello font [NAME]             glyph sets / fonts with examples: nerd, powerline, unicode, ascii
hothello color [MODE]            colour depth with examples: truecolor, 256, 16, none
hothello frame [STYLE]           frames with examples
hothello size [NAME|WxH]         screen size presets, or a custom size like 100x30
hothello cycle [MODE]            shuffle | rotate | random  --every login|hourly|daily  --prefer any|large
hothello categories [SEARCH]     --add / --remove / --only NAME|GROUP|ID ...   --clear   --selected
hothello feeds                   --add ID|URL  --remove ID|URL  --name NAME
hothello headlines               --count N  --per-source N  --max-age HOURS
hothello animation [STYLE]       none lines slide wipe rain decode nuke random   --speed  --target all|art
                                 --try plays one now without saving it
hothello greeting [TEXT]         e.g.  hothello greeting 'Hey {user}, {greeting}!'
hothello get [KEY] | set KEY VALUE | reset [SECTION] --yes

hothello refresh                 fetch art and headlines now (--art, --news, --catalog)
hothello status                  paths, cache size, feed health, hook status
hothello install | uninstall     [--target bash|zsh|fish|pwsh|powershell|update-motd] [--hushlogin]
```

Animations run only when the output is a terminal, never delay a login by more than a couple of seconds,
and any key skips them. They redraw only the characters that change, so they stay light over SSH, and the
real text is printed over the last frame so scrollback and links are intact.

Config: `~/.config/hothello/config.json` (user themes in `themes/`). Cache: `~/.cache/hothello/hothello.db`.

## System-wide (every user, via pam_motd)

```bash
sudo ~/hothello/.venv/bin/python -m hothello install --target update-motd
```

This copies your config to `/var/lib/hothello` and adds `/etc/update-motd.d/60-hothello`. pam_motd has no
terminal to measure, so choose a fixed size (e.g. Classic 80x24) in the Display tab first.

## Tests

```bash
.venv/bin/pip install -e ".[dev]" && .venv/bin/pytest
```

Art is © its artists and credited on every MOTD with a link back to asciiart.website.
