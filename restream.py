#!/usr/bin/env python3
import time, random, logging, requests, subprocess
from flask import Flask, Response, render_template_string, abort, stream_with_context, request

# ============================================================
# SETUP
# ============================================================
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

REFRESH_INTERVAL = 1800
LOGO_FALLBACK = "https://iptv-org.github.io/assets/logo.png"

PLAYLISTS = {
    "all": "https://iptv-org.github.io/iptv/index.m3u",
    "india": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
}

CACHE = {}

# ============================================================
# M3U PARSER
# ============================================================
def parse_m3u(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            title = lines[i].split(",", 1)[-1]
            url = lines[i + 1]
            out.append({"title": title, "url": url, "logo": ""})
            i += 2
        else:
            i += 1
    return out

def get_channels(name):
    now = time.time()
    if name in CACHE and now - CACHE[name]["time"] < REFRESH_INTERVAL:
        return CACHE[name]["channels"]
    r = requests.get(PLAYLISTS[name], timeout=25)
    ch = parse_m3u(r.text)
    CACHE[name] = {"time": now, "channels": ch}
    return ch

# ============================================================
# STREAM PROXIES
# ============================================================
def proxy_audio_only(url):
    cmd = ["ffmpeg", "-i", url, "-vn", "-ac", "1", "-b:a", "40k", "-f", "mp3", "pipe:1"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for c in iter(lambda: p.stdout.read(1024), b""):
        yield c

def proxy_video_144p(url):
    cmd = [
        "ffmpeg", "-i", url, "-an",
        "-vf", "scale=-2:144",
        "-b:v", "40k",
        "-preset", "veryfast",
        "-movflags", "frag_keyframe+empty_moov",
        "-f", "mp4", "pipe:1"
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for c in iter(lambda: p.stdout.read(1024), b""):
        yield c

# ============================================================
# BIG TEXT HTML
# ============================================================
BASE_STYLE = """
<style>
body{
 background:black;color:#0f0;
 font-family:Arial;
 font-size:22px;
 padding:14px;
}
a,button{
 font-size:22px;
 padding:14px;
 margin:6px;
 display:inline-block;
 border:2px solid #0f0;
 color:#0f0;
 background:black;
 text-decoration:none;
 border-radius:10px;
}
button{cursor:pointer}
hr{border:1px solid #0f0}
</style>
"""

HOME_HTML = """
<!doctype html><html><head>{{style}}</head><body>
<h2>📺 IPTV</h2>
{% for k in playlists %}
<a href="/list/{{k}}">{{k|upper}}</a><br><br>
{% endfor %}
<a href="/random">🎲 RANDOM</a>
<a href="/favourites">⭐ FAVOURITES</a>
</body></html>
"""

LIST_HTML = """
<!doctype html><html><head>{{style}}</head><body>
<h2>{{group|upper}}</h2>
<a href="/">⬅ BACK</a><hr>
{% for ch in channels %}
<div>
<b>{{loop.index}}. {{ch.title}}</b><br><br>
<a href="/watch/{{group}}/{{loop.index0}}">▶ WATCH</a>
<a href="/play-144p/{{group}}/{{loop.index0}}">📺 144P</a>
<a href="/play-audio/{{group}}/{{loop.index0}}">🎧 AUDIO</a>
<button onclick='fav("{{ch.title}}","{{ch.url}}")'>⭐</button>
</div><hr>
{% endfor %}
<script>
function fav(t,u){
 let f=JSON.parse(localStorage.getItem("favs")||"[]");
 if(!f.find(x=>x.url==u)){
  f.push({title:t,url:u});
  localStorage.setItem("favs",JSON.stringify(f));
  alert("Added");
 }
}
</script>
</body></html>
"""

WATCH_HTML = """
<!doctype html><html><head>{{style}}</head><body>
<h2>{{channel.title}}</h2>
<video controls autoplay style="width:100%;max-height:85vh;border:3px solid #0f0">
 <source src="{{channel.url}}">
</video>
</body></html>
"""

FAV_HTML = """
<!doctype html><html><head>{{style}}</head><body>
<h2>⭐ FAVOURITES</h2>
<a href="/">⬅ BACK</a><hr>
<div id="f"></div>
<script>
let f=JSON.parse(localStorage.getItem("favs")||"[]");
let h="";
f.forEach(c=>{
 h+=`<div><b>${c.title}</b><br><br>
 <a href="/watch-direct?u=${encodeURIComponent(c.url)}">▶</a>
 <a href="/play-144p-direct?u=${encodeURIComponent(c.url)}">📺144P</a>
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
    return render_template_string(HOME_HTML, playlists=PLAYLISTS, style=BASE_STYLE)

@app.route("/list/<group>")
def list_group(group):
    return render_template_string(
        LIST_HTML, group=group,
        channels=get_channels(group),
        style=BASE_STYLE
    )

@app.route("/random")
def random_play():
    ch = random.choice(get_channels("all"))
    return render_template_string(WATCH_HTML, channel=ch, style=BASE_STYLE)

@app.route("/watch/<group>/<int:i>")
def watch(group, i):
    ch = get_channels(group)[i]
    return render_template_string(WATCH_HTML, channel=ch, style=BASE_STYLE)

@app.route("/play-audio/<group>/<int:i>")
def play_audio(group, i):
    return Response(
        stream_with_context(proxy_audio_only(get_channels(group)[i]["url"])),
        mimetype="audio/mpeg"
    )

@app.route("/play-144p/<group>/<int:i>")
def play_144p(group, i):
    return Response(
        stream_with_context(proxy_video_144p(get_channels(group)[i]["url"])),
        mimetype="video/mp4"
    )

@app.route("/play-audio-direct")
def audio_direct():
    return Response(stream_with_context(proxy_audio_only(request.args["u"])), mimetype="audio/mpeg")

@app.route("/play-144p-direct")
def video_direct():
    return Response(stream_with_context(proxy_video_144p(request.args["u"])), mimetype="video/mp4")

@app.route("/watch-direct")
def watch_direct():
    return render_template_string(
        WATCH_HTML,
        channel={"title": "Channel", "url": request.args["u"]},
        style=BASE_STYLE
    )

@app.route("/favourites")
def favs():
    return render_template_string(FAV_HTML, style=BASE_STYLE)

# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    print("Running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)