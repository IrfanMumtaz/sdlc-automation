"""
Render a static HTML mockup to PNG screenshots with headless Chrome.

Used by the knowledge-base server's save_mockup tool (UI/UX stage) and, through
`sdlc render`, by /sdlc-kickoff for the design system's style guide:

    sdlc render path/to/style-guide.html                  # desktop + mobile
    sdlc render page.html --desktop-height 2400           # taller capture

Writes <name>-desktop.png and <name>-mobile.png next to the HTML file.

Mockups are static and self-contained. make_static() adds a
Content-Security-Policy that blocks scripts and every network request, so a
mockup renders the same everywhere and can't fetch or run anything.
(Chrome's scriptEnabled=false setting also stops headless screenshots, so
the CSP does that job.)
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

VIEWPORTS = {"desktop": 1440, "mobile": 390}
DEFAULT_HEIGHTS = {"desktop": 900, "mobile": 844}
MAX_HEIGHT = 6000

CSP_META = ('<meta http-equiv="Content-Security-Policy" '
            'content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:; font-src data:">')


def find_chrome():
    candidates = [os.environ.get("CHROME_PATH"), "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
    for c in candidates:
        if c and shutil.which(c):
            return shutil.which(c)
    raise RuntimeError("No Chrome or Chromium found. Install one, or set chrome_path in .sdlc/config.json.")


def make_static(html):
    """Insert the no-scripts, no-network CSP as the first element of <head>."""
    if CSP_META in html:
        return html
    m = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    if m:
        return html[:m.end()] + CSP_META + html[m.end():]
    return CSP_META + html


def render(html_path, png_path, width, height):
    height = max(200, min(int(height), MAX_HEIGHT))
    profile = tempfile.mkdtemp(prefix="mockup-chrome-")  # never touch the user's own Chrome profile
    try:
        subprocess.run(
            [find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
             f"--user-data-dir={profile}", f"--window-size={width},{height}",
             f"--screenshot={png_path}", Path(html_path).resolve().as_uri()],
            check=False, capture_output=True, timeout=60,
        )
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if not Path(png_path).exists():
        raise RuntimeError(f"Chrome did not produce {png_path}")
    return Path(png_path)


def render_viewports(html_path, heights=None):
    """Render desktop and mobile PNGs next to html_path; returns their paths."""
    html_path = Path(html_path)
    heights = {**DEFAULT_HEIGHTS, **(heights or {})}
    pngs = []
    for viewport, width in VIEWPORTS.items():
        png = html_path.with_name(f"{html_path.stem}-{viewport}.png")
        png.unlink(missing_ok=True)
        pngs.append(render(html_path, png, width, heights[viewport]))
    return pngs
