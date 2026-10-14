# Edge Reader Web

Upload your chapter files and listen to them on your phone with Microsoft Edge neural voices (via `edge-tts`).

**Formats:** .txt, .md, .docx, .pdf, .epub. Chapters are split on headings like `Chapter 3`, `Prologue`, `Part II`, or markdown `#`/`##`/`###` (Word "Heading" styles count too). No headings means the whole file is one chapter.

## Run locally
```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export APP_PASSWORD='choose-a-password'   # Windows: set APP_PASSWORD=...
uvicorn app:app --host 0.0.0.0 --port 8000
```
Without `APP_PASSWORD` every page shows **"Set APP_PASSWORD"** and nothing works.
Open http://localhost:8000 on the computer.

**From your phone (same Wi-Fi):** find the computer's IP address (Windows: `ipconfig`, Mac: `ipconfig getifaddr en0`, Linux: `hostname -I`), then open `http://<that-IP>:8000` on the phone. Allow Python through the firewall if asked.

## Using it
- Upload one or more files, then tap a chapter to generate audio and play it.
- The speed slider (0.5x–3x) changes playback right away. Tap **Regenerate** to re-synthesize at that speed with natural pitch.
- Prev/Next buttons; it auto-advances when a chapter ends. Use **Download MP3** to save the audio.
- Settings, chapters, and your position are saved in the browser (localStorage).
- Needs internet, because the voices come from Microsoft's online service.

## Free hosting
- **Render** (render.com): New → Web Service → connect a GitHub repo containing this folder → it detects the Dockerfile. Free tier sleeps when idle, so the first load after a break is slow.
- Hugging Face Spaces (Docker), Fly.io, and Railway also work with the Dockerfile.


## Docker
```bash
docker build -t edge-reader-web .
docker run -p 8000:8000 edge-reader-web
```

## Password protection
- `APP_PASSWORD` (required): the login password. If it's unset, all access is blocked.
- `SECRET_KEY` (recommended): signs the session cookie. If it's unset, a random key is generated at startup and everyone gets logged out on restart.
- `COOKIE_SECURE`: set to `1` to make the cookie HTTPS-only (this is automatic on Render).
- Logins last 30 days. After 5 wrong passwords from one IP, that IP is blocked from logging in for 5 minutes. Use the Logout button at the top of the page.

## Deploy on Render (free)
1. Push this folder to a GitHub repo: `git remote add origin <url> && git push -u origin main`.
2. On render.com, choose **New → Blueprint**, pick the repo, and Render reads `render.yaml`. You can also choose New → Web Service with the Docker runtime.
3. When prompted, enter **APP_PASSWORD**. `SECRET_KEY` is generated automatically.
4. Open the `https://<name>.onrender.com` URL on your phone and log in. The free tier sleeps after about 15 minutes idle, so the first load after that takes around 30–60 seconds.
