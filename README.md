<h1 align="center">TIS - The Image Scrapper</h1>

<p align="center">
  <b>Download Images by term search, just like in a common browse but automatically
</p>


---

### Why another scrapper?

Commonly, the scrappers work excellent for text scrapping. However, several projects are currently outdated and lacks of enough support to properly scrap and download images.

Also, when scrapping images, you normally want to scrap of specific topic, for doing that is commonly messy and very disordered.

The Image Scrapper solves this through 2 important things.

- Support to download Images from Google Images (Supported at least at September 2026).
- Collect Images by term search and some other specific filter like image resolution.


## How it works?

The Image Scrapper has a like-browser process and is intended in that way to keep it as simple as: 

<p align="center">
  <b>You put a term, you get images of that term.
</p>


## Which are the sources?

For now, it's limited to only Google Images, is intended to evolve to get images from more resources.

- Google Images


## Install

Python **3.12**. From the repo root:

```bash
python -m venv venv
venv\Scripts\activate.bat

pip install -e .
playwright install chromium
```

> [!NOTE]
> `pip install -e .` installs the runtime deps (`playwright`, `httpx`,
`SQLAlchemy`, `pillow`, `imagehash`) from `pyproject.toml`; a matching
`requirements.txt` is provided too. `playwright install chromium` downloads the
browser used for harvesting (one-time).


## Usage

```bash
imagegrab "Ferrari Italia" --count 20 --min-resolution 1080p
```

| Option             | Default        | Meaning                                                        |
| ------------------ | -------------- | -------------------------------------------------------------- |
| `query`            | —              | Positional search term.                                        |
| `--count`          | `50`           | Images to **keep** after filtering (clamped `1..1000`).        |
| `--min-resolution` | `none`         | `none` / `480p` / `720p` / `1080p` / `4k`.                     |
| `--out`            | `images`       | Output folder for kept images.                                 |
| `--db`             | `imagegrab.db` | SQLite manifest path.                                          |
| `--headful`        | off            | Show the browser (required to solve a CAPTCHA by hand).         |
| `--profile-dir`    | none           | Persistent browser profile — remembers consent + CAPTCHA solves.|
| `--concurrency`    | `20`           | Max simultaneous downloads.                                    |
| `--pace`           | `1.0`          | Seconds between thumbnail clicks while harvesting.             |

`--count` is the number of images **kept** after de-duplication and the
resolution filter — the tool over-harvests to absorb losses. It is a ceiling:
Google itself usually yields only a few hundred images per term.

## How it works — the harvest/download split

Google Images is JavaScript-rendered, so harvesting needs a real browser
(Playwright). It does **not** click results — each grid tile is a link that
would navigate away; instead it scrolls the grid and reads the origin URL
straight out of each tile's `<a href="/imgres?imgurl=...">`. And scraping is
fundamentally just *harvesting URL strings*: once a full-res origin URL is
captured, downloading it is a plain HTTP GET with no browser. v1 is built around
that split:

```
harvest (Playwright -> Google)     SQLite manifest       download (async httpx)
  full-res URL strings       ->     status=pending   ->   no browser needed
                                                          | decode + filter
                          files on disk  <-  keep/discard (dedup + resolution)
```

De-duplication runs cheapest-first: exact URL (a UNIQUE column) -> exact bytes
(SHA-256) -> near-duplicate (perceptual hash, Hamming distance <= 5). The
resolution filter is authoritative on the decoded bytes: an image passes a tier
when `min(width, height) >= tier`.

Everything is **resumable**: the SQLite manifest records every URL and outcome,
so re-running a query skips what's already done and tops up toward `--count`.

## Google, CAPTCHAs, and the manual-solve workflow

Google aggressively fingerprints automation and often serves a `/sorry`
"unusual traffic" + reCAPTCHA page — sometimes on the very first request, even
from a normal residential connection. The tool does **not** try to solve or
bypass it. Instead:

- In **headful** mode it detects the CAPTCHA, pauses, and prints a message; you
  solve it by hand in the browser window and harvesting resumes automatically.
- In **headless** mode it can't be solved, so the run stops with a message
  telling you to re-run with `--headful`.

Pair it with `--profile-dir` so the solved-exemption and consent cookies persist
between runs — after the first manual solve, later runs often skip the CAPTCHA
entirely:

```bash
imagegrab "Ferrari Italia" --count 20 --headful --profile-dir chrome-profile
```

Use a **dedicated** folder for `--profile-dir`, not your everyday Chrome profile.
The profile stores cookies/session data and is git-ignored.

> Reality check: this makes Google *usable* but semi-manual (you're on standby
> to solve a challenge). For hands-off bulk collection, a server-rendered source
> like Bing (roadmap Phase 4) is the better long-term default; Google is "the one
> fragile source."

## Notes / caveats

- Downloaded images carry
  their own copyright, you are responsible of the usage given to that images.
- Datacenter IP's might be blocked automatically, making TIS unusable.
