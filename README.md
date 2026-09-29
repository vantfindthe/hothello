# motd+

A different piece of ASCII art at every login, picked from
[Christopher Johnson's ASCII Art Collection](https://asciiart.website/browse.php),
with news headlines underneath and an oh-my-posh-style header, all fitted to your screen.

## Install

```bash
cd ~/motd-plus
python3 -m venv .venv            # on Ubuntu without python3-venv: python3 -m venv --without-pip .venv
                                 #   && curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
.venv/bin/pip install -e .
.venv/bin/motdplus install       # adds the login hook and downloads a first batch of art + news
```

Then open the settings UI:

```bash
.venv/bin/motdplus
```

## The settings UI

| Tab | What you control |
|---|---|
| **Art** | Which of the ~630 categories to cycle (space checks a category or a whole group; nothing checked = all), shuffle / rotate / random, every login / hourly / daily, prefer bigger pieces, hide flagged content, fetch more now |
| **Display** | Screen size: fit the terminal, fit width only, or fixed presets (40x12 for phones up to 200x60), custom size, smallest art worth showing, rows kept for your prompt, frame style, alignment, crop-or-skip when nothing fits |
| **News** | 37 built-in feeds (BBC, NPR, Guardian, NYT, Al Jazeera, DW, PBS, Economist, Ars Technica, Nature, NASA ...), your own RSS/Atom feeds (checked before they're added), how many headlines, per-source cap, max age, refresh interval, clickable OSC 8 links |
| **System** | A themed version of Ubuntu's login message: load, disk / memory / swap with usage bars, processes, users, IP addresses, pending updates, *restart required*, new-release notice and last login. Includes the `~/.hushlogin` switch that hides the plain system version so it isn't shown twice |
| **Theme** | 12 themes (Tokyo Night, Catppuccin, Dracula, Gruvbox, Nord, Solarized, Synthwave, Matrix, Amber CRT ...), glyph set (Nerd Font / Powerline / Unicode / ASCII), colour depth (truecolor / 256 / 16 / none), art colouring (gradient, rainbow ...), header segments (incl. kernel), greeting, date format, timezone, **import an oh-my-posh theme** |
| **Install** | Login hooks for bash, zsh, fish and PowerShell, and the system-wide `/etc/update-motd.d` hook |

Keys: `p` full-screen preview at your real terminal size · `n` next art · `f` fetch art and news · `q` quit.

## How it works

* **At login** the hook runs `motdplus show`: stdlib only, reads the local SQLite cache, prints, and exits
  (about 60 ms). It never touches the network, and it never fails your login: errors are swallowed
  (set `MOTDPLUS_DEBUG=1` to see them). It only runs in interactive shells, so `ssh host cmd`, scp and
  deploy scripts are unaffected.
* **In the background** it starts `motdplus refresh --if-due` (detached) when news is older than the refresh
  interval, when the unseen pool of fitting art runs low, or when you pick categories that were never fetched.
* **Art source**: public `cat.php` pages, each of which serves 20 random pieces of a category, fetched a few
  pages at a time with a pause between requests and an honest User-Agent. The cache grows gradually;
  the site's width/height and content flags are used for fitting and filtering.
* **Fitting**: everything (header, framed art, headlines, prompt rows) is budgeted into the screen size.
  On short screens headlines are dropped before the art is; if nothing cached fits, the closest piece is
  centre-cropped (or skipped, if you prefer).
* **Shuffle** never repeats a piece until every fitting piece in your selection has been shown.

## Commands

```
motdplus               settings UI
motdplus show          print the MOTD (what the hook runs)
motdplus preview       show the next MOTD without using it up
motdplus refresh       fetch art and headlines now (--art, --news, --catalog)
motdplus status        paths, cache size, feed health, hook status
motdplus themes        list themes; --import-omp [NAME|PATH] [--use]
motdplus categories    list categories (optionally filtered)
motdplus install / uninstall [--target bash|zsh|fish|pwsh|powershell|update-motd] [--hushlogin]
```

Config: `~/.config/motdplus/config.json` (user themes in `themes/`). Cache: `~/.cache/motdplus/motdplus.db`.

## System-wide (every user, via pam_motd)

```bash
sudo ~/motd-plus/.venv/bin/python -m motdplus install --target update-motd
```

This copies your config to `/var/lib/motdplus` and adds `/etc/update-motd.d/60-motdplus`. pam_motd has no
terminal to measure, so choose a fixed size (e.g. Classic 80x24) in the Display tab first.

## Tests

```bash
.venv/bin/pip install -e ".[dev]" && .venv/bin/pytest
```

Art is © its artists and credited on every MOTD with a link back to asciiart.website.
