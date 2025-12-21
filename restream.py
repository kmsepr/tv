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
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "music": "https://iptv-org.github.io/iptv/categories/music.m3u",
    "kids": "https://iptv-org.github.io/iptv/categories/kids.m3u",
    "english": "https://iptv-org.github.io/iptv/languages/eng.m3u",
    "hindi": "https://iptv-org.github.io/iptv/languages/hin.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
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
            val = left[val_start:val_end]
            pos = val_end + 1
        else:
            val_end = left.find(" ", eq + 1)
            val = left[eq + 1:val_end].strip()
            pos = val_end

        attrs[key] = val
    return attrs, title.strip()

def parse_m3u(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            attrs, title = parse_extinf(lines[i])
            url = lines[i + 1]
            out.append({
                "title": title or attrs.get("tvg-name", "Unknown"),
                "url": url,
                "logo": attrs.get("tvg-logo", ""),
                "group": attrs.get("group-title", "")
            })
            i += 2
        else:
            i += 1
    return out

# ============================================================
# Cache Loader
# ============================================================
def get_channels(name):
    now = time.time()
    if name in CACHE and now - CACHE[name]["time"] < REFRESH_INTERVAL:
        return CACHE[name]["channels"]

    r = requests.get(PLAYLISTS[name], timeout=25)
    channels = parse_m3u(r.text)
    CACHE[name] = {"time": now, "channels": channels}
    return channels

# ============================================================
# Audio proxy
# ============================================================
def proxy_audio_only(url):
    cmd = ["ffmpeg", "-i", url, "-vn", "-b:a", "40k", "-f", "mp3", "pipe:1"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    while True:
        data = p.stdout.read(65536)
        if not data:
            break
        yield data

# ============================================================
# 240p LOW VIDEO proxy (NO AUDIO)
# ============================================================
def proxy_video_low(url):
    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-i", url,
        "-an",
        "-vf", "scale=426:240",
        "-r", "15",
        "-b:v", "150k",
        "-f", "mp4",
        "-movflags", "frag_keyframe+empty_moov",
        "pipe:1"
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    while True:
        data = p.stdout.read(65536)
        if not data:
            break
        yield data

# ============================================================
# HTML
# ============================================================
HOME_HTML = """
<!doctype html>
<html>
<body style="background:#000;color:#0f0">
<h2>IPTV</h2>
<a href="/random">🎲 Random</a>
<a href="/favourites">⭐ Favourites</a>
<hr>
{% for k in playlists %}
<a href="/list/{{k}}">{{k}}</a><br>
{% endfor %}
</body></html>
"""

LIST_HTML = """
<!doctype html><html><body style="background:#000;color:#0f0">
<h3>{{group}}</h3><a href="/">← Back</a><hr>
{% for ch in channels %}
<b>{{loop.index}}. {{ch.title}}</b><br>
<a href="/watch/{{group}}/{{loop.index0}}" target="_blank">▶ Watch</a>
<a href="/low/{{group}}/{{loop.index0}}" target="_blank">📉 240p</a>
<a href="/play-audio/{{group}}/{{loop.index0}}" target="_blank">🎧 Audio</a>
<hr>
{% endfor %}
</body></html>
"""

WATCH_HTML = """
<!doctype html>
<html><body style="background:#000;color:#0f0">
<h3>{{channel.title}}</h3>
<video controls autoplay playsinline style="width:100%">
<source src="{{channel.url}}" type="{{mime_type}}">
</video>
</body></html>
"""

# ============================================================
# ROUTES
# ============================================================
@app.route("/")
def home():
    return render_template_string(HOME_HTML, playlists=PLAYLISTS)

@app.route("/list/<group>")
def list_group(group):
    return render_template_string(
        LIST_HTML,
        group=group,
        channels=get_channels(group)
    )

@app.route("/watch/<group>/<int:idx>")
def watch(group, idx):
    ch = get_channels(group)[idx]
    mime = "application/vnd.apple.mpegurl" if ".m3u8" in ch["url"] else "video/mp4"
    return render_template_string(WATCH_HTML, channel=ch, mime_type=mime)

@app.route("/low/<group>/<int:idx>")
def low(group, idx):
    ch = get_channels(group)[idx]
    return Response(
        stream_with_context(proxy_video_low(ch["url"])),
        mimetype="video/mp4"
    )

@app.route("/play-audio/<group>/<int:idx>")
def audio(group, idx):
    ch = get_channels(group)[idx]
    return Response(
        stream_with_context(proxy_audio_only(ch["url"])),
        mimetype="audio/mpeg"
    )

@app.route("/random")
def random_ch():
    ch = random.choice(get_channels("all"))
    mime = "application/vnd.apple.mpegurl" if ".m3u8" in ch["url"] else "video/mp4"
    return render_template_string(WATCH_HTML, channel=ch, mime_type=mime)

# ============================================================
# Entry
# ============================================================
if __name__ == "__main__":
    print("Running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)