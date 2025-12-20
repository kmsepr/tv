#!/usr/bin/env python3
import time, logging, subprocess, requests
from flask import Flask, Response, render_template_string, abort, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -----------------------------
# IPTV SOURCE
# -----------------------------
PLAYLIST_URL = "https://iptv-org.github.io/iptv/countries/in.m3u"
CACHE, CACHE_TIME = [], 0
CACHE_TTL = 1800

def load_channels():
    global CACHE, CACHE_TIME
    if time.time() - CACHE_TIME < CACHE_TTL and CACHE:
        return CACHE

    txt = requests.get(PLAYLIST_URL, timeout=20).text
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    out = []
    for i in range(len(lines)):
        if lines[i].startswith("#EXTINF") and i+1 < len(lines):
            out.append({
                "idx": i,
                "title": lines[i].split(",",1)[-1],
                "url": lines[i+1]
            })
    CACHE, CACHE_TIME = out, time.time()
    return out

# -----------------------------
# UI (keypad + localStorage)
# -----------------------------
HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
form{display:flex;gap:6px;margin-bottom:10px}
input{flex:1;padding:12px;font-size:16px;border-radius:8px;border:1px solid #0f0;background:#111;color:#0f0}
button,a.btn{padding:12px 16px;font-size:18px;border-radius:8px;border:1px solid #0f0;background:#111;color:#0f0;text-decoration:none}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.card{border:1px solid #0f0;border-radius:10px;padding:10px;background:#111}
.card h4{margin:0 0 10px 0;font-size:14px}
a.link{display:block;margin:6px 0;padding:6px;border:1px solid #0f0;border-radius:6px;text-align:center}
.fav{font-size:12px;padding:4px;margin-top:6px}
</style>

<script>
function favs(){return JSON.parse(localStorage.getItem("iptv_favs")||"[]")}
function save(f){localStorage.setItem("iptv_favs",JSON.stringify(f))}
function toggle(i){
 let f=favs(); f.includes(i)?f=f.filter(x=>x!=i):f.push(i);
 save(f); location.reload();
}
</script>
</head>

<body>
<h3>📺 IPTV</h3>

<form method="get" action="/search">
<input name="q" placeholder="Search channels">
<button>🔍</button>
</form>

{% if page=="home" %}
<div id="fav" class="grid"></div>
<script>
const ch={{ channels|tojson }};
const f=favs();
const box=document.getElementById("fav");
if(!f.length){box.innerHTML="<p>No favourites yet. Use search.</p>";}
f.forEach(i=>{
 box.innerHTML+=`
 <div class="card">
 <h4>${ch[i].title}</h4>
 <a class="link" href="/watch/${i}">▶ Watch</a>
 <a class="link" href="/watch-low/${i}">🔇 144p</a>
 <button class="fav" onclick="toggle(${i})">❌ Remove</button>
 </div>`;
});
</script>
{% else %}
<div class="grid">
{% for c in channels %}
<div class="card">
<h4>{{ c.title }}</h4>
<a class="link" href="/watch/{{ c.idx }}">▶ Watch</a>
<a class="link" href="/watch-low/{{ c.idx }}">🔇 144p</a>
<button class="fav" onclick="toggle({{ c.idx }})">⭐ Favourite</button>
</div>
{% endfor %}
</div>
{% endif %}
</body>
</html>
"""

# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return render_template_string(HTML, channels=load_channels(), page="home")

@app.route("/search")
def search():
    q=request.args.get("q","").lower()
    res=[c for c in load_channels() if q in c["title"].lower()]
    return render_template_string(HTML, channels=res, page="search")

@app.route("/watch/<int:i>")
def watch(i):
    c=load_channels()
    if i>=len(c):abort(404)
    return f"<video controls autoplay src='{c[i]['url']}' style='width:100%;height:100vh'></video>"

@app.route("/watch-low/<int:i>")
def low(i):
    return f"<video controls autoplay src='/stream/{i}' style='width:100%;height:100vh'></video>"

@app.route("/stream/<int:i>")
def stream(i):
    url=load_channels()[i]["url"]
    cmd=["ffmpeg","-loglevel","error","-i",url,"-an",
         "-vf","scale=256:144","-r","15",
         "-c:v","libx264","-preset","ultrafast",
         "-b:v","40k","-f","mpegts","pipe:1"]
    def gen():
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE)
        while True:
            d=p.stdout.read(4096)
            if not d:break
            yield d
    return Response(gen(),mimetype="video/mp2t")

if __name__=="__main__":
    app.run(host="0.0.0.0",port=8000,threaded=True)