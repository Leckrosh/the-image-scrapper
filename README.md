<h1 align="center">TIS — The Image Scrapper</h1>

<p align="center">
  <b>Type a search term, get a folder of de-duplicated images — automatically.</b>
</p>

<p align="center">
  <sub>Python 3.12+ · Google Images · resumable · resolution-filtered</sub>
</p>

---

## Quickstart

```bash
python -m venv venv
venv\Scripts\Activate.ps1          # PowerShell   (cmd: venv\Scripts\activate.bat)
pip install -e .
playwright install chromium        # one-time browser download

tis "Ferrari Italia" --count 20 --min-resolution 1080p --headful
```

Kept images land in `images/ferrari_italia/ferrari_italia_0001.jpg`, `…_0002.jpg`, … — one folder per search term.

---

## Why another scraper?

Most scrapers are built for **text**, and the image-focused ones are often outdated or
too fragile to reliably fetch and download real, full-resolution images.

Collecting images for a *specific* topic is also usually messy: mixed resolutions,
duplicate files, and no clean per-topic organization.

**The Image Scrapper (TIS)** focuses on exactly that:

- **Full-resolution images from Google Images** (working as of September 2026).
- **Collect by search term**, with filtering (e.g. minimum resolution) and automatic de-duplication.
- **Tidy output**: one folder per term, sequentially numbered files.
- **Resumable**: stop and re-run; it tops up toward your target instead of starting over.

---

## How it works

TIS is intentionally a *browser-like* flow, kept as simple as:

<p align="center">
  <b>You put in a term, you get images of that term.</b>
</p>

