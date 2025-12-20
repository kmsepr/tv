#!/usr/bin/env python3
import os
import time
import logging
import random
import requests
import subprocess
from flask import Flask, Response, render_template_string, abort, stream_with_context, request

# ============================================================
# Basic Setup
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__)

REFRESH_INTERVAL = 1800
LOGO_FALLBACK = "https://iptv-org.github.io/assets/logo.png"

# ============================================================
# PLAYLISTS
# ============================================================
PLAYLISTS = {
    "all": "https://iptv-org.github.io/iptv/index.m3u",
    "india": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "usa": "https://iptv-org.github.io/iptv/countries/us.m3u",
    "uk": "https://iptv-org.github.io/iptv/countries/uk.m3u",
    "uae": "https://iptv-org.github.io/iptv/countries/ae.m3u",
    "saudi": "https://iptv-org.github.io/iptv/countries/sa.m3u",
    "pakistan": "https://iptv-org.github.io/iptv/countries/pk.m3u",
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "music": "https://iptv-org.github.io/iptv/categories/music.m3u",
    "kids": "https://iptv-org.github.io/iptv/categories/kids.m3u",
    "entertainment": "https://iptv-org.github.io/iptv/categories/entertainment.m3u",
    "english":   "https://iptv-org.github.io/iptv/languages/eng.m3u",
    "hindi":     "https://iptv-org.github.io/iptv/languages/hin.m3u",
    "tamil":     "https://iptv-org.github.io/iptv/languages/tam.m3u",
    "telugu":    "https://iptv-org.github.io/iptv/languages/tel.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "kannada":   "https://iptv-org.github.io/iptv/languages/kan.m3u",
    "marathi":   "https://iptv-org.github.io/iptv/languages/mar.m3u",
    "gujarati":  "https://iptv-org.github.io/iptv/languages/guj.m3u",
    "bengali":   "https://iptv-org.github.io/iptv/languages/ben.m3u",
    "punjabi":   "https://iptv-org.github.io/iptv/languages/pan.m3u",
    "arabic":    "https://iptv-org.github.io/iptv/languages/ara.m3u",
    "urdu":      "https://iptv-org.github.io/iptv/languages/urd.m3u",
    "french":    "https://iptv-org.github.io/iptv/languages/fra.m3u",
    "spanish":   "https://iptv-org.github.io/iptv/languages/spa.m3u",
    "german":    "https://iptv-org.github.io/iptv/languages/deu.m3u",
    "turkish":   "https://iptv-org.github.io/iptv/languages/tur.m3u",
    "russian":   "https://iptv-org.github.io/iptv/languages/rus.m3u",
    "chinese":   "https://iptv-org.github.io/iptv/languages/zho.m3u",
    "japanese":  "https://iptv-org.github.io/iptv/languages/jpn.m3u",
    "korean":    "https://iptv-org.github.io/iptv/languages/kor.m3u",
}

CACHE = {}

# ============================================================
# M3U PARSER
# ============================================================
def parse_extinf(line: str):
    if "," in line:
        left, title = line.split(",", 1)
    else:
        left, title = line, ""
    attrs = {}
    pos = 0
    while True:
        eq = left.find("=", pos)
        if eq == -1:
            break
        key_end = eq
        key_start = left.rfind(" ", 0, key_end)
        colon = left.rfind(":", 0, key_end)
        if colon > key_start:
            key_start = colon
        key = left[key_start + 1:key_end].strip()
        if eq + 1 < len(left) and left[eq + 1] == '"':
            val_start = eq + 2
            val_end = left.find('"', val_start)
            if val_end == -1:
                break
            val = left[val_start:val_end]
            pos = val_end + 1
        else:
            val_end = left.find(" ", eq + 1)
            if val_end == -1:
                val_end = len(left)
            val = left[eq + 1:val_end].strip()
            pos = val_end
        attrs[key] = val
    return attrs, title.strip()

def parse_m3u(text: str):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    channels = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            attrs, title = parse_extinf(lines[i])
            j = i + 1
            url = None
            while j < len(lines):
                if not lines[j].startswith("#"):
                    url = lines[j]
                    break
                j += 1
            if url:
                channels.append({
                    "title": title or attrs.get("tvg-name") or "Unknown",
                    "url": url,
                    "logo": attrs.get("tvg-logo") or "",
                    "group": attrs.get("group-title") or "",
                    "tvg_id": attrs.get("tvg-id") or "",
                })
            i = j + 1
        else:
            i += 1
    return channels

