import os
import sys
import mimetypes
import subprocess
import tempfile
import uuid
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Ensure environment
os.environ["PYTHONUNBUFFERED"] = "1"
EXPORT_DIR = Path("/tmp/clipforge_exports")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = Path("/tmp/hf_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ["HOME"] = "/tmp"
os.environ["HF_HOME"] = str(CACHE_DIR)

HTML_CONTENT = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>ClipForge Web App</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .loading-spinner { border-top-color: #10B981; animation: spinner 1.5s linear infinite; }
        @keyframes spinner { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen">
    <div class="max-w-4xl mx-auto p-6">
        <h1 class="text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-teal-500 mb-2">ClipForge</h1>
        <p class="text-slate-400 mb-8 font-medium">Open Source Video Repurposing Engine</p>
        
        <div class="bg-slate-800 p-6 rounded-2xl shadow-xl border border-slate-700">
            <div class="mb-6">
                <label class="block text-sm font-semibold text-slate-300 mb-2">Source URL (YouTube/TikTok/Direct MP4)</label>
                <input type="text" id="urlInput" placeholder="Paste link here..." class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-emerald-500 transition-colors">
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                <div>
                    <label class="block text-sm font-semibold text-slate-300 mb-2">Hook Banner Text</label>
                    <input type="text" id="hookText" placeholder="e.g. STOP SCROLLING!" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-emerald-500 transition-colors text-black">
                </div>
                <div>
                    <label class="block text-sm font-semibold text-slate-300 mb-2">Max Clip Duration (s)</label>
                    <input type="number" id="maxDuration" value="30" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-emerald-500 transition-colors">
                </div>
            </div>

            <button id="processBtn" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-4 rounded-xl shadow-lg transition-transform active:scale-95 flex items-center justify-center space-x-2">
                <span>Forge Clips</span>
            </button>
        </div>

        <div id="statusArea" class="mt-8 hidden">
            <h2 class="text-xl font-bold mb-4 flex items-center">
                <div class="loading-spinner w-5 h-5 border-2 border-slate-600 rounded-full mr-3"></div>
                <span id="statusText">Starting process...</span>
            </h2>
            <div class="bg-slate-950 rounded-xl p-4 font-mono text-xs text-emerald-400 max-h-48 overflow-y-auto border border-slate-900">
                <div id="consoleOutput">> Initialized pipeline environment.</div>
            </div>
        </div>

        <div id="outputArea" class="mt-8 grid grid-cols-1 gap-6"></div>
    </div>

    <script>
        const btn = document.getElementById('processBtn');
        const statusArea = document.getElementById('statusArea');
        const statusText = document.getElementById('statusText');
        const consoleOutput = document.getElementById('consoleOutput');
        const outputArea = document.getElementById('outputArea');

        btn.addEventListener('click', () => {
            const url = document.getElementById('urlInput').value.trim();
            if (!url) { alert('Please enter a valid URL'); return; }

            statusArea.classList.remove('hidden');
            outputArea.innerHTML = '';
            consoleOutput.innerHTML = '> Starting render function...';
            statusText.innerText = 'Downloading and processing media...';

            fetch(`/render?url=${encodeURIComponent(url)}&hook=${encodeURIComponent(document.getElementById('hookText').value)}&max_len=${document.getElementById('maxDuration').value}`)
                .then(response => response.json())
                .then(data => {
                    statusText.innerText = 'Job Complete!';
                    if (data.status === 'success') {
                        data.clips.forEach((clip, index) => {
                            const card = document.createElement('div');
                            card.className = "bg-slate-800 rounded-2xl overflow-hidden shadow-lg border border-slate-700 animate-fadeIn";
                            card.innerHTML = `
                                <div class="p-4 bg-slate-900 border-b border-slate-700 flex justify-between items-center">
                                    <span class="font-bold text-emerald-400">Clip #${index + 1}</span>
                                    <a href="/download?path=${encodeURIComponent(clip)}" class="bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded-lg text-xs font-semibold">Download MP4</a>
                                </div>
                                <div class="bg-black flex items-center justify-center">
                                    <video src="/download?path=${encodeURIComponent(clip)}" controls class="max-h-96 w-auto"></video>
                                </div>
                            `;
                            outputArea.appendChild(card);
                        });
                    } else {
                        consoleOutput.innerHTML += `<br><span class="text-red-400">> Error: ${data.error}</span>`;
                    }
                })
                .catch(err => {
                    statusText.innerText = 'Render Failed';
                    consoleOutput.innerHTML += `<br><span class="text-red-400">> Network Exception: ${err.message}</span>`;
                });
        });
    </script>
</body>
</html>
"""

def generate_subtitles(audio_path, output_srt):
    cmd = ["whisper", audio_path, "--model", "tiny", "--output_format", "srt", "--output_dir", str(Path(output_srt).parent)]
    subprocess.run(cmd, check=True)
    srt_file = Path(audio_path).with_suffix(".srt")
    if srt_file.exists():
        srt_file.rename(output_srt)

def run_ffmpeg(cmd_list):
    res = subprocess.run(cmd_list, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {res.stderr}")
    return res.stdout

def create_complex_filter(num_clips, font_path, resolution="720x1280"):
    w, h = [int(x) for x in resolution.split('x')]
    pad_h = int(h * 0.15)
    filter_strs = []
    inputs = []
    
    for i in range(num_clips):
        inputs.extend([f"[{i}:v]", f"[{i}:a]"])
        filter_strs.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"drawbox=y=0:w=iw:h={pad_h}:t=fill:c=black@0.6,"
            f"drawtext=fontfile='{font_path}':text='%{{metadata:lavfi.hook_text}}':fontsize=48:fontcolor=white:x=(w-text_w)/2:y=( {pad_h}-text_h)/2,"
            f"drawtext=fontfile='{font_path}':text='%{{metadata:lavfi.sub_text}}':fontsize=32:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=10:x=(w-text_w)/2:y={h}-text_h-100[v{i}];"
        )
    concat_filter = "".join(filter_strs) + "".join([f"[v{i}][{i}:a]" for i in range(num_clips)]) + f"concat=n={num_clips}:v=1:a=1[outv][outa]"
    return inputs, concat_filter

class RequestHandler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode('utf-8'))
        elif path == '/render':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            url = query.get('url', [''])[0]
            hook = query.get('hook', [''])[0]
            max_len = int(query.get('max_len', [30])[0])
            
            job_id = uuid.uuid4().hex[:8]
            work_dir = EXPORT_DIR / job_id
            work_dir.mkdir(parents=True, exist_ok=True)
            
            try:
                raw_video = work_dir / "input.mp4"
                if not url.startswith("http"):
                    raise ValueError("Invalid URL protocol")
                
                subprocess.run(["yt-dlp", "-f", "bestvideo[ext=mp4]+bestaudio[ext=mp4]/best[ext=mp4]", url, "-o", str(raw_video)], check=True)
                
                probe_out = run_ffmpeg(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(raw_video)])
                duration = float(probe_out.strip())
                
                audio_path = work_dir / "audio.mp3"
                run_ffmpeg(["ffmpeg", "-i", str(raw_video), "-vn", "-acodec", "libmp3lame", str(audio_path)])
                
                srt_path = work_dir / "subs.srt"
                generate_subtitles(str(audio_path), str(srt_path))
                
                split_duration = min(max_len, int(duration / 3) + 1)
                num_clips = min(3, int(duration // split_duration) + 1)
                
                metadata_file = work_dir / "metadata.ffmetadata"
                with open(metadata_file, "w", encoding="utf-8") as f:
                    f.write(";FFMETADATA1\n")
                    for i in range(num_clips):
                        start_time = i * split_duration
                        if start_time >= duration: break
                        f.write(f"[STREAM]\nSTART_TIME={start_time}\nTAG:hook_text={hook}\nTAG:sub_text=Generated Highlight #{i+1}\n")
                
                font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                if not os.path.exists(font_path): font_path = ""

                cmd = ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(metadata_file)]
                for i in range(num_clips):
                    cmd.extend(["-i", str(raw_video)])
                cmd.extend(["-filter_complex", "[0:v]metadata=print=summary[outv]", "-map", "[outv]", "-map", "0:a", "-c:v", "libx264", "-c:a", "aac", "-y", str(work_dir / "output.mp4")])
                run_ffmpeg(cmd)

                self.wfile.write(('{"status": "success", "clips": ["' + job_id + '/output.mp4"]}\n').encode('utf-8'))
            except Exception as e:
                self.wfile.write((f'{{"status": "error", "error": "{str(e)}"}}').encode('utf-8'))

        elif path == '/download':
            file_path = EXPORT_DIR / query.get('path', [''])[0].lstrip('/')
            if os.path.exists(file_path):
                ctype, _ = mimetypes.guess_type(file_path)
                self.send_response(200)
                self.send_header('Content-Type', ctype or 'application/octet-stream')
                self.send_header('Content-Length', os.path.getsize(file_path))
                self.end_headers()
                with open(file_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404)
        else:
            self.send_error(404)

if __name__ == '__main__':
    PORT = int(os.environ.get('PORT', 7860))
    server = ThreadingHTTPServer(('0.0.0.0', PORT), RequestHandler)
    server.serve_forever()
