"""FFmpeg / ffprobe helpers."""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

log = logging.getLogger(__name__)


class MediaError(RuntimeError):
    """User-facing media problem (corrupt file, no audio, ...)."""


@dataclass
class ProbeResult:
    duration: float
    width: int
    height: int
    fps: float
    fps_str: str
    has_audio: bool
    video_codec: str
    rotation: int = 0

    @property
    def display_size(self) -> tuple[int, int]:
        if self.rotation in (90, 270, -90, -270):
            return self.height, self.width
        return self.width, self.height


def probe(path: Path) -> ProbeResult:
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            capture_output=True, text=True, timeout=120, check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise MediaError("Analýza souboru trvala příliš dlouho.") from e
    if out.returncode != 0:
        raise MediaError("Soubor nelze přečíst – pravděpodobně nejde o platné video nebo je poškozený.")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None:
        raise MediaError("Soubor neobsahuje videostopu.")
    duration = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    if duration <= 0:
        raise MediaError("Nepodařilo se zjistit délku videa – soubor je nejspíš poškozený.")
    fps_str = v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1"
    try:
        fps = float(Fraction(fps_str)) if fps_str != "0/0" else 30.0
    except (ZeroDivisionError, ValueError):
        fps, fps_str = 30.0, "30/1"
    if fps <= 0 or fps > 240:
        fps, fps_str = 30.0, "30/1"
    rotation = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(sd["rotation"])
    if "rotate" in (v.get("tags") or {}):
        rotation = int(v["tags"]["rotate"])
    return ProbeResult(
        duration=duration,
        width=int(v.get("width") or 0),
        height=int(v.get("height") or 0),
        fps=fps,
        fps_str=fps_str,
        has_audio=a is not None,
        video_codec=str(v.get("codec_name") or ""),
        rotation=rotation,
    )


def run_ffmpeg(
    args: Sequence[str],
    duration: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    timeout: float | None = None,
) -> None:
    """Run ffmpeg with ``-progress`` parsing. Raises MediaError with the stderr tail."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", *args]
    log.debug("ffmpeg %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if on_progress and duration and line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                    on_progress(min(1.0, max(0.0, us / 1e6 / duration)))
                except ValueError:
                    pass
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as e:
        proc.kill()
        raise MediaError("FFmpeg překročil časový limit.") from e
    stderr = proc.stderr.read() if proc.stderr else ""
    if proc.returncode != 0:
        tail = "\n".join(stderr.strip().splitlines()[-8:])
        raise MediaError(f"FFmpeg selhal: {tail}")


def extract_audio(src: Path, dst: Path, start: float = 0.0, end: float | None = None,
                  on_progress: Callable[[float], None] | None = None) -> None:
    """16 kHz mono WAV for Whisper."""
    args = ["-ss", f"{start:.3f}"]
    if end is not None:
        args += ["-to", f"{end:.3f}"]
    args += ["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)]
    run_ffmpeg(args, duration=(end - start) if end else None, on_progress=on_progress)


def thumbnail(src: Path, dst: Path, at: float, width: int = 640) -> None:
    run_ffmpeg([
        "-ss", f"{max(0.0, at):.3f}", "-i", str(src), "-frames:v", "1",
        "-vf", f"scale={width}:-2", "-q:v", "3", str(dst),
    ])


def preview_excerpt(src: Path, dst: Path, start: float, end: float, max_height: int = 540) -> None:
    """Lightweight browser-playable excerpt of the source for the editor."""
    run_ffmpeg([
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src),
        "-vf", f"scale=-2:'min({max_height},ih)'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-pix_fmt", "yuv420p",
        "-g", "15",
        "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-movflags", "+faststart", str(dst),
    ], duration=end - start)


def has_speech_energy(wav: Path) -> bool:
    """Cheap check whether the audio is not pure silence."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(wav), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    for line in out.stderr.splitlines():
        if "max_volume:" in line:
            try:
                return float(line.split("max_volume:")[1].split("dB")[0]) > -50.0
            except ValueError:
                return True
    return True