# ============================================================
# Cache Loader
# ============================================================
def get_channels(name: str):
    now = time.time()
    cached = CACHE.get(name)
    if cached and now - cached.get("time", 0) < REFRESH_INTERVAL:
        return cached["channels"]
    url = PLAYLISTS.get(name)
    if not url:
        logging.error("Playlist not found: %s", name)
        return []
    logging.info("[%s] Fetching playlist: %s", name, url)
    try:
        resp = requests.get(url, timeout=25)
        resp.raise_for_status()
        channels = parse_m3u(resp.text)
        CACHE[name] = {"time": now, "channels": channels}
        logging.info("[%s] Loaded %d channels", name, len(channels))
        return channels
    except Exception as e:
        logging.error("Load failed %s: %s", name, e)
        return []

# ============================================================
# 144p NO-AUDIO STREAM
# ============================================================
def stream_144p(source_url: str):
    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", source_url,
        "-an",                     # no audio
        "-vf", "scale=256:144",
        "-r", "15",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-b:v", "40k",
        "-maxrate", "40k",
        "-bufsize", "240k",
        "-g", "30",
        "-f", "mpegts",
        "pipe:1"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    try:
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            yield chunk
    finally:
        proc.terminate()
        proc.wait()

# ============================================================
# ROUTES
# ============================================================
@app.route("/")
def home():
    return render_template_string(HOME_HTML, playlists=PLAYLISTS)

@app.route("/list/<group>")
def list_group(group):
    if group not in PLAYLISTS:
        abort(404)
    channels = get_channels(group)
    return render_template_string(LIST_HTML, group=group, channels=channels, fallback=LOGO_FALLBACK)

@app.route("/favourites")
def favourites():
    return render_template_string(FAV_HTML, fallback=LOGO_FALLBACK)

@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return render_template_string(SEARCH_HTML, query="", results=[], fallback=LOGO_FALLBACK)
    ql = q.lower()
    all_channels = get_channels("all")
    results = []
    for idx, ch in enumerate(all_channels):
        title = (ch.get("title") or "").lower()
        group = (ch.get("group") or "").lower()
        if ql in title or ql in group or ql in (ch.get("url") or "").lower():
            results.append({
                "index": idx,
                "title": ch.get("title"),
                "url": ch.get("url"),
                "logo": ch.get("logo"),
            })
    return render_template_string(SEARCH_HTML, query=q, results=results, fallback=LOGO_FALLBACK)

@app.route("/random")
def random_global():
    channels = get_channels("all")
    if not channels:
        abort(404)
    idx = random.randint(0, len(channels)-1)
    return f'<script>window.location="/stream-144p/all/{idx}"</script>'

@app.route("/random/<group>")
def random_category(group):
    if group not in PLAYLISTS:
        abort(404)
    channels = get_channels(group)
    if not channels:
        abort(404)
    idx = random.randint(0, len(channels)-1)
    return f'<script>window.location="/stream-144p/{group}/{idx}"</script>'

@app.route("/watch/<group>/<int:idx>")
def watch_channel(group, idx):
    if group not in PLAYLISTS:
        abort(404)
    channels = get_channels(group)
    if idx < 0 or idx >= len(channels):
        abort(404)
    ch = channels[idx]
    # WATCH page uses 144p no-audio by default
    stream_url = f"/stream-144p/{group}/{idx}"
    return render_template_string(WATCH_HTML, channel={**ch, "url": stream_url}, mime_type="video/mp2t")

@app.route("/stream-144p/<group>/<int:idx>")
def stream_144p_iptv(group, idx):
    if group not in PLAYLISTS:
        abort(404)
    channels = get_channels(group)
    if idx < 0 or idx >= len(channels):
        abort(404)
    url = channels[idx]["url"]
    return Response(stream_with_context(stream_144p(url)),
                    mimetype="video/mp2t",
                    headers={"Access-Control-Allow-Origin": "*", "Cache-Control":"no-cache"})

@app.route("/watch-direct")
def watch_direct():
    title = request.args.get("title", "Channel")
    url = request.args.get("url")
    logo = request.args.get("logo", "")
    if not url:
        return "Invalid URL", 400
    # For direct, also stream 144p
    stream_url = f"/stream-144p/direct?url={url}"
    channel = {"title": title, "url": stream_url, "logo": logo}
    return render_template_string(WATCH_HTML, channel=channel, mime_type="video/mp2t")

@app.route("/stream-144p/direct")
def stream_144p_direct():
    url = request.args.get("url")
    if not url:
        abort(404)
    return Response(stream_with_context(stream_144p(url)),
                    mimetype="video/mp2t",
                    headers={"Access-Control-Allow-Origin": "*", "Cache-Control":"no-cache"})

# ============================================================
# Entry
# ============================================================
if __name__ == "__main__":
    print("Running IPTV Restream on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)