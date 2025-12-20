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
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "music": "https://iptv-org.github.io/iptv/categories/music.m3u",
    "kids": "https://iptv-org.github.io/iptv/categories/kids.m3u",
}

CACHE = {}

# ============================================================
# M3U PARSER
# ============================================================
def parse_extinf(line):
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

def parse_m3u(text):
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
                })
            i = j + 1
        else:
            i += 1
    return channels

# ============================================================
# Cache Loader
# ============================================================
def get_channels(name):
    now = time.time()
    cached = CACHE.get(name)
    if cached and now - cached["time"] < REFRESH_INTERVAL:
        return cached["channels"]

    url = PLAYLISTS.get(name)
    if not url:
        return []

    try:
        r = requests.get(url, timeout=25)
        r.raise_for_status()
        ch = parse_m3u(r.text)
        CACHE[name] = {"time": now, "channels": ch}
        return ch
    except Exception as e:
        logging.error(e)
        return []

# ============================================================
# 🔥 144p NO AUDIO VIDEO STREAM (40kbps)
# ============================================================
@app.route("/video/<group>/<int:idx>")
def video_144p(group, idx):
    if group not in PLAYLISTS:
        abort(404)

    channels = get_channels(group)
    if idx < 0 or idx >= len(channels):
        abort(404)

    src = channels[idx]["url"]

    cmd = [
        "ffmpeg",
        "-loglevel", "error",

        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",

        "-i", src,

        "-an",
        "-vf", "scale=256:144",
        "-r", "15",

        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",

        "-b:v", "40k",
        "-maxrate", "40k",
        "-bufsize", "200k",

        "-movflags", "frag_keyframe+empty_moov",
        "-f", "mp4",
        "pipe:1"
    ]

    def generate():
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        try:
            while True:
                data = p.stdout.read(4096)
                if not data:
                    break
                yield data
        finally:
            p.terminate()
            p.wait()

    return Response(
        stream_with_context(generate()),
        mimetype="video/mp4",
        headers={"Access-Control-Allow-Origin": "*"}
    )

# ============================================================
# HTML
# ============================================================
WATCH_HTML = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ channel.title }}</title>
<style>
body{background:#000;color:#0f0;margin:0;padding:10px;text-align:center}
video{width:100%;max-height:85vh;border:2px solid #0f0}
.btn{border:1px solid #0f0;color:#0f0;padding:8px 12px;border-radius:6px;margin:6px;display:inline-block}
</style>
</head>
<body>
<h3>{{ channel.title }}</h3>
<video controls autoplay playsinline>
  <source src="{{ channel.url }}" type="{{ mime_type }}">
</video>
</body>
</html>"""

# ============================================================
# ROUTES
# ============================================================
@app.route("/watch/<group>/<int:idx>")
def watch(group, idx):
    channels = get_channels(group)
    if idx < 0 or idx >= len(channels):
        abort(404)

    ch = channels[idx]
    channel = {
        "title": ch["title"] + " (144p)",
        "url": f"/video/{group}/{idx}",
        "logo": ch.get("logo", "")
    }

    return render_template_string(
        WATCH_HTML,
        channel=channel,
        mime_type="video/mp4"
    )

# ============================================================
# Entry
# ============================================================
if __name__ == "__main__":
    print("Running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)