#!/usr/bin/env python3
import time
import random
import logging
import subprocess
from flask import Flask, Response, render_template_string, abort, stream_with_context, request
import requests

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

REFRESH_INTERVAL = 1800

# --------------------------
# IPTV Playlists
# --------------------------
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
    "english": "https://iptv-org.github.io/iptv/languages/eng.m3u",
    "hindi": "https://iptv-org.github.io/iptv/languages/hin.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
}

CACHE = {}

# --------------------------
# M3U Parser
# --------------------------
def parse_extinf(line):
    if "," in line:
        left, title = line.split(",",1)
    else:
        left, title = line, ""
    attrs = {}
    pos=0
    while True:
        eq = left.find("=", pos)
        if eq==-1: break
        key_start = left.rfind(" ",0,eq)
        colon = left.rfind(":",0,eq)
        if colon>key_start: key_start=colon
        key = left[key_start+1:eq].strip()
        if eq+1<len(left) and left[eq+1]=='"':
            val_start = eq+2
            val_end = left.find('"', val_start)
            if val_end==-1: break
            val=left[val_start:val_end]
            pos=val_end+1
        else:
            val_end=left.find(" ", eq+1)
            if val_end==-1: val_end=len(left)
            val=left[eq+1:val_end].strip()
            pos=val_end
        attrs[key]=val
    return attrs, title.strip()

def parse_m3u(text):
    lines=[l.strip() for l in text.splitlines() if l.strip()]
    channels=[]
    i=0
    while i<len(lines):
        if lines[i].startswith("#EXTINF"):
            attrs,title=parse_extinf(lines[i])
            j=i+1
            url=None
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

# --------------------------
# Get channels with cache
# --------------------------
def get_channels(name):
    now = time.time()
    cached = CACHE.get(name)
    if cached and now - cached.get("time",0)<REFRESH_INTERVAL:
        return cached["channels"]
    url = PLAYLISTS.get(name)
    if not url:
        return []
    try:
        r = requests.get(url, timeout=25)
        r.raise_for_status()
        channels=parse_m3u(r.text)
        CACHE[name]={"time":now,"channels":channels}
        logging.info("[%s] Loaded %d channels", name, len(channels))
        return channels
    except Exception as e:
        logging.error("Failed %s: %s", name, e)
        return []

# --------------------------
# HTML Templates
# --------------------------
HOME_HTML = """
<!doctype html><html>
<head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV Low</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:16px}
a{color:#0f0;text-decoration:none;border:1px solid #0f0;padding:10px;margin:8px;border-radius:8px;display:inline-block}
a:hover{background:#0f0;color:#000}
</style>
</head>
<body>
<h2>🌐 IPTV Low 144p</h2>
<a href="/random">🎲 Random Channel</a>
<p>Select a category:</p>
{% for key in playlists %}
<a href="/list/{{ key }}">{{ key|capitalize }}</a>
{% endfor %}
<form action="/search" method="get" style="margin-top:12px;">
<input name="q" placeholder="Search..." style="padding:8px;border-radius:6px;background:#111;border:1px solid #0f0;color:#0f0">
<button type="submit" style="padding:6px 12px;border-radius:6px;background:#0f0;color:#000;border:none">🔍</button>
</form>
</body></html>
"""

LIST_HTML = """
<!doctype html><html>
<head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ group|capitalize }}</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:12px}
.card{border:1px solid #0f0;border-radius:8px;padding:8px;margin:6px 0;background:#111}
a{color:#0f0;text-decoration:none;border:1px solid #0f0;padding:6px 8px;border-radius:6px;margin-right:6px}
a:hover{background:#0f0;color:#000}
</style>
</head>
<body>
<h3>{{ group|capitalize }} Channels</h3>
<a href="/">← Back</a>
<div>
{% for ch in channels %}
<div class="card">
<strong>{{ ch.title }}</strong><br>
<a href="/low/{{ group }}/{{ loop.index0 }}">▶ Low 144p</a>
</div>
{% endfor %}
</div>
</body>
</html>
"""

SEARCH_HTML = """
<!doctype html><html>
<head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Search</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:12px}
.card{border:1px solid #0f0;border-radius:8px;padding:8px;margin:6px 0;background:#111}
a{color:#0f0;text-decoration:none;border:1px solid #0f0;padding:6px 8px;border-radius:6px;margin-right:6px}
a:hover{background:#0f0;color:#000}
</style>
</head>
<body>
<h3>Search results for: "{{ query }}"</h3>
<a href="/">← Back</a>
<div>
{% if results %}
{% for r in results %}
<div class="card">
<strong>{{ r.title }}</strong><br>
<a href="/low/all/{{ r.index }}">▶ Low 144p</a>
</div>
{% endfor %}
{% else %}
<p>No results found.</p>
{% endif %}
</div>
</body>
</html>
"""

LOW_HTML = """
<!doctype html><html>
<head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ channel.title }} - Low 144p</title>
</head>
<body style="background:#000;color:#0f0;text-align:center;padding:10px">
<h3>{{ channel.title }} - Low 144p</h3>
<video controls autoplay playsinline style="width:100%;max-height:80vh;">
<source src="{{ low_url }}" type="video/mp2t">
</video>
</body>
</html>
"""

# --------------------------
# Routes
# --------------------------
@app.route("/")
def home():
    return render_template_string(HOME_HTML, playlists=PLAYLISTS.keys())

@app.route("/list/<group>")
def list_group(group):
    if group not in PLAYLISTS:
        abort(404)
    channels = get_channels(group)
    return render_template_string(LIST_HTML, group=group, channels=channels)

@app.route("/search")
def search():
    q = request.args.get("q","").strip().lower()
    all_ch = get_channels("all")
    results=[]
    for idx,ch in enumerate(all_ch):
        if q in (ch.get("title") or "").lower():
            results.append({"index":idx,"title":ch.get("title")})
    return render_template_string(SEARCH_HTML, query=q, results=results)

@app.route("/random")
def random_channel():
    chs = get_channels("all")
    if not chs:
        abort(404)
    ch = random.choice(chs)
    idx = chs.index(ch)
    return f'<script>window.location="/low/all/{idx}"</script>'

@app.route("/low/<group>/<int:idx>")
def low_page(group, idx):
    channels = get_channels(group)
    if idx<0 or idx>=len(channels):
        abort(404)
    ch = channels[idx]
    low_url = f"/low-stream/{group}/{idx}"
    return render_template_string(LOW_HTML, channel=ch, low_url=low_url)

@app.route("/low-stream/<group>/<int:idx>")
def low_stream(group, idx):
    channels = get_channels(group)
    if idx<0 or idx>=len(channels):
        abort(404)
    url = channels[idx]["url"]
    cmd=[
        "ffmpeg","-loglevel","error",
        "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","5",
        "-i",url,
        "-an",
        "-vf","scale=256:144",
        "-r","15",
        "-c:v","libx264","-preset","ultrafast","-tune","zerolatency",
        "-b:v","40k","-maxrate","40k","-bufsize","240k",
        "-g","30",
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
    return Response(stream_with_context(gen()), headers={"Content-Type":"video/mp2t","Cache-Control":"no-cache"})

# --------------------------
if __name__=="__main__":
    print("IPTV Low 144p running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)