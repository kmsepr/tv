#!/usr/bin/env python3
import os, time, logging, random, requests, subprocess
from flask import Flask, Response, render_template_string, abort, stream_with_context, request

# =============================
# Setup
# =============================
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
PORT = 8000

REFRESH_INTERVAL = 1800
LOGO_FALLBACK = "https://iptv-org.github.io/assets/logo.png"

# =============================
# Playlists
# =============================
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
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "english": "https://iptv-org.github.io/iptv/languages/eng.m3u"
}

CACHE = {}

# =============================
# M3U Parser
# =============================
def parse_extinf(line):
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
        key_start = max(left.rfind(" ", 0, key_end), left.rfind(":", 0, key_end))
        key = left[key_start+1:key_end].strip()
        if eq+1 < len(left) and left[eq+1] == '"':
            val_start = eq+2
            val_end = left.find('"', val_start)
            if val_end == -1: break
            val = left[val_start:val_end]
            pos = val_end+1
        else:
            val_end = left.find(" ", eq+1)
            if val_end == -1: val_end=len(left)
            val = left[eq+1:val_end].strip()
            pos = val_end
        attrs[key]=val
    return attrs, title.strip()

def parse_m3u(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
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
                    "tvg_id": attrs.get("tvg-id") or ""
                })
            i=j+1
        else:
            i+=1
    return channels

# =============================
# Cache loader
# =============================
def get_channels(name):
    now=time.time()
    cached=CACHE.get(name)
    if cached and now-cached.get("time",0)<REFRESH_INTERVAL:
        return cached["channels"]
    url=PLAYLISTS.get(name)
    if not url: return []
    try:
        resp=requests.get(url, timeout=25)
        resp.raise_for_status()
        channels=parse_m3u(resp.text)
        CACHE[name]={"time":now,"channels":channels}
        return channels
    except: return []

# =============================
# Templates
# =============================
# Only WATCH_HTML, LIST_HTML, HOME_HTML, FAV_HTML, SEARCH_HTML remain
# Remove Audio buttons in LIST_HTML, FAV_HTML, SEARCH_HTML
# Keep 144p button

# =============================
# Routes
# =============================
@app.route("/")
def home(): return render_template_string(HOME_HTML, playlists=PLAYLISTS)

@app.route("/list/<group>")
def list_group(group):
    if group not in PLAYLISTS: abort(404)
    channels=get_channels(group)
    return render_template_string(LIST_HTML, group=group, channels=channels, fallback=LOGO_FALLBACK)

@app.route("/favourites")
def favourites(): return render_template_string(FAV_HTML)

@app.route("/search")
def search():
    q=request.args.get("q","").strip().lower()
    results=[]
    if q:
        all_ch=get_channels("all")
        for idx,ch in enumerate(all_ch):
            if q in (ch.get("title") or "").lower() or q in (ch.get("group") or "").lower():
                results.append({"index":idx,"title":ch.get("title"),"url":ch.get("url"),"logo":ch.get("logo")})
    return render_template_string(SEARCH_HTML, query=q, results=results)

@app.route("/random")
def random_global():
    ch=random.choice(get_channels("all"))
    mime="application/vnd.apple.mpegurl" if ".m3u8" in ch["url"] else "video/mp4"
    return render_template_string(WATCH_HTML, channel=ch, mime_type=mime)

@app.route("/watch/<group>/<int:idx>")
def watch_channel(group, idx):
    chs=get_channels(group)
    if idx<0 or idx>=len(chs): abort(404)
    ch=chs[idx]
    mime="application/vnd.apple.mpegurl" if ".m3u8" in ch["url"] else "video/mp4"
    return render_template_string(WATCH_HTML, channel=ch, mime_type=mime)

@app.route("/watch-direct")
def watch_direct():
    title=request.args.get("title","Channel")
    url=request.args.get("url")
    logo=request.args.get("logo","")
    if not url: return "Invalid URL",400
    ch={"title":title,"url":url,"logo":logo}
    mime="application/vnd.apple.mpegurl" if ".m3u8" in url else "video/mp4"
    return render_template_string(WATCH_HTML, channel=ch, mime_type=mime)

@app.route("/stream-noaudio/<group>/<int:idx>")
def stream_noaudio(group, idx):
    chs=get_channels(group)
    if idx<0 or idx>=len(chs): abort(404)
    url=chs[idx]["url"]
    cmd=[
        "ffmpeg","-loglevel","error",
        "-i",url,"-an","-vf","scale=256:144","-r","15",
        "-c:v","libx264","-preset","ultrafast","-tune","zerolatency",
        "-b:v","40k","-maxrate","40k","-bufsize","240k","-g","30","-f","mpegts","pipe:1"
    ]
    def gen():
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
        try:
            while True:
                chunk=proc.stdout.read(4096)
                if not chunk: break
                yield chunk
        finally: proc.terminate(); proc.wait()
    return Response(stream_with_context(gen()), mimetype="video/mp2t")

# =============================
# Start
# =============================
if __name__=="__main__":
    print(f"▶ IPTV running on http://0.0.0.0:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=True)