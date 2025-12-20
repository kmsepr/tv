#!/usr/bin/env python3
import os, time, logging, random, requests, subprocess
from flask import Flask, Response, render_template_string, abort, stream_with_context, request

# ============================================================
# BASIC SETUP
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
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "kids": "https://iptv-org.github.io/iptv/categories/kids.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "arabic": "https://iptv-org.github.io/iptv/languages/ara.m3u",
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
            title = lines[i].split(",",1)[-1]
            logo = ""
            if 'tvg-logo="' in lines[i]:
                logo = lines[i].split('tvg-logo="')[1].split('"')[0]
            url = lines[i+1]
            out.append({"title": title, "url": url, "logo": logo})
            i += 2
        else:
            i += 1
    return out

def get_channels(group):
    now = time.time()
    if group in CACHE and now - CACHE[group]["time"] < REFRESH_INTERVAL:
        return CACHE[group]["channels"]
    url = PLAYLISTS[group]
    r = requests.get(url, timeout=25)
    r.raise_for_status()
    ch = parse_m3u(r.text)
    CACHE[group] = {"time": now, "channels": ch}
    return ch

# ============================================================
# HTML TEMPLATES
# ============================================================
HOME_HTML = """
<!doctype html><html><head>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>IPTV</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:16px}
a{color:#0f0;border:1px solid #0f0;padding:10px;margin:6px;
text-decoration:none;border-radius:8px;display:inline-block}
a:hover{background:#0f0;color:#000}
</style></head><body>
<h2>📺 IPTV</h2>
<a href="/random">🎲 Random</a>
<a href="/favourites" style="color:yellow;border-color:yellow">⭐ Favourites</a>
<hr>
{% for k in playlists %}
<a href="/list/{{k}}">{{k|capitalize}}</a>
{% endfor %}
</body></html>
"""

LIST_HTML = """
<!doctype html><html><head>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{{group}}</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:12px}
.card{border:1px solid #0f0;border-radius:8px;padding:8px;margin:8px 0;background:#111}
.btn{border:1px solid #0f0;color:#0f0;padding:6px 10px;border-radius:6px;text-decoration:none}
.btn:hover{background:#0f0;color:#000}
</style></head><body>
<h3>{{group|capitalize}}</h3>
<a href="/">← Back</a>
{% for ch in channels %}
<div class="card">
<b>{{ch.title}}</b><br><br>
<a class="btn" href="/watch/{{group}}/{{loop.index0}}" target="_blank">▶ Watch</a>
<a class="btn" href="/stream-noaudio/{{group}}/{{loop.index0}}" target="_blank">🔇 144p</a>
<button class="btn" onclick='fav("{{ch.title}}","{{ch.url}}")'>⭐</button>
</div>
{% endfor %}
<script>
function fav(t,u){
let f=JSON.parse(localStorage.getItem("favs")||"[]");
if(!f.find(x=>x.url===u)){
f.push({title:t,url:u});
localStorage.setItem("favs",JSON.stringify(f));
alert("Added");
}}
</script>
</body></html>
"""

WATCH_HTML = """
<!doctype html><html><head>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{{channel.title}}</title>
<style>
body{background:#000;color:#0f0;text-align:center}
video{width:100%;max-height:90vh;border:2px solid #0f0}
</style></head><body>
<h3>{{channel.title}}</h3>
<video controls autoplay playsinline>
<source src="{{channel.url}}" type="application/vnd.apple.mpegurl">
</video>
</body></html>
"""

FAV_HTML = """
<!doctype html><html><head>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Favourites</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:12px}
.card{border:1px solid yellow;border-radius:8px;padding:8px;margin:8px;background:#111}
.btn{border:1px solid yellow;color:yellow;padding:6px;border-radius:6px;text-decoration:none}
</style></head><body>
<h2>⭐ Favourites</h2>
<a href="/">← Back</a>
<div id="list"></div>
<script>
let f=JSON.parse(localStorage.getItem("favs")||"[]");
let h="";
f.forEach((c,i)=>{
h+=`<div class=card>
<b>${c.title}</b><br><br>
<a class=btn href="/watch-direct?u=${encodeURIComponent(c.url)}" target=_blank>▶ Watch</a>
<a class=btn href="/stream-direct?u=${encodeURIComponent(c.url)}" target=_blank>🔇 144p</a>
<button class=btn onclick="del(${i})">❌</button>
</div>`;
});
document.getElementById("list").innerHTML=h||"No favourites";
function del(i){
f.splice(i,1);
localStorage.setItem("favs",JSON.stringify(f));
location.reload();
}
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
    if group not in PLAYLISTS: abort(404)
    return render_template_string(LIST_HTML, group=group, channels=get_channels(group))

@app.route("/watch/<group>/<int:i>")
def watch(group,i):
    ch=get_channels(group)[i]
    return render_template_string(WATCH_HTML, channel=ch)

@app.route("/watch-direct")
def watch_direct():
    u=request.args.get("u")
    return render_template_string(WATCH_HTML, channel={"title":"Channel","url":u})

@app.route("/random")
def rnd():
    ch=random.choice(get_channels("all"))
    return render_template_string(WATCH_HTML, channel=ch)

@app.route("/favourites")
def fav():
    return render_template_string(FAV_HTML)

# ============================================================
# 🔥 IPTV NO-AUDIO STREAM (BUFFERING FIXED)
# ============================================================
def ffmpeg_stream(url):
    cmd=[
        "ffmpeg","-loglevel","error",
        "-fflags","+nobuffer","-flags","low_delay",
        "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","5",
        "-i",url,
        "-an",
        "-vf","scale=256:144","-r","15",
        "-c:v","libx264","-preset","ultrafast","-tune","zerolatency",
        "-b:v","40k","-maxrate","40k","-bufsize","240k",
        "-g","30",
        "-f","mpegts","pipe:1"
    ]
    p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
    try:
        while True:
            d=p.stdout.read(4096)
            if not d: break
            yield d
    finally:
        p.terminate(); p.wait()

@app.route("/stream-noaudio/<group>/<int:i>")
def stream_noaudio(group,i):
    url=get_channels(group)[i]["url"]
    return Response(stream_with_context(ffmpeg_stream(url)),
                    mimetype="video/mp2t")

@app.route("/stream-direct")
def stream_direct():
    u=request.args.get("u")
    return Response(stream_with_context(ffmpeg_stream(u)),
                    mimetype="video/mp2t")

# ============================================================
# ENTRY
# ============================================================
if __name__=="__main__":
    print("▶ IPTV running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0",port=8000,threaded=True)