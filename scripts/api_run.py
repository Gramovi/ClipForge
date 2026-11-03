#!/usr/bin/env python3
"""Drive a full ClipForge run through the HTTP API (register/login, chunked upload, process, wait).

    python scripts/api_run.py VIDEO --settings '{"language":"cs"}' [--base http://localhost:3000]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--base", default="http://localhost:3000")
    ap.add_argument("--email", default="api-runner@example.cz")
    ap.add_argument("--settings", default="{}")
    ap.add_argument("--name", default=None)
    a = ap.parse_args()
    s = requests.Session()
    cred = {"email": a.email, "password": "api-runner-pass"}
    if s.post(f"{a.base}/api/auth/login", json=cred).status_code != 200:
        s.post(f"{a.base}/api/auth/register", json=cred).raise_for_status()
    size = os.path.getsize(a.video)
    up = s.post(f"{a.base}/api/uploads", json={"filename": os.path.basename(a.video), "size": size})
    up.raise_for_status()
    info = up.json()
    with open(a.video, "rb") as f:
        off = 0
        while off < size:
            f.seek(off)
            r = s.put(f"{a.base}/api/uploads/{info['id']}?offset={off}", data=f.read(info["chunk_size"]))
            r.raise_for_status()
            off = r.json()["received"]
    p = s.post(f"{a.base}/api/projects", json={"upload_id": info["id"], "name": a.name, "settings": json.loads(a.settings)})
    p.raise_for_status()
    pid = p.json()["id"]
    print("project", pid, flush=True)
    t0, last = time.time(), None
    while True:
        d = s.get(f"{a.base}/api/projects/{pid}").json()
        cur = (d["status"], d["step"])
        if cur != last:
            print(f"[{time.time() - t0:6.0f}s] {d['status']} {d['step']} {d['progress']:.0f}% {d.get('message') or ''}", flush=True)
            last = cur
        if d["status"] in ("done", "failed"):
            break
        time.sleep(5)
    print(json.dumps({k: d[k] for k in ("status", "error", "message", "language", "duration", "llm_usage")}, ensure_ascii=False))
    for c in d.get("clips", []):
        print(f"{c['virality_score']:5.1f} {c['start']:7.1f}-{c['end']:7.1f} ({c['duration']:5.1f}s) {c['render_status']:8} "
              f"{c['render_info'].get('layout')} | {c['title']} | {' '.join(c['hashtags'])}")
    sys.exit(0 if d["status"] == "done" else 1)


if __name__ == "__main__":
    main()
