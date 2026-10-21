#!/usr/bin/env python3
"""Qwen3-ASR 本地识别服务器
用法: ./.asr-venv/bin/python asr_server.py [端口]
接口: POST /transcribe  (body = 音频文件原始字节, mp3/wav 均可)
返回: {"language": "...", "text": "...", "segments": n}
"""
import io
import os
import sys
# 模型缓存指向本文件夹的 .hf-cache（不依赖 ~/.cache 权限），必须在导入 qwen_asr 前设置
os.environ.setdefault(
    "HF_HOME",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".hf-cache"),
)
import json
import time
import numpy as np
import soundfile as sf
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import torch
from qwen_asr import Qwen3ASRModel

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8399
SR = 16000

print("loading model (MPS)...", flush=True)
model = Qwen3ASRModel.from_pretrained(
    "Qwen/Qwen3-ASR-1.7B",
    dtype=torch.bfloat16 if torch.backends.mps.is_available() else torch.float32,
    device_map="mps" if torch.backends.mps.is_available() else "cpu",
    max_inference_batch_size=8,
    max_new_tokens=1024,
)
print("model ready", flush=True)


def split_on_silence(x: np.ndarray):
    """与前端同款静音切分：50ms 帧 RMS，自适应阈值，≥0.35s 停顿为切点，段目标 18s 上限 28s"""
    hop = int(SR * 0.05)
    frames = len(x) // hop
    if frames == 0:
        return [(0, len(x))]
    rms = np.sqrt(np.mean(np.square(x[: frames * hop].reshape(frames, hop)), axis=1))
    noise = float(np.sort(rms)[int(len(rms) * 0.2)]) or 0.005
    thr = max(0.006, noise * 4)
    quiet = rms < thr
    cuts, f = [], 0
    while f < frames:
        if quiet[f]:
            g = f
            while g < frames and quiet[g]:
                g += 1
            if (g - f) * hop >= SR * 0.35:
                cuts.append(int((f + g) / 2 * hop))
            f = g
        else:
            f += 1
    target, max_seg = SR * 18, SR * 28
    segs, start = [], 0
    for c in cuts:
        if c <= start:
            continue
        if c - start > max_seg:
            while c - start > max_seg:
                segs.append((start, start + max_seg))
                start += max_seg
        if c - start >= target:
            segs.append((start, c))
            start = c
    while len(x) - start > max_seg:
        segs.append((start, start + max_seg))
        start += max_seg
    if len(x) - start > SR * 0.5:
        segs.append((start, len(x)))
    return segs or [(0, len(x))]


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            body = b'{"ok":true}'
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self._cors()
            self.end_headers()

    def do_POST(self):
        if self.path != "/transcribe":
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = self.rfile.read(length)
            x, sr = sf.read(io.BytesIO(data), dtype="float32")
            if x.ndim > 1:
                x = x.mean(axis=1)
            if sr != SR:
                # 简单线性重采样到 16k
                n_out = int(len(x) * SR / sr)
                x = np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x).astype(np.float32)
                sr = SR
            segs = split_on_silence(x)
            audios = [(x[s:e], SR) for s, e in segs]
            t0 = time.time()
            results = model.transcribe(
                audio=audios,
                language="English",
                return_time_stamps=False,
            )
            dt = time.time() - t0
            text = " ".join(r.text.strip() for r in results if r.text.strip())
            body = json.dumps(
                {"language": results[0].language if results else "", "text": text,
                 "segments": len(segs), "seconds": round(dt, 1)},
                ensure_ascii=False,
            ).encode()
            print(f"[transcribe] {len(segs)} segs, {dt:.1f}s, {len(text)} chars", flush=True)
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            print("[error]", e, flush=True)
            body = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Qwen3-ASR server listening on http://127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()