Under the hood it splits the job into a **harvest** stage and a **download** stage
(see [The harvest/download split](#the-harvestdownload-split) below).

---

## Sources

Today TIS harvests from a single source; the architecture is built to grow more.

| Source        | Status        | Notes                                                        |
| ------------- | ------------- | ------------------------------------------------------------ |
| Google Images | ✅ Supported  | JS-rendered, so it needs a real browser; may hit a CAPTCHA.  |
| Bing Images   | 🛣️ Roadmap    | Server-rendered (plain HTTP GET) — better for hands-off bulk. |

> Google is powerful but the "one fragile source": it can serve a CAPTCHA and its
> markup changes over time. A server-rendered source like Bing is the better
> long-term default for unattended collection (see [Roadmap](#roadmap)).

---

## Install

Requires **Python 3.12+**. From the repo root:

```bash
python -m venv venv
venv\Scripts\Activate.ps1          # PowerShell   (cmd: venv\Scripts\activate.bat)

pip install -e .
playwright install chromium
```

> [!NOTE]
> `pip install -e .` installs the runtime dependencies (`playwright`, `httpx`,
> `SQLAlchemy`, `pillow`, `imagehash`) from `pyproject.toml`; an equivalent
> `requirements.txt` is provided too. `playwright install chromium` downloads the
> browser used for harvesting (one-time).

---

## Usage

```bash
tis "Ferrari Italia" --count 20 --min-resolution 1080p
```

| Option             | Default        | Meaning                                                          |
| ------------------ | -------------- | ---------------------------------------------------------------- |
| `query`            | —              | Positional search term.                                          |
| `--count`          | `50`           | Images to **keep** after filtering (clamped `1..1000`).          |
| `--min-resolution` | `none`         | `none` / `480p` / `720p` / `1080p` / `4k`.                       |
| `--out`            | `images`       | Root output folder for kept images.                              |
| `--db`             | `imagegrab.db` | SQLite manifest path.                                            |
| `--headful`        | off            | Show the browser (required to solve a CAPTCHA by hand).          |
| `--profile-dir`    | none           | Persistent browser profile — remembers consent + CAPTCHA solves. |
| `--concurrency`    | `20`           | Max simultaneous downloads.                                      |
| `--pace`           | `1.0`          | Seconds between thumbnail hovers while harvesting.               |

**About `--count`:** it is the number of images **kept** after de-duplication and the
resolution filter — TIS over-harvests to absorb losses. It's a *ceiling*, not a
guarantee: Google itself usually yields only a few hundred images per term.

**About `--min-resolution`:** the default `none` maps to tier `0`, i.e. **no resolution
filtering** — every decodable image passes. Higher tiers require
`min(width, height) >= tier`, measured on the decoded bytes.

### Output layout

Kept images are organized one folder per query, with a zero-padded, per-query index;
the original file extension is preserved:

```
images/
  ferrari_italia/
    ferrari_italia_0001.jpg
    ferrari_italia_0002.png
  lamborghini/
    lamborghini_0001.jpg
```

---

## The harvest/download split

Google Images is JavaScript-rendered, so **harvesting** needs a real browser
(Playwright). TIS does **not** click results — each grid tile is a link that would
navigate away; instead it **hovers** each tile to make Google populate that tile's
`<a href="/imgres?imgurl=...">`, then reads the origin URL straight out of the href.
(The only thing ever clicked is Google's own "Show more results" button.)

Scraping is fundamentally just *harvesting URL strings*: once a full-resolution origin
URL is captured, **downloading** it is a plain async HTTP GET with no browser involved.
v1 (version `0.1.0`) is built around that split:

```
harvest (Playwright -> Google)     SQLite manifest       download (async httpx)
  full-res URL strings       ->     status=pending   ->   no browser needed
                                                          | decode + filter
                          files on disk  <-  keep/discard (dedup + resolution)
```

**De-duplication runs cheapest-first:**

1. Exact URL (a `UNIQUE` column in the manifest).
2. Exact bytes (SHA-256).
3. Near-duplicate (perceptual hash, Hamming distance ≤ 5).

**The resolution filter** is authoritative on the decoded bytes: an image passes a tier
when `min(width, height) >= tier`.

**Everything is resumable:** the SQLite manifest records every URL and its outcome, so
re-running a query skips what's already done and tops up toward `--count`.

---

## Google, CAPTCHAs, and the manual-solve workflow

Google aggressively fingerprints automation and often serves a `/sorry`
"unusual traffic" + reCAPTCHA page — sometimes on the very first request, even from a
normal residential connection. TIS does **not** try to solve or bypass it. Instead:

- In **headful** mode it detects the CAPTCHA, pauses, and prints a message; you solve it
  by hand in the browser window and harvesting resumes automatically.
- In **headless** mode it can't be solved, so the run stops with a message telling you to
  re-run with `--headful`.

Pair it with `--profile-dir` so the solved-exemption and consent cookies persist between
runs — after the first manual solve, later runs often skip the CAPTCHA entirely:

```bash
tis "Ferrari Italia" --count 20 --headful --profile-dir chrome-profile
```

Use a **dedicated** folder for `--profile-dir`, not your everyday Chrome profile. It
stores cookies/session data and is git-ignored.

> **Reality check:** this makes Google *usable* but semi-manual — you're on standby to
> solve a challenge. For hands-off bulk collection, a server-rendered source like Bing
> (see Roadmap) is the better long-term default.

---

## Roadmap

- **More sources.** A server-rendered source like **Bing Images** is GET-scrapable — no
  rendering browser needed. Because it's plain HTTP, the harvest could run fully **async**
  (fetching result pages concurrently), unlike the inherently serial Google browser flow.
- **Smarter output naming.** The current one-folder-per-term layout works, but there's
  room for a more optimal scheme — **proposals welcome.**

---

## Notes & caveats

- **Copyright:** downloaded images carry their own copyright. You are responsible for how
  you use them.
- **Datacenter IPs** may be blocked automatically, which can make TIS unusable from such
  hosts; a residential connection (with `--headful` + `--profile-dir`) is more reliable.
- **Google markup is a moving target.** If harvesting suddenly returns nothing, Google has
  likely reshuffled its markup — run with `--headful` to watch, and update the selectors in
  `src/imagegrab/sources/google.py` (they're isolated in one clearly marked block).

---

## License

See [LICENSE](LICENSE).
