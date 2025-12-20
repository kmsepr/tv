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
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
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
    "arabic":  "https://iptv-org.github.io/iptv/languages/ara.m3u",
    "urdu":    "https://iptv-org.github.io/iptv/languages/urd.m3u",
    "french":  "https://iptv-org.github.io/iptv/languages/fra.m3u",
    "spanish": "https://iptv-org.github.io/iptv/languages/spa.m3u",
    "german":  "https://iptv-org.github.io/iptv/languages/deu.m3u",
    "turkish": "https://iptv-org.github.io/iptv/languages/tur.m3u",
    "russian": "https://iptv-org.github.io/iptv/languages/rus.m3u",
    "chinese": "https://iptv-org.github.io/iptv/languages/zho.m3u",
    "japanese":"https://iptv-org.github.io/iptv/languages/jpn.m3u",
    "korean":  "https://iptv-org.github.io/iptv/languages/kor.m3u",
}

CACHE = {}

# ============================================================
# M3U Parser
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
        if eq == -1: break
        key_end = eq
        key_start = left.rfind(" ", 0, key_end)
        colon = left.rfind(":", 0, key_end)
        if colon > key_start: key_start = colon
        key = left[key_start + 1:key_end].strip()
        if eq + 1 < len(left) and left[eq + 1] == '"':
            val_start = eq + 2
            val_end = left.find('"', val_start)
            if val_end == -1: break
            val = left[val_start:val_end]
            pos = val_end + 1
        else:
            val_end = left.find(" ", eq + 1)
            if val_end == -1: val_end = len(left)
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
# Cache loader
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
    try:
        resp = requests.get(url, timeout=25)
        resp.raise_for_status()
        channels = parse_m3u(resp.text)
        CACHE[name] = {"time": now, "channels": channels}
        return channels
    except Exception as e:
        logging.error("Load failed %s: %s", name, e)
        return []

# ============================================================
# Audio proxy
# ============================================================
def proxy_audio_only(source_url: str):
    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-fflags", "+nobuffer",
        "-flags", "low_delay",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", source_url,
        "-vn", "-ac", "1", "-ar", "22050", "-b:a", "40k", "-bufsize", "256k",
        "-f", "mp3", "pipe:1"
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
# Routes and HTML
# ============================================================
@app.route("/")
def home():
    html = "<h1>IPTV</h1>"
    html += "<p>Select category:</p>"
    for key in PLAYLISTS.keys():
        html += f'<a href="/list/{key}">{key.capitalize()}</a> '
    html += '<br><a href="/favourites">⭐ Favourites</a> '
    html += '<a href="/random">🎲 Random Channel</a>'
    return html

@app.route("/list/<group>")
def list_group(group):
    if group not in PLAYLISTS: abort(404)
    channels = get_channels(group)
    html = f"<h2>{group.capitalize()} Channels</h2>"
    html += '<a href="/">← Back</a> <a href="/random/'+group+'">🎲 Random</a><br>'
    for idx,ch in enumerate(channels):
        html += f"{idx+1}. {ch['title']} "
        html += f'<a href="/watch/{group}/{idx}" target="_blank">▶ Watch</a> '
        html += f'<a href="/play-audio/{group}/{idx}" target="_blank">🎧 Audio</a><br>'
    return html

@app.route("/watch/<group>/<int:idx>")
def watch_channel(group, idx):
    if group not in PLAYLISTS: abort(404)
    channels = get_channels(group)
    if idx<0 or idx>=len(channels): abort(404)
    ch = channels[idx]
    return f'<h2>{ch["title"]}</h2><video controls autoplay width="100%" src="{ch["url"]}"></video>'

@app.route("/play-audio/<group>/<int:idx>")
def play_audio(group, idx):
    if group not in PLAYLISTS: abort(404)
    channels = get_channels(group)
    if idx<0 or idx>=len(channels): abort(404)
    ch = channels[idx]
    return Response(stream_with_context(proxy_audio_only(ch["url"])), mimetype="audio/mpeg")

@app.route("/random")
@app.route("/random/<group>")
def random_channel(group="all"):
    channels = get_channels(group)
    if not channels: abort(404)
    ch = random.choice(channels)
    return f'<h2>Random: {ch["title"]}</h2><video controls autoplay width="100%" src="{ch["url"]}"></video>'

@app.route("/favourites")
def favourites():
    html = "<h1>⭐ Favourites</h1><p>Open browser console/localStorage for adding favourites.</p>"
    return html

# ============================================================
# Run Flask
# ============================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)