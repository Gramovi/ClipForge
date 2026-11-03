#!/usr/bin/env python3
"""Generate realistic test videos for ClipForge (speech + faces with moving mouths).

Creates a two-person "podcast" from a script (lines prefixed with ``A:`` / ``B:``) using Piper
TTS, and renders a 1920x1080 video with two faces whose mouths open according to who is
speaking. The camera alternates between a wide two-shot and close-ups (to test scene cuts and
active-speaker tracking).

Requirements (separate venv is fine):
    pip install piper-tts scikit-image opencv-python-headless numpy
    Piper voices (.onnx + .onnx.json) from https://huggingface.co/rhasspy/piper-voices

Usage:
    python make_test_media.py podcast --script test_scripts/cs.txt --script test_scripts/cs2.txt --voice-a cs_CZ-jirka-medium.onnx \
        --voice-b cs_CZ-jirka-medium.onnx --pitch-b 0.9 --out ../test-media/podcast-cs.mp4
    python make_test_media.py extras --voice cs_CZ-jirka-medium.onnx --out-dir ../test-media
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import cv2
import numpy as np

W, H, FPS, SR = 1920, 1080, 25, 22050


def tts(text: str, voice: Path, out: Path, length_scale: float, pitch: float = 1.0) -> np.ndarray:
    raw = out.with_suffix(".raw.wav")
    subprocess.run(
        [sys.executable, "-m", "piper", "-m", str(voice), "-f", str(raw), "--length-scale", str(length_scale),
         "--sentence-silence", "0.35"],
        input=text.encode("utf-8"), check=True, capture_output=True,
    )
    flt = f"aresample={SR}"
    if pitch != 1.0:  # lower/raise the voice so the two speakers sound different
        flt = f"asetrate={int(SR * pitch)},aresample={SR},atempo={1 / pitch:.4f}"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", flt, "-ac", "1", "-ar", str(SR), str(out)], check=True)
    with wave.open(str(out)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def face_assets() -> tuple[np.ndarray, tuple[int, int, int]]:
    """Astronaut portrait (public domain, NASA) + mouth position (found with MediaPipe landmarks 13/14/61/291)."""
    from skimage import data

    img = cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)
    return img, (223, 143, 30)


def mouth_variants(img: np.ndarray, mouth: tuple[int, int, int], levels: int = 6) -> list[np.ndarray]:
    out = []
    mx, my, mw = mouth
    for lv in range(levels):
        f = img.copy()
        h = int(lv / (levels - 1) * mw * 0.55)
        if h > 0:
            cv2.ellipse(f, (mx, my + 4), (int(mw * 0.55), h // 2 + 1), 0, 0, 360, (30, 20, 60), -1, cv2.LINE_AA)
            cv2.ellipse(f, (mx, my + 4 + h // 4), (int(mw * 0.35), max(1, h // 5)), 0, 0, 360, (90, 80, 200), -1, cv2.LINE_AA)
        out.append(f)
    return out


def background() -> np.ndarray:
    y, x = np.mgrid[0:H, 0:W]
    bg = np.zeros((H, W, 3), np.uint8)
    bg[..., 0] = (40 + 30 * x / W).astype(np.uint8)
    bg[..., 1] = (28 + 20 * y / H).astype(np.uint8)
    bg[..., 2] = (30 + 25 * (1 - x / W)).astype(np.uint8)
    cv2.rectangle(bg, (0, int(H * 0.82)), (W, H), (25, 22, 30), -1)  # desk
    return bg


def podcast(args: argparse.Namespace) -> None:
    lines = [ln.strip() for sc in args.script for ln in Path(sc).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if args.max_lines:
        lines = lines[: args.max_lines]
    tmp = Path(tempfile.mkdtemp(prefix="cf-media-"))
    audio: list[np.ndarray] = []
    speaker_at: list[tuple[int, int, str]] = []  # (start sample, end sample, speaker)
    pos = 0
    gap = np.zeros(int(SR * 0.55), np.float32)
    for i, ln in enumerate(lines):
        spk, text = ln.split(":", 1)
        voice = Path(args.voice_a if spk == "A" else args.voice_b)
        pitch = args.pitch_a if spk == "A" else args.pitch_b
        a = tts(text.strip(), voice, tmp / f"l{i}.wav", args.length_scale, pitch)
        speaker_at.append((pos, pos + len(a), spk))
        audio += [a, gap]
        pos += len(a) + len(gap)
        print(f"\rTTS {i + 1}/{len(lines)}", end="", flush=True)
    print()
    full = np.concatenate(audio)
    wav = tmp / "full.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(full, -1, 1) * 32767).astype(np.int16).tobytes())
    duration = len(full) / SR
    n_frames = int(duration * FPS)
    print(f"audio {duration / 60:.1f} min, {n_frames} frames")

    # per-frame envelope and speaker
    spf = SR // FPS
    env = np.array([np.sqrt(np.mean(full[i * spf:(i + 1) * spf] ** 2)) for i in range(n_frames)])
    env = np.clip(env / (np.percentile(env[env > 0], 95) + 1e-6), 0, 1)
    spk_frame = np.full(n_frames, "", dtype=object)
    for s, e, spk in speaker_at:
        spk_frame[s // spf:min(n_frames, e // spf + 1)] = spk

    img, mouth = face_assets()
    face_a = mouth_variants(img, mouth)
    # speaker B: mirrored + warmer colour grade so the two faces differ
    img_b = cv2.flip(img, 1)
    img_b = cv2.convertScaleAbs(img_b, alpha=1.05, beta=6)
    mouth_b = (img.shape[1] - mouth[0], mouth[1], mouth[2])
    face_b = mouth_variants(img_b, mouth_b)
    size = 560
    fa = [cv2.resize(f, (size, size), interpolation=cv2.INTER_AREA) for f in face_a]
    fb = [cv2.resize(f, (size, size), interpolation=cv2.INTER_AREA) for f in face_b]
    bg = background()
    pos_a, pos_b = (250, 300), (W - 250 - size, 300)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "pipe:0", "-i", str(wav), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE,
    )
    assert enc.stdin is not None
    shot_len = FPS * 40
    for f in range(n_frames):
        spk = spk_frame[f]
        lv = int(round(env[f] * 5)) if spk else 0
        la = lv if spk == "A" else 0
        lb = lv if spk == "B" else 0
        frame = bg.copy()
        frame[pos_a[1]:pos_a[1] + size, pos_a[0]:pos_a[0] + size] = fa[la]
        frame[pos_b[1]:pos_b[1] + size, pos_b[0]:pos_b[0] + size] = fb[lb]
        shot = (f // shot_len) % 4
        if shot == 3:  # close-up of the left person (camera cut)
            crop = frame[200:200 + 660, 120:120 + 1173]
            frame = cv2.resize(crop, (W, H), interpolation=cv2.INTER_LINEAR)
        elif shot == 1 and args.closeups:  # close-up of the right person
            crop = frame[200:200 + 660, W - 120 - 1173:W - 120]
            frame = cv2.resize(crop, (W, H), interpolation=cv2.INTER_LINEAR)
        enc.stdin.write(frame.tobytes())
        if f % 500 == 0:
            print(f"\rvideo {f}/{n_frames}", end="", flush=True)
    enc.stdin.close()
    enc.wait()
    print(f"\nwritten {out}")


def extras(args: argparse.Namespace) -> None:
    """Edge-case files: no face, no speech, corrupt file."""
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    text = ("Tohle video nemá žádný obličej, jen barevné pruhy. Přesto by z něj měly vzniknout klipy s titulky. "
            "Peníze, čas a zdraví jsou tři věci, které si musíš hlídat. Když ztratíš zdraví, peníze ti nepomůžou. "
            "Když ztratíš čas, už ho nikdy nevrátíš. A proto si každý den vyhraď hodinu jen pro sebe. "
            "Žádný telefon, žádné zprávy, jen ty a tvoje myšlenky. Uvidíš, jak se ti změní život.")
    a = tts(text, Path(args.voice), tmp / "nf.wav", 1.1)
    dur = len(a) / SR + 0.5
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={dur:.2f}",
                    "-i", str(tmp / "nf.wav"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(out / "no-face-cs.mp4")], check=True)
    img, mouth = face_assets()
    still = background()
    still[300:300 + 512, 700:700 + 512] = img
    cv2.imwrite(str(tmp / "still.png"), still)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(tmp / "still.png"), "-f", "lavfi", "-i",
                    "anullsrc=r=44100:cl=stereo", "-t", "20", "-r", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(out / "no-speech.mp4")], check=True)
    rng = np.random.default_rng(1)
    (out / "corrupt.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + rng.bytes(200_000))
    print("written extras to", out)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("podcast")
    p.add_argument("--script", required=True, action="append", help="may be given several times (concatenated)")
    p.add_argument("--voice-a", required=True)
    p.add_argument("--voice-b", required=True)
    p.add_argument("--pitch-a", type=float, default=1.0)
    p.add_argument("--pitch-b", type=float, default=1.0)
    p.add_argument("--length-scale", type=float, default=1.15)
    p.add_argument("--max-lines", type=int, default=0)
    p.add_argument("--closeups", action="store_true")
    p.add_argument("--out", required=True)
    e = sub.add_parser("extras")
    e.add_argument("--voice", required=True)
    e.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    podcast(args) if args.cmd == "podcast" else extras(args)


if __name__ == "__main__":
    main()
