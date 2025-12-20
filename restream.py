#!/usr/bin/env python3
import os, time, random, logging, requests, subprocess
from flask import Flask, Response, render_template_string, abort, stream_with_context, request

# =========================
# Basic Setup
# =========================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)
CACHE = {}
REFRESH_INTERVAL = 1800
LOGO_FALLBACK = "https://iptv-org.github.io/assets/logo.png"

# =========================
# Playlists
# =========================
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
    "arabic":  "https://iptv-org.github.io/iptv/languages/ara.m3u",
    "urdu":    "https://iptv-org.github.io/iptv/languages/urd.m3u",
}

# =========================
# M3U parser
# =========================
def parse_extinf(line):
    attrs, title = {}, ""
    if "," in line:
        left, title = line.split(",", 1)
    else:
        left = line
    pos = 0
    while True:
        eq = left.find("=", pos)
        if eq == -1: break
        key_start = left.rfind(" ", 0, eq)
        colon = left.rfind(":", 0, eq)
        if colon > key_start:
            key_start = colon
        key = left[key_start+1:eq].strip()
        if eq+1<len(left) and left[eq+1]=='"':
            val_start = eq+2
            val_end = left.find('"', val_start)
            val = left[val_start:val_end]
            pos = val_end+1
        else:
            val_end = left.find(" ", eq+1)
            if val_end==-1: val_end=len(left)
            val = left[eq+1:val_end].strip()
            pos = val_end
        attrs[key]=val
    return attrs, title.strip()

