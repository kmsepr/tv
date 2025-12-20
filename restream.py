#!/usr/bin/env python3
import os
import time
import logging
import random
import requests
import subprocess
from flask import Flask, Response, render_template_string, abort, stream_with_context, request, send_file

# =============================
# Basic Setup
# =============================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

REFRESH_INTERVAL = 1800
LOGO_FALLBACK = "https://iptv-org.github.io/assets/logo.png"

# =============================
# Playlists
# =============================
PLAYLISTS = {
    "all": "https://iptv-org.github.io/iptv/index.m3u",
    "india": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
}

CACHE = {}

# =============================
# M3U Parser
# =============================
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
                })
            i = j + 1
        else:
            i += 1
    return channels

# =============================
# Cache Loader
# =============================
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

# =============================
# HLS No-Audio Transcoder
# =============================
HLS_CACHE_DIR = "/tmp/hls_cache"
os.makedirs(HLS_CACHE_DIR, exist_ok=True)

def generate_hls_noaudio(url, channel_name):
    """Generate 144p HLS no-audio for a given stream"""
    safe_name = channel_name.replace(" ", "_")
    out_dir = os.path.join(HLS_CACHE_DIR, safe_name)
    os.makedirs(out_dir, exist_ok=True)
    m3u8_file = os.path.join(out_dir, "index.m3u8")

    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-i", url,
        "-an",                        # No audio
        "-vf", "scale=256:144",
        "-r", "15",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-b:v", "40k",
        "-maxrate", "40k",
        "-bufsize", "240k",
        "-g", "30",
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "3",
        "-hls_flags", "delete_segments+temp_file",
        m3u8_file
    ]
    # Run FFmpeg as background process
    subprocess.Popen(cmd)
    return m3u8_file

# =============================
# Routes
# =============================
@app.route("/")
def home():
    html = """<!doctype html>
<html>
<head><meta name="viewport" content="width=device-width,initial-scale=1"><title>IPTV</title></head>
<body>
<h2>🌐 IPTV</h2>
<p>Select a category:</p>
{% for key, url in playlists.items() %}
<a href="/list/{{ key }}">{{ key|capitalize }}</a><br>
{% endfor %}
</body>
</html>"""
    return render_template_string(html, playlists=PLAYLISTS)

@app.route("/list/<group>")
def list_group(group):
    if group not in PLAYLISTS:
        abort(404)
    channels = get_channels(group)
    html = """<!doctype html>
<html><body>
<h3>{{ group|capitalize }} Channels</h3>
<a href="/">← Back</a><br>
{% for ch in channels %}
<b>{{ ch.title }}</b> 
[<a href="/watch/{{ group }}/{{ loop.index0 }}">Watch</a>] 
[<a href="/stream-noaudio/{{ group }}/{{ loop.index0 }}">144p No-Audio</a>]<br>
{% endfor %}
</body></html>"""
    return render_template_string(html, group=group, channels=channels)

@app.route("/watch/<group>/<int:idx>")
def watch_channel(group, idx):
    channels = get_channels(group)
    if idx < 0 or idx >= len(channels):
        abort(404)
    ch = channels[idx]
    mime = "application/vnd.apple.mpegurl" if ch["url"].endswith(".m3u8") else "video/mp4"
    html = """<!doctype html>
<html><body>
<h3>{{ channel.title }}</h3>
<video controls autoplay playsinline style="width:100%;max-height:80vh">
<source src="{{ channel.url }}" type="{{ mime_type }}">
</video>
</body></html>"""
    return render_template_string(html, channel=ch, mime_type=mime)

@app.route("/stream-noaudio/<group>/<int:idx>")
def stream_noaudio(group, idx):
    channels = get_channels(group)
    if idx < 0 or idx >= len(channels):
        abort(404)
    ch = channels[idx]
    m3u8_file = generate_hls_noaudio(ch["url"], ch["title"])
    # Serve HLS playlist
    return send_file(m3u8_file, mimetype="application/vnd.apple.mpegurl")

# =============================
# Serve HLS TS segments
# =============================
@app.route("/hls/<channel>/<path:filename>")
def hls_segments(channel, filename):
    safe_name = channel.replace(" ", "_")
    path = os.path.join(HLS_CACHE_DIR, safe_name, filename)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path)

# =============================
# Run Flask
# =============================
if __name__ == "__main__":
    print("IPTV HLS Restream running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)