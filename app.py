"""Edge Reader Web - upload chapters, listen with Microsoft Edge neural voices."""
import asyncio, io, re, os, zipfile
from pathlib import Path
import edge_tts
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel
import hmac, secrets, time, logging
from fastapi import Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

log = logging.getLogger("uvicorn.error")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(32)
if not os.environ.get("SECRET_KEY"):
    log.warning("SECRET_KEY not set - generated a random one; logins reset on restart.")
if not APP_PASSWORD:
    log.warning("APP_PASSWORD not set - ALL ACCESS IS BLOCKED until you set it.")

app = FastAPI(title="Edge Reader Web", docs_url=None, redoc_url=None, openapi_url=None)

FAILS: dict[str, list[float]] = {}
MAX_FAILS, WINDOW = 5, 300  # 5 failed tries per 5 min per IP

def client_ip(req: Request) -> str:
    fwd = req.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "?")

LOGIN_HTML = """<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Edge Reader - Login</title><style>body{font-family:system-ui;background:#111;color:#eee;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
form{width:90%;max-width:360px}input,button{width:100%;font-size:1.1rem;min-height:52px;border-radius:10px;border:0;margin:8px 0;padding:0 14px;box-sizing:border-box}
button{background:#2d6cdf;color:#fff}.e{color:#ff7b7b}</style></head><body><form method=post action=/login>
<h1>📖 Edge Reader</h1><p class=e>{msg}</p><input type=password name=password placeholder=Password autofocus autocomplete=current-password>
<button>Log in</button></form></body></html>"""

def login_page(msg="", code=200):
    return HTMLResponse(LOGIN_HTML.replace("{msg}", msg), status_code=code)

@app.middleware("http")
async def auth(request: Request, call_next):
    if not APP_PASSWORD:
        return HTMLResponse("<h2 style='font-family:system-ui'>Set APP_PASSWORD</h2><p>This server has no password configured, so access is blocked.</p>", 503)
    if request.url.path in ("/login", "/healthz") or request.session.get("auth"):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Not logged in"}, 401)
    return RedirectResponse("/login", 303)

@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.get("/login")
async def login_form():
    return login_page()

@app.post("/login")
async def login(request: Request, password: str = Form("")):
    ip, now = client_ip(request), time.time()
    FAILS[ip] = [t for t in FAILS.get(ip, []) if now - t < WINDOW]
    if len(FAILS[ip]) >= MAX_FAILS:
        return login_page("Too many attempts. Try again in a few minutes.", 429)
    if hmac.compare_digest(password.encode(), APP_PASSWORD.encode()):
        FAILS.pop(ip, None)
        request.session["auth"] = True
        return RedirectResponse("/", 303)
    FAILS[ip].append(now)
    return login_page("Wrong password.", 401)

@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 303)
STATIC = Path(__file__).parent / "static"
HEADING = re.compile(r"^\s*(?:#{1,3}\s+.+|(?:chapter|ch\.|prologue|epilogue|part)\b.*)$", re.I)

def extract(name: str, data: bytes) -> str:
    ext = Path(name).suffix.lower()
    if ext in (".txt", ".md", ".markdown", ""):
        return data.decode("utf-8", errors="replace")
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        out = []
        for p in d.paragraphs:
            t = p.text.strip()
            if p.style.name.lower().startswith("heading") and t:
                t = "# " + t
            out.append(t)
        return "\n".join(out)
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages)
    if ext == ".epub":
        from bs4 import BeautifulSoup
        z = zipfile.ZipFile(io.BytesIO(data))
        opf_path = re.search(r'full-path="([^"]+)"', z.read("META-INF/container.xml").decode()).group(1)
        opf = BeautifulSoup(z.read(opf_path), "xml")
        base = os.path.dirname(opf_path)
        items = {i["id"]: i["href"] for i in opf.find_all("item")}
        parts = []
        for ref in opf.find_all("itemref"):
            href = items.get(ref["idref"]); 
            if not href: continue
            soup = BeautifulSoup(z.read(os.path.normpath(os.path.join(base, href)).replace("\\", "/")), "html.parser")
            for h in soup.find_all(["h1", "h2", "h3"]):
                h.replace_with("\n# " + h.get_text(" ", strip=True) + "\n")
            parts.append(soup.get_text("\n"))
        return "\n".join(parts)
    raise HTTPException(400, f"Unsupported file type: {ext}")

