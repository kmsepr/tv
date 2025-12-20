#!/usr/bin/env python3
import time
import logging
import random
import requests
import subprocess
from flask import (
    Flask, Response, render_template_string,
    abort, stream_with_context, request
)

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
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "english": "https://iptv-org.github.io/iptv/languages/eng.m3u",
}

CACHE = {}

# ============================================================
# M3U PARSER
# ============================================================
def parse_extinf(line):
    left, title = line.split(",", 1) if "," in line else (line, "")
    attrs = {}
    for part in left.split():
        if "=" in part:
            k, v = part.split("=", 1)
            attrs[k] = v.strip('"')
    return attrs, title.strip()

def parse_m3u(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            attrs, title = parse_extinf(lines[i])
            url = lines[i+1] if i+1 < len(lines) else None
            if url and not url.startswith("#"):
                out.append({
                    "title": title or attrs.get("tvg-name", "Unknown"),
                    "url": url,
                    "logo": attrs.get("tvg-logo", ""),
                })
            i += 2
        else:
            i += 1
    return out

# ============================================================
# CACHE LOADER
# ============================================================
def get_channels(name):
    now = time.time()
    if name in CACHE and now - CACHE[name]["time"] < REFRESH_INTERVAL:
        return CACHE[name]["channels"]

    url = PLAYLISTS.get(name)
    if not url:
        return []

    try:
        r = requests.get(url, timeout=25)
        r.raise_for_status()
        ch = parse_m3u(r.text)
        CACHE[name] = {"time": now, "channels": ch}
        logging.info("[%s] %d channels", name, len(ch))
        return ch
    except Exception as e:
        logging.error("Playlist error: %s", e)
        return []

# ============================================================
# AUDIO ONLY (40 kbps)
# ============================================================
def proxy_audio_only(src):
    cmd = [
        "ffmpeg", "-i", src,
        "-vn",
        "-ac", "1",
        "-b:a", "40k",
        "-f", "mp3",
        "pipe:1"
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for c in iter(lambda: p.stdout.read(1024), b""):
            yield c
    finally:
        p.terminate()
        p.wait()

# ============================================================
# 144p VIDEO ONLY (NO AUDIO)
# ============================================================
def proxy_video_144p(src):
    cmd = [
        "ffmpeg",
        "-i", src,
        "-an",
        "-vf", "scale=-2:144",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-b:v", "40k",
        "-maxrate", "50k",
        "-bufsize", "80k",
        "-pix_fmt", "yuv420p",
        "-movflags", "frag_keyframe+empty_moov",
        "-f", "mp4",
        "pipe:1"
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for c in iter(lambda: p.stdout.read(1024), b""):
            yield c
    finally:
        p.terminate()
        p.wait()

# ============================================================
# HTML
# ============================================================
HOME_HTML = """
<!doctype html><html><body style="background:black;color:#0f0">
<h3>IPTV</h3>
{% for k in playlists %}
<a href="/list/{{k}}" style="color:#0f0">{{k}}</a><br>
{% endfor %}
<a href="/random">🎲 Random</a>
<a href="/favourites">⭐ Favourites</a>
</body></html>
"""

LIST_HTML = """
<!doctype html><html><body style="background:black;color:#0f0">
<h3>{{group}}</h3>
{% for ch in channels %}
<div>
{{loop.index}}. {{ch.title}}<br>
<a href="/watch/{{group}}/{{loop.index0}}">▶</a>
<a href="/play-144p/{{group}}/{{loop.index0}}">📺144p</a>
<a href="/play-audio/{{group}}/{{loop.index0}}">🎧</a>
<button onclick='fav("{{ch.title}}","{{ch.url}}","{{ch.logo}}")'>⭐</button>
</div><hr>
{% endfor %}
<script>
function fav(t,u,l){
let f=JSON.parse(localStorage.getItem("favs")||"[]");
if(!f.find(x=>x.url==u)){
f.push({title:t,url:u,logo:l});
localStorage.setItem("favs",JSON.stringify(f));
alert("Added");
}}
</script>
</body></html>
"""

WATCH_HTML = """
<!doctype html><html><body style="background:black;color:#0f0">
<h3>{{channel.title}}</h3>
<video controls autoplay width="100%">
<source src="{{channel.url}}">
</video>
</body></html>
"""

FAV_HTML = """
<!doctype html><html><body style="background:black;color:#0f0">
<h3>Favourites</h3>
<div id="f"></div>
<script>
let f=JSON.parse(localStorage.getItem("favs")||"[]");
let h="";
f.forEach((c,i)=>{
h+=`<div>${c.title}
<a href="/watch-direct?u=${encodeURIComponent(c.url)}">▶</a>
<a href="/play-144p-direct?u=${encodeURIComponent(c.url)}">📺144p</a>
<a href="/play-audio-direct?u=${encodeURIComponent(c.url)}">🎧</a>
</div><hr>`;
});
document.getElementById("f").innerHTML=h;
</script>
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

@app.route("/random")
def random_play():
    ch = random.choice(get_channels("all"))
    return render_template_string(WATCH_HTML, channel=ch)

@app.route("/watch/<group>/<int:i>")
def watch(group, i):
    ch = get_channels(group)[i]
    return render_template_string(WATCH_HTML, channel=ch)

@app.route("/play-audio/<group>/<int:i>")
def play_audio(group, i):
    ch = get_channels(group)[i]
    return Response(
        stream_with_context(proxy_audio_only(ch["url"])),
        mimetype="audio/mpeg"
    )

@app.route("/play-144p/<group>/<int:i>")
def play_144p(group, i):
    ch = get_channels(group)[i]
    return Response(
        stream_with_context(proxy_video_144p(ch["url"])),
        mimetype="video/mp4"
    )

@app.route("/play-audio-direct")
def audio_direct():
    return Response(
        stream_with_context(proxy_audio_only(request.args["u"])),
        mimetype="audio/mpeg"
    )

@app.route("/play-144p-direct")
def video_direct():
    return Response(
        stream_with_context(proxy_video_144p(request.args["u"])),
        mimetype="video/mp4"
    )

@app.route("/watch-direct")
def watch_direct():
    return render_template_string(
        WATCH_HTML,
        channel={"title":"Channel","url":request.args["u"]}
    )

@app.route("/favourites")
def favs():
    return render_template_string(FAV_HTML)

# ============================================================
# ENTRY
# ============================================================
if __name__ == "__main__":
    print("Running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)