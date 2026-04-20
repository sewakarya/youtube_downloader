# youtube_downloader

Local YouTube downloader with:

- A **web page** (URL + output path + resolution dropdown)
- A **CLI** (optional)

## Install

From this repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
pip install -r requirements.txt
pip install -e .
```

Also install **ffmpeg** (required for merging video+audio and converting to MP4):

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

## Run

### Web (recommended)

Start the server:

```bash
youtube-downloader-web
```

Open:

- `http://127.0.0.1:8000`

### Workflow

1. Paste the YouTube URL
2. Leave **Target path** as `Vid` (or change it to any folder you want)
3. Click **Download** — the video saves as MP4 in the target folder
4. Once done, a green **⬇ Save to my computer** button appears — click it to download the file to your browser

### Fields explained

| Field | What it does | When to change it |
|---|---|---|
| **YouTube URL** | The video you want to download | Every time |
| **Target path** | Folder where the file is saved on the server machine | If you want a different folder |
| **Resolution** | Quality of the download | Pick a lower resolution (e.g. 480p) for smaller files. Leave as "Best available" for highest quality. Click **Load resolutions** first to see what's available. |
| **Network / Proxy** | How yt-dlp connects to YouTube | Leave as **Auto** for normal use. See troubleshooting below. |
| **Custom proxy URL** | Your proxy server address | Only needed if you selected "Custom" proxy mode |
| **Self-test** | Downloads a test video end-to-end to verify everything works | When something seems broken |
| **Check status** | Manually refreshes the current job status | The app auto-refreshes, so rarely needed |

### CLI

With the venv activated:

```bash
youtube-downloader
```

Or pass the URL directly:

```bash
youtube-downloader "https://www.youtube.com/watch?v=VIDEO_ID"
```

Or without installing (still requires `yt-dlp` in your venv):

```bash
python3 -m youtube_downloader
```

It will prompt:

- `Paste YouTube link:`

and download the video into `Vid/` (created automatically).

---

## Sharing via ngrok

You can expose the web UI to a friend over the internet using [ngrok](https://ngrok.com).

### Setup (one time)

1. Install ngrok:
   ```bash
   brew install ngrok/ngrok/ngrok
   ```
2. Sign up free at [ngrok.com](https://ngrok.com)
3. Go to **dashboard.ngrok.com/get-started/your-authtoken** and copy your authtoken
4. Save it:
   ```bash
   ngrok config add-authtoken YOUR_TOKEN_HERE
   ```

### Start the tunnel

Make sure the server is running first, then in a second terminal:

```bash
ngrok http 8000
```

ngrok will show a public URL like `https://abc123.ngrok-free.app`. Send that to your friend.

> **Note:** The first time your friend visits the URL, ngrok shows a warning page — they just need to click **Visit Site** to proceed.

### Important limitations (free tier)

- **1 GB/month bandwidth** — video files are large (a 1080p video can be 500MB–1.5GB), so the limit can be hit quickly if your friend uses "Save to my computer" a lot
- **URL changes on every restart** — you'll need to resend the link each time you restart ngrok
- Downloads always save to **your machine's** `Vid/` folder, not your friend's. The "Save to my computer" button lets them pull the file to their browser after it's downloaded.

---

## Troubleshooting

### "CONNECT tunnel failed: 403"
Your network or ISP is blocking yt-dlp's default connection method. Fix:
- Set **Network / Proxy** to **Direct (no proxy)** and try again.

### "ffmpeg not found" / video downloads as WebM instead of MP4
ffmpeg is not installed. Install it:
```bash
brew install ffmpeg   # macOS
sudo apt install ffmpeg  # Ubuntu/Debian
```

### Download stuck on "queued" / status never updates
Large videos take time. The app polls every 2 seconds for up to 60 minutes. If it genuinely seems stuck, click **Check status** to manually refresh.

### Video already exists — yt-dlp skips it
yt-dlp won't re-download a file that already exists in the target folder. Delete the existing file or change the target path.

### Friend can't open the ngrok URL
- Make sure both the server (`youtube-downloader-web`) and ngrok (`ngrok http 8000`) are still running on your machine
- The ngrok URL changes every restart — check you sent the latest one
- Free ngrok accounts show a warning page on first visit — click **Visit Site** to proceed
