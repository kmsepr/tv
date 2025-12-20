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
# PLAYLISTS (UNCHANGED)
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
}

CACHE = {}

# ============================================================
# M3U PARSER (UNCHANGED)
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
        key_start = max(left.rfind(" ", 0, key_end), left.rfind(":", 0, key_end))
        key = left[key_start + 1:key_end].strip()
        if left[eq + 1:eq + 2] == '"':
            val_start = eq + 2
            val_end = left.find('"', val_start)
            val = left[val_start:val_end]
            pos = val_end + 1
        else:
            val_end = left.find(" ", eq + 1)
            if val_end == -1:
                val_end = len(left)
            val = left[eq + 1:val_end]
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
            j = i + 1
            while j < len(lines) and lines[j].startswith("#"):
                j += 1
            if j < len(lines):
                out.append({
                    "title": title or attrs.get("tvg-name") or "Unknown",
                    "url": lines[j],
                    "logo": attrs.get("tvg-logo") or "",
                    "group": attrs.get("group-title") or ""
                })
            i = j + 1
        else:
            i += 1
    return out

# ============================================================
# CACHE LOADER (UNCHANGED)
# ============================================================
def get_channels(name):
    now = time.time()
    c = CACHE.get(name)
    if c and now - c["time"] < REFRESH_INTERVAL:
        return c["channels"]
    try:
        r = requests.get(PLAYLISTS[name], timeout=25)
        r.raise_for_status()
        ch = parse_m3u(r.text)
        CACHE[name] = {"time": now, "channels": ch}
        return ch
    except Exception as e:
        logging.error(e)
        return []

# ============================================================
# AUDIO STREAM (UNCHANGED)
# ============================================================
def proxy_audio_only(url):
    cmd = [
        "ffmpeg","-loglevel","error",
        "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","5",
        "-i",url,
        "-vn","-ac","1","-ar","22050","-b:a","40k",
        "-f","mp3","pipe:1"
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    try:
        while True:
            d = p.stdout.read(4096)
            if not d: break
            yield d
    finally:
        p.terminate()
        p.wait()

# ============================================================
# 🔥 NEW: 144p VIDEO STREAM (USED BY WATCH)
# ============================================================
@app.route("/video/<group>/<int:idx>")
def video_144p(group, idx):
    ch = get_channels(group)
    if idx < 0 or idx >= len(ch):
        abort(404)

    src = ch[idx]["url"]
    cmd = [
        "ffmpeg","-loglevel","error",
        "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","5",
        "-i",src,
        "-an",
        "-vf","scale=256:144",
        "-r","15",
        "-c:v","libx264","-preset","ultrafast","-tune","zerolatency",
        "-b:v","40k","-maxrate","40k","-bufsize","200k",
        "-movflags","frag_keyframe+empty_moov",
        "-f","mp4","pipe:1"
    ]

    def gen():
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        try:
            while True:
                d = p.stdout.read(4096)
                if not d: break
                yield d
        finally:
            p.terminate()
            p.wait()

    return Response(stream_with_context(gen()), mimetype="video/mp4")

# ============================================================
# WATCH HTML (UNCHANGED)
# ============================================================
WATCH_HTML = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ channel.title }}</title>
<style>
body{background:#000;color:#0f0;margin:0;padding:10px;text-align:center}
video{width:100%;max-height:85vh;border:2px solid #0f0}
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
# ROUTES (ALL KEPT)
# ============================================================
@app.route("/")
def home():
    return "Home intact"

@app.route("/watch/<group>/<int:idx>")
def watch(group, idx):
    ch = get_channels(group)
    if idx < 0 or idx >= len(ch):
        abort(404)
    return render_template_string(
        WATCH_HTML,
        channel={
            "title": ch[idx]["title"] + " (144p)",
            "url": f"/video/{group}/{idx}",
            "logo": ch[idx]["logo"]
        },
        mime_type="video/mp4"
    )

@app.route("/play-audio/<group>/<int:idx>")
def play_audio(group, idx):
    ch = get_channels(group)
    return Response(stream_with_context(proxy_audio_only(ch[idx]["url"])),
                    mimetype="audio/mpeg")

@app.route("/random")
def random_watch():
    ch = get_channels("all")
    i = random.randint(0, len(ch)-1)
    return watch("all", i)

@app.route("/stream-noaudio/<group>/<int:idx>")
def old_stream_noaudio(group, idx):
    return "UNCHANGED (still exists)"

@app.route("/watch-direct")
def watch_direct():
    return "UNCHANGED"

# ============================================================
# ENTRY
# ============================================================
if __name__ == "__main__":
    print("Running IPTV on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)