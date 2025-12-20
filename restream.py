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
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
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
# Proxy No-Audio Stream (Browser-playable MP4)
# ============================================================
def proxy_noaudio_mp4(url):
    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", url,
        "-an",                        # 🔇 NO AUDIO
        "-vf", "scale=256:144",
        "-r", "15",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-b:v", "40k",
        "-maxrate", "40k",
        "-bufsize", "240k",
        "-g", "30",
        "-f", "mp4",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
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
# HTML Templates
# ============================================================
HOME_HTML = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV Restream</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:16px}
a{color:#0f0;text-decoration:none;border:1px solid #0f0;padding:10px;margin:8px;border-radius:8px;display:inline-block}
a:hover{background:#0f0;color:#000}
</style>
</head>
<body>
<h2>🌐 IPTV</h2>
<p>Select a category:</p>
{% for key, url in playlists.items() %}
<a href="/list/{{ key }}">{{ key|capitalize }}</a>
{% endfor %}
<a href="/favourites" style="border-color:yellow;color:yellow">⭐ Favourites</a>
</body>
</html>"""

LIST_HTML = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ group|capitalize }} Channels</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:12px}
.card{display:flex;align-items:center;gap:10px;border:1px solid #0f0;border-radius:8px;padding:8px;margin:8px 0;background:#111}
.card img{width:42px;height:42px;background:#222;border-radius:6px}
a.btn{border:1px solid #0f0;color:#0f0;padding:6px 8px;border-radius:6px;text-decoration:none;margin-right:8px}
a.btn:hover{background:#0f0;color:#000}
button.k{padding:6px 8px;border-radius:6px;border:1px solid #0f0;background:#111;color:#0f0;margin-left:6px}
</style>
</head>
<body>
<h3>{{ group|capitalize }} Channels</h3>
<a href="/">← Back</a>
<div style="margin-top:12px;">
{% for ch in channels %}
<div class="card" data-url="{{ ch.url }}" data-title="{{ ch.title }}">
  <img src="{{ ch.logo or fallback }}" onerror="this.src='{{ fallback }}'">
  <div style="flex:1">
    <strong>{{ ch.title }}</strong>
    <div style="margin-top:6px">
      <a class="btn" href="/watch/{{ group }}/{{ loop.index0 }}" target="_blank">▶️ Watch</a>
      <a class="btn" href="/stream-noaudio/{{ group }}/{{ loop.index0 }}" target="_blank">🔇 144p</a>
      <button class="k" onclick='addFav("{{ ch.title|replace('"','&#34;') }}","{{ ch.url }}","{{ ch.logo }}")'>⭐</button>
    </div>
  </div>
</div>
{% endfor %}
</div>

<script>
function addFav(title, url, logo){
  let f = JSON.parse(localStorage.getItem('favs') || '[]');
  if(!f.find(x=>x.url===url)){
    f.push({title:title,url:url,logo:logo});
    localStorage.setItem('favs', JSON.stringify(f));
    alert("Added to favourites");
  } else { alert("Already in favourites"); }
}
</script>
</body>
</html>"""

FAV_HTML = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Favourites</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:12px}
.card{display:flex;align-items:center;gap:10px;border:1px solid yellow;border-radius:8px;padding:8px;margin:8px 0;background:#111}
.card img{width:42px;height:42px;background:#222;border-radius:6px}
a.btn{border:1px solid yellow;color:yellow;padding:6px 8px;border-radius:6px;text-decoration:none;margin-right:8px}
a.btn:hover{background:yellow;color:#000}
button.del{padding:4px 10px;margin-right:8px;color:red;border:1px solid red;background:#000;border-radius:6px;cursor:pointer}
</style>
</head>
<body>
<h2>⭐ Favourites</h2>
<a href="/">← Back</a>
<div id="favList" style="margin-top:12px;"></div>
<script>
function loadFavs(){
  let f = JSON.parse(localStorage.getItem('favs') || '[]');
  let html = "";
  f.forEach((c,i)=>{
    html += `<div class="card">
      <img src="${c.logo||''}" onerror="this.src='""" + LOGO_FALLBACK + """'">
      <button class="del" onclick="delFav(${i})">×</button>
      <div style="flex:1">
        <strong>${c.title}</strong>
        <div style="margin-top:6px">
          <a class="btn" href="/watch-direct?title=${encodeURIComponent(c.title)}&url=${encodeURIComponent(c.url)}&logo=${encodeURIComponent(c.logo)}" target="_blank">▶ Watch</a>
          <a class="btn" href="/stream-noaudio-direct?u=${encodeURIComponent(c.url)}" target="_blank">🔇 144p</a>
        </div>
      </div>
    </div>`;
  });
  document.getElementById('favList').innerHTML = html;
}

function delFav(idx){
  let f = JSON.parse(localStorage.getItem('favs') || '[]');
  f.splice(idx,1);
  localStorage.setItem('favs',JSON.stringify(f));
  loadFavs();
}

loadFavs();
</script>
</body>
</html>"""

# ============================================================
# Routes
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

@app.route("/watch/<group>/<int:idx>")
def watch_channel(group, idx):
    if group not in PLAYLISTS:
        abort(404)
    channels = get_channels(group)
    if idx < 0 or idx >= len(channels):
        abort(404)
    ch = channels[idx]
    mime = "application/vnd.apple.mpegurl" if ch["url"].endswith(".m3u8") else "video/mp4"
    return render_template_string(WATCH_HTML, channel=ch, mime_type=mime)

@app.route("/stream-noaudio/<group>/<int:idx>")
def stream_noaudio(group, idx):
    if group not in PLAYLISTS:
        abort(404)
    channels = get_channels(group)
    if idx < 0 or idx >= len(channels):
        abort(404)
    url = channels[idx]["url"]
    return Response(stream_with_context(proxy_noaudio_mp4(url)),
                    mimetype="video/mp4",
                    headers={"Access-Control-Allow-Origin":"*"})

@app.route("/favourites")
def favourites():
    return render_template_string(FAV_HTML)

@app.route("/watch-direct")
def watch_direct():
    title = request.args.get("title","Channel")
    url = request.args.get("url")
    logo = request.args.get("logo","")
    if not url:
        return "Invalid URL", 400
    ch = {"title": title, "url": url, "logo": logo}
    mime = "application/vnd.apple.mpegurl" if url.endswith(".m3u8") else "video/mp4"
    return render_template_string(WATCH_HTML, channel=ch, mime_type=mime)

@app.route("/stream-noaudio-direct")
def stream_noaudio_direct():
    url = request.args.get("u")
    if not url:
        abort(404)
    return Response(stream_with_context(proxy_noaudio_mp4(url)),
                    mimetype="video/mp4",
                    headers={"Access-Control-Allow-Origin":"*"})

# ============================================================
# Entry
# ============================================================
if __name__ == "__main__":
    print("Running IPTV Restream with Favourites on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)