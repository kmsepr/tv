#!/usr/bin/env python3
import time, logging, subprocess, requests
from flask import Flask, Response, render_template_string, abort, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------
# PLAYLISTS (CATEGORIES)
# -------------------------------------------------
PLAYLISTS = {
    "India": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "USA": "https://iptv-org.github.io/iptv/countries/us.m3u",
    "UK": "https://iptv-org.github.io/iptv/countries/uk.m3u",
    "UAE": "https://iptv-org.github.io/iptv/countries/ae.m3u",

    "News": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "Sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "Movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "Music": "https://iptv-org.github.io/iptv/categories/music.m3u",

    "Malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "Hindi": "https://iptv-org.github.io/iptv/languages/hin.m3u",
    "Tamil": "https://iptv-org.github.io/iptv/languages/tam.m3u",
}

CACHE, CACHE_TTL = {}, 1800

def load_playlist(url):
    now = time.time()
    if url in CACHE and now - CACHE[url]["t"] < CACHE_TTL:
        return CACHE[url]["d"]

    txt = requests.get(url, timeout=20).text
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    out = []
    for i in range(len(lines)):
        if lines[i].startswith("#EXTINF") and i+1 < len(lines):
            out.append({
                "idx": i,
                "title": lines[i].split(",",1)[-1],
                "url": lines[i+1]
            })
    CACHE[url] = {"t": now, "d": out}
    return out

# -------------------------------------------------
# HTML (KEYPAD FRIENDLY + JS FAVOURITES)
# -------------------------------------------------
HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
h3{margin:6px 0}
.search{display:flex;gap:6px;margin-bottom:6px}
input{flex:1;padding:14px;font-size:18px;border:1px solid #0f0;background:#111;color:#0f0;border-radius:8px}
button{padding:14px 18px;font-size:20px;border:1px solid #0f0;background:#111;color:#0f0;border-radius:8px}
.nav{display:flex;gap:8px;margin-bottom:12px}
.nav a{flex:1;text-align:center;padding:14px;font-size:18px;
border:1px solid #0f0;background:#111;color:#0f0;border-radius:8px;text-decoration:none}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.card{border:1px solid #0f0;border-radius:10px;padding:10px;background:#111;text-align:center}
a.link{display:block;margin:6px 0;padding:10px;border:1px solid #0f0;border-radius:6px;color:#0f0;text-decoration:none}
.small{font-size:13px;padding:6px}
</style>

<script>
function favs(){return JSON.parse(localStorage.getItem("iptv_favs")||"[]")}
function save(f){localStorage.setItem("iptv_favs",JSON.stringify(f))}
function toggle(k){
 let f=favs();
 f.includes(k)?f=f.filter(x=>x!=k):f.push(k);
 save(f); location.reload();
}
</script>
</head>

<body>

<h3>📺 IPTV</h3>

<form method="get" action="/search" class="search">
<input name="q" placeholder="Search channels">
<button>🔍</button>
</form>

<div class="nav">
<a href="/">🏠 HOME</a>
<a href="/favourites">⭐ FAVOURITES</a>
</div>

{% if page=="home" %}
<div class="grid">
{% for i in items %}
<div class="card">
<a class="link" href="/category/{{ i.key }}">{{ i.name }}</a>
</div>
{% endfor %}
</div>

{% elif page=="list" %}
<div class="grid">
{% for i in items %}
<div class="card">
<b>{{ i.title }}</b>
<a class="link" href="/watch/{{ cat }}/{{ i.idx }}">▶ Watch</a>
<a class="link" href="/watch-low/{{ cat }}/{{ i.idx }}">🔇 144p</a>
<button class="small" onclick="toggle('{{ cat }}|{{ i.idx }}')">⭐ Favourite</button>
</div>
{% endfor %}
</div>

{% elif page=="favs" %}
<div id="favlist" class="grid"></div>

<script>
const favBox=document.getElementById("favlist");
const fav=favs();
if(!fav.length){
 favBox.innerHTML="<p>No favourites yet</p>";
}
fav.forEach(k=>{
 const [cat,idx]=k.split("|");
 favBox.innerHTML+=`
 <div class="card">
 <b>${cat}</b>
 <a class="link" href="/watch/${cat}/${idx}">▶ Watch</a>
 <a class="link" href="/watch-low/${cat}/${idx}">🔇 144p</a>
 <button class="small" onclick="toggle('${k}')">❌ Remove</button>
 </div>`;
});
</script>
{% endif %}

</body>
</html>
"""

# -------------------------------------------------
# ROUTES
# -------------------------------------------------
@app.route("/")
def home():
    items=[{"name":k,"key":k} for k in PLAYLISTS]
    return render_template_string(HTML,items=items,page="home")

@app.route("/category/<cat>")
def category(cat):
    if cat not in PLAYLISTS: abort(404)
    return render_template_string(
        HTML,
        items=load_playlist(PLAYLISTS[cat]),
        page="list",
        cat=cat
    )

@app.route("/search")
def search():
    q=request.args.get("q","").lower()
    res=[]
    for cat,url in PLAYLISTS.items():
        for c in load_playlist(url):
            if q in c["title"].lower():
                res.append(c)
    return render_template_string(HTML,items=res,page="list",cat=cat)

@app.route("/favourites")
def favourites():
    return render_template_string(HTML,items=[],page="favs")

@app.route("/watch/<cat>/<int:i>")
def watch(cat,i):
    ch=load_playlist(PLAYLISTS[cat])
    return f"<video controls autoplay src='{ch[i]['url']}' style='width:100%;height:100vh'></video>"

@app.route("/watch-low/<cat>/<int:i>")
def watch_low(cat,i):
    return f"<video controls autoplay src='/stream/{cat}/{i}' style='width:100%;height:100vh'></video>"

@app.route("/stream/<cat>/<int:i>")
def stream(cat,i):
    url=load_playlist(PLAYLISTS[cat])[i]["url"]
    cmd=["ffmpeg","-loglevel","error","-i",url,"-an",
         "-vf","scale=256:144","-r","15",
         "-c:v","libx264","-preset","ultrafast",
         "-b:v","40k","-f","mpegts","pipe:1"]
    def gen():
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE)
        while True:
            d=p.stdout.read(4096)
            if not d: break
            yield d
    return Response(gen(),mimetype="video/mp2t")

# -------------------------------------------------
if __name__=="__main__":
    app.run(host="0.0.0.0",port=8000,threaded=True)