def parse_m3u(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    channels = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            attrs, title = parse_extinf(lines[i])
            j = i+1
            url = None
            while j<len(lines):
                if not lines[j].startswith("#"):
                    url=lines[j]
                    break
                j+=1
            if url:
                channels.append({
                    "title": title or attrs.get("tvg-name") or "Unknown",
                    "url": url,
                    "logo": attrs.get("tvg-logo") or "",
                    "group": attrs.get("group-title") or "",
                })
            i=j+1
        else:
            i+=1
    return channels

# =========================
# Cache loader
# =========================
def get_channels(name):
    now=time.time()
    cached=CACHE.get(name)
    if cached and now - cached.get("time",0) < REFRESH_INTERVAL:
        return cached["channels"]
    url = PLAYLISTS.get(name)
    if not url:
        logging.error("Playlist not found: %s", name)
        return []
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        channels=parse_m3u(resp.text)
        CACHE[name]={"time":now,"channels":channels}
        return channels
    except Exception as e:
        logging.error("Load failed %s: %s", name, e)
        return []

# =========================
# HTML Templates
# =========================
HOME_HTML = """<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV Restream</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:16px}
a.btn{color:#0f0;text-decoration:none;border:1px solid #0f0;padding:10px;margin:6px;border-radius:8px;display:inline-block}
a.btn:hover{background:#0f0;color:#000}
</style>
</head><body>
<h2>🌐 IPTV</h2>
<a class="btn" href="/random-low">🎲 Random Low 144p</a>
<p>Select a category:</p>
{% for key in playlists %}
<a class="btn" href="/list/{{ key }}">{{ key|capitalize }}</a>
{% endfor %}
<form action="/search" method="get" style="margin-top:10px;">
<input name="q" placeholder="Search..." style="padding:6px;border-radius:6px;border:1px solid #0f0;background:#111;color:#0f0">
<button type="submit" class="btn">🔍 Search</button>
</form>
</body></html>
"""

LIST_HTML = """<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ group|capitalize }} Channels</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:12px}
.card{display:flex;align-items:center;gap:10px;border:1px solid #0f0;border-radius:8px;padding:8px;margin:8px 0;background:#111}
.card img{width:42px;height:42px;background:#222;border-radius:6px}
a.btn{border:1px solid #0f0;color:#0f0;padding:6px 8px;border-radius:6px;text-decoration:none;margin-right:8px}
a.btn:hover{background:#0f0;color:#000}
</style></head><body>
<h3>{{ group|capitalize }} Channels</h3>
<a href="/">← Back</a>
<div id="channelList">
{% for ch in channels %}
<div class="card">
<div style="width:30px;text-align:center">{{ loop.index }}.</div>
<img src="{{ ch.logo or fallback }}" onerror="this.src='{{ fallback }}'">
<div style="flex:1">
<strong>{{ ch.title }}</strong><br>
<a class="btn" href="/watch/{{ group }}/{{ loop.index0 }}">▶ Watch</a>
<a class="btn" href="/low/{{ group }}/{{ loop.index0 }}">🔇 Low 144p</a>
</div></div>
{% endfor %}
</div></body></html>
"""

SEARCH_HTML = """<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Search</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:12px}
.card{display:flex;align-items:center;gap:10px;border:1px solid #0f0;border-radius:8px;padding:8px;margin:8px 0;background:#111}
.card img{width:42px;height:42px;background:#222;border-radius:6px}
a.btn{border:1px solid #0f0;color:#0f0;padding:6px 8px;border-radius:6px;text-decoration:none;margin-right:8px}
a.btn:hover{background:#0f0;color:#000}
</style></head><body>
<h3>Search results for "{{ query }}"</h3>
<a href="/">← Back</a>
<div>
{% for r in results %}
<div class="card">
<img src="{{ r.logo or fallback }}" onerror="this.src='{{ fallback }}'">
<div style="flex:1">
<strong>{{ r.title }}</strong><br>
<a class="btn" href="/watch/all/{{ r.index }}">▶ Watch</a>
<a class="btn" href="/low/all/{{ r.index }}">🔇 Low 144p</a>
</div></div>
{% endfor %}
{% if not results %}
<p>No results found.</p>
{% endif %}
</div></body></html>
"""

WATCH_HTML = """<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ channel.title }}</title>
<style>body{background:#000;color:#0f0;margin:0;font-family:Arial;text-align:center;padding:10px}video{width:100%;height:auto;max-height:85vh;border:2px solid #0f0;margin-top:10px}</style>
</head><body>
<h3>{{ channel.title }}</h3>
<video controls autoplay playsinline>
<source src="{{ channel.url }}" type="{{ mime_type }}">
</video>
</body></html>
"""

# =========================
# Routes
# =========================
@app.route("/")
def home():
    return render_template_string(HOME_HTML, playlists=PLAYLISTS)

@app.route("/list/<group>")
def list_group(group):
    if group not in PLAYLISTS:
        abort(404)
    channels=get_channels(group)
    return render_template_string(LIST_HTML, group=group, channels=channels, fallback=LOGO_FALLBACK)

@app.route("/search")
def search():
    q=request.args.get("q","").strip().lower()
    all_channels=get_channels("all")
    results=[]
    for idx,ch in enumerate(all_channels):
        if q in ch.get("title","").lower() or q in ch.get("group","").lower() or q in ch.get("url","").lower():
            results.append({"index":idx,"title":ch["title"],"url":ch["url"],"logo":ch.get("logo","")})
    return render_template_string(SEARCH_HTML, query=q, results=results, fallback=LOGO_FALLBACK)

@app.route("/watch/<group>/<int:idx>")
def watch(group, idx):
    channels=get_channels(group)
    if idx<0 or idx>=len(channels):
        abort(404)
    ch=channels[idx]
    mime="application/vnd.apple.mpegurl" if ".m3u8" in ch["url"] else "video/mp4"
    return render_template_string(WATCH_HTML, channel=ch, mime_type=mime)

@app.route("/low/<group>/<int:idx>")
def low(group, idx):
    channels=get_channels(group)
    if idx<0 or idx>=len(channels):
        abort(404)
    url=channels[idx]["url"]
    cmd=[
        "ffmpeg","-loglevel","error",
        "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","5",
        "-i",url,"-an","-vf","scale=256:144","-r","15",
        "-c:v","libx264","-preset","ultrafast","-tune","zerolatency",
        "-b:v","40k","-maxrate","40k","-bufsize","240k","-g","30",
        "-f","mpegts","pipe:1"
    ]
    def gen():
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        try:
            while True:
                d=p.stdout.read(4096)
                if not d: break
                yield d
        finally:
            p.terminate()
            p.wait()
    return Response(stream_with_context(gen()), mimetype="video/mp2t")

@app.route("/random-low")
def random_low():
    channels=get_channels("all")
    if not channels:
        abort(404)
    idx=random.randint(0,len(channels)-1)
    return low("all", idx)

# =========================
# Entry
# =========================
if __name__=="__main__":
    print("IPTV Restream running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)