def clean_md(t: str) -> str:
    t = re.sub(r"^#+\s*", "", t, flags=re.M)
    t = re.sub(r"[*_`]{1,3}", "", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()

def split_chapters(text: str, fname: str):
    lines = text.splitlines()
    chapters, title, buf = [], None, []
    def flush():
        body = clean_md("\n".join(buf))
        if body or title:
            chapters.append({"title": clean_md(title) if title else None, "text": body})
    for ln in lines:
        if HEADING.match(ln) and len(ln.strip()) < 120:
            flush(); title, buf = ln.strip(), []
        else:
            buf.append(ln)
    flush()
    chapters = [c for c in chapters if c["text"]]
    if not chapters:
        chapters = [{"title": None, "text": clean_md(text)}]
    for i, c in enumerate(chapters):
        c["title"] = c["title"] or (Path(fname).stem if len(chapters) == 1 else f"Section {i+1}")
        c["chars"] = len(c["text"])
    return chapters

@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    result = []
    for f in files:
        data = await f.read()
        text = extract(f.filename, data)
        for c in split_chapters(text, f.filename):
            c["source"] = f.filename
            result.append(c)
    if not result:
        raise HTTPException(400, "No text found")
    return {"chapters": result}

_voices = None
@app.get("/api/voices")
async def voices(all: bool = False):
    global _voices
    if _voices is None:
        _voices = await edge_tts.list_voices()
    vs = _voices if all else [v for v in _voices if v["Locale"].startswith("en-")]
    return [{"name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"]} for v in vs]

def chunks(text: str, size: int = 1800):
    sents = re.split(r"(?<=[.!?…\"”])\s+|\n+", text)
    cur = ""
    for s in sents:
        s = s.strip()
        if not s: continue
        while len(s) > size:
            yield s[:size]; s = s[size:]
        if len(cur) + len(s) + 1 > size:
            yield cur; cur = s
        else:
            cur = f"{cur} {s}" if cur else s
    if cur: yield cur

SYNTH_CONCURRENCY = 4

def rate_str(speed: float) -> str:
    speed = max(0.5, min(3.0, speed))
    return f"{round((speed - 1) * 100):+d}%"

class SynthReq(BaseModel):
    text: str
    voice: str = "en-US-AriaNeural"
    speed: float = 1.0

@app.post("/api/synthesize")
async def synthesize(req: SynthReq):
    if not req.text.strip():
        raise HTTPException(400, "Empty text")
    rate = rate_str(req.speed)
    sem = asyncio.Semaphore(SYNTH_CONCURRENCY)

    async def synth_one(part: str) -> bytes:
        async with sem:
            for attempt in range(2):  # one retry
                try:
                    buf = bytearray()
                    async for ev in edge_tts.Communicate(part, req.voice, rate=rate).stream():
                        if ev["type"] == "audio":
                            buf += ev["data"]
                    if not buf:
                        raise RuntimeError("no audio returned")
                    return bytes(buf)
                except Exception as e:
                    if attempt:
                        raise
                    log.warning("chunk synth failed (%s); retrying once", e)
                    await asyncio.sleep(0.5)

    try:
        parts = await asyncio.gather(*(synth_one(c) for c in chunks(req.text)))
    except Exception as e:
        raise HTTPException(502, f"Speech service error: {e}")
    out = b"".join(parts)  # gather preserves input order
    return Response(bytes(out), media_type="audio/mpeg")

@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")

# Added last so it wraps everything (runs before the auth middleware).
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="er_session",
                   max_age=30*24*3600, same_site="lax",
                   https_only=os.environ.get("COOKIE_SECURE", "1" if os.environ.get("RENDER") else "0") == "1")
