"""Final clip rendering with FFmpeg (crop path, captions, emoji, logo, intro/outro)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.pipeline.media import run_ffmpeg
from app.pipeline.reframe import CropPlan
from app.pipeline.timeline import TimeMap

log = logging.getLogger(__name__)

ASPECTS: dict[str, tuple[int, int]] = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}


def aspect_ratio(aspect: str) -> float:
    w, h = ASPECTS.get(aspect, ASPECTS["9:16"])
    return w / h


def output_size(aspect: str, resolution: str, crop_w: int, crop_h: int, split: bool = False) -> tuple[int, int, float]:
    """Return (width, height, upscale factor relative to the source pixels used)."""
    bw, bh = ASPECTS.get(aspect, ASPECTS["9:16"])
    if resolution == "2160":
        w, h = bw * 2, bh * 2
    elif resolution == "source":
        src_h = crop_h * 2 if split else crop_h
        f = min(2.0, src_h / bh)
        w, h = int(round(bw * f / 2) * 2), int(round(bh * f / 2) * 2)
    else:
        w, h = bw, bh
    native_h = crop_h * 2 if split else crop_h
    return w, h, round(h / max(1, native_h), 3)


@dataclass
class Overlay:
    path: Path
    start: float
    end: float
    cx: float
    cy: float


@dataclass
class LogoSpec:
    path: Path
    position: str = "top-right"
    opacity: float = 0.85
    scale: float = 0.18


@dataclass
class RenderSpec:
    src: Path
    src_w: int
    src_h: int
    fps_str: str
    has_audio: bool
    start: float
    end: float
    timemap: TimeMap
    out_w: int
    out_h: int
    plan: CropPlan
    out_path: Path
    work_dir: Path
    ass_path: Path | None = None
    fonts_dir: Path | None = None
    overlays: list[Overlay] = field(default_factory=list)
    logo: LogoSpec | None = None
    preset: str | None = None
    crf: int | None = None


def _esc(path: Path) -> str:
    """Escape a path for use inside an FFmpeg filter argument."""
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def _select_expr(tm: TimeMap, start: float) -> str:
    return "+".join(f"between(t,{a - start:.3f},{b - start:.3f})" for a, b in tm.segments)


def write_sendcmd(spec: RenderSpec, fps: float, path: Path) -> None:
    """Per-output-frame crop positions (source time -> output time via the time map)."""
    plan = spec.plan
    lines: list[str] = []
    step = 1.0 / max(1.0, fps)
    acc = 0.0
    for a, b in spec.timemap.segments:
        t = a
        while t < b - 1e-6:
            out_t = acc + (t - a)
            x, y = plan.at(t)
            cmd = f"{out_t:.4f} crop@c0 x {x:.0f}, crop@c0 y {y:.0f}"
            if plan.layout == "split":
                x2, y2 = plan.at(t, second=True)
                cmd += f", crop@c1 x {x2:.0f}, crop@c1 y {y2:.0f}"
            lines.append(cmd + ";")
            t += step
        acc += b - a
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_command(spec: RenderSpec, fps: float) -> list[str]:
    s = get_settings()
    W, H = spec.out_w, spec.out_h
    plan = spec.plan
    args: list[str] = ["-ss", f"{spec.start:.3f}", "-to", f"{spec.end:.3f}", "-i", str(spec.src)]
    input_idx = 1
    overlay_inputs: list[tuple[int, Overlay]] = []
    for ov in spec.overlays:
        args += ["-i", str(ov.path)]
        overlay_inputs.append((input_idx, ov))
        input_idx += 1
    logo_idx = None
    if spec.logo:
        args += ["-i", str(spec.logo.path)]
        logo_idx = input_idx
        input_idx += 1

    chains: list[str] = []
    v = "[0:v]"
    pre = ""
    if not spec.timemap.trivial:
        pre = f"select='{_select_expr(spec.timemap, spec.start)}',setpts=N/FRAME_RATE/TB,"
    cmd_file = spec.work_dir / "crop.cmd"

    x0, y0 = plan.at(plan.times[0] if plan.times else 0.0)
    if plan.layout in ("track", "full", "center"):
        dyn = plan.layout == "track"
        if dyn:
            write_sendcmd(spec, fps, cmd_file)
        send = f"sendcmd=f='{_esc(cmd_file)}'," if dyn else ""
        chains.append(
            f"{v}{pre}{send}crop@c0=w={plan.crop_w}:h={plan.crop_h}:x={x0:.0f}:y={y0:.0f},"
            f"scale={W}:{H}:flags=lanczos,setsar=1[base]"
        )
    elif plan.layout == "split":
        write_sendcmd(spec, fps, cmd_file)
        x1, y1 = plan.at(plan.times[0], second=True)
        hh = H // 2
        chains.append(f"{v}{pre}sendcmd=f='{_esc(cmd_file)}',split=2[sa][sb]")
        chains.append(f"[sa]crop@c0=w={plan.crop_w}:h={plan.crop_h}:x={x0:.0f}:y={y0:.0f},scale={W}:{hh}:flags=lanczos,setsar=1[top]")
        chains.append(f"[sb]crop@c1=w={plan.crop_w}:h={plan.crop_h}:x={x1:.0f}:y={y1:.0f},scale={W}:{H - hh}:flags=lanczos,setsar=1[bot]")
        chains.append("[top][bot]vstack=inputs=2[base]")
    else:  # blur: fit the whole frame over a blurred, zoomed background
        chains.append(f"{v}{pre}split=2[ba][bb]")
        chains.append(
            f"[ba]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
            f"boxblur=12:2,scale={W}:{H},setsar=1[bg]"
        )
        chains.append(f"[bb]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,setsar=1[fg]")
        chains.append("[bg][fg]overlay=(W-w)/2:(H-h)/2[base]")

    cur = "[base]"
    if spec.ass_path:
        fd = f":fontsdir='{_esc(spec.fonts_dir)}'" if spec.fonts_dir else ""
        chains.append(f"{cur}ass=filename='{_esc(spec.ass_path)}'{fd}[subs]")
        cur = "[subs]"
    for n, (idx, ov) in enumerate(overlay_inputs):
        lbl = f"[em{n}]"
        chains.append(
            f"{cur}[{idx}:v]overlay=x={ov.cx:.0f}-w/2:y={ov.cy:.0f}-h/2:"
            f"enable='between(t,{ov.start:.3f},{ov.end:.3f})'{lbl}"
        )
        cur = lbl
    if spec.logo and logo_idx is not None:
        lw = max(16, int(W * spec.logo.scale))
        margin = int(min(W, H) * 0.04)
        pos = {
            "top-left": (f"{margin}", f"{margin}"),
            "top-right": (f"W-w-{margin}", f"{margin}"),
            "bottom-left": (f"{margin}", f"H-h-{margin}"),
            "bottom-right": (f"W-w-{margin}", f"H-h-{margin}"),
            "center": ("(W-w)/2", "(H-h)/2"),
        }.get(spec.logo.position, (f"W-w-{margin}", f"{margin}"))
        chains.append(
            f"[{logo_idx}:v]format=rgba,scale={lw}:-1,colorchannelmixer=aa={spec.logo.opacity:.2f}[logo]"
        )
        chains.append(f"{cur}[logo]overlay=x={pos[0]}:y={pos[1]}[lg]")
        cur = "[lg]"
    chains.append(f"{cur}format=yuv420p[vout]")

    if spec.has_audio:
        if spec.timemap.trivial:
            chains.append("[0:a]aresample=48000[aout]")
        else:
            chains.append(f"[0:a]aselect='{_select_expr(spec.timemap, spec.start)}',asetpts=N/SR/TB,aresample=48000[aout]")

    args += ["-filter_complex", ";".join(chains), "-map", "[vout]"]
    if spec.has_audio:
        args += ["-map", "[aout]"]
    args += [
        "-c:v", "libx264", "-profile:v", "high", "-preset", spec.preset or s.x264_preset,
        "-crf", str(spec.crf if spec.crf is not None else s.x264_crf), "-pix_fmt", "yuv420p",
        "-r", spec.fps_str, "-movflags", "+faststart",
    ]
    if s.render_threads:
        args += ["-threads", str(s.render_threads)]
    if spec.has_audio:
        args += ["-c:a", "aac", "-b:a", s.audio_bitrate, "-ar", "48000"]
    args += ["-t", f"{spec.timemap.duration:.3f}", str(spec.out_path)]
    return args


def render(spec: RenderSpec, fps: float, on_progress: Callable[[float], None] | None = None) -> None:
    spec.work_dir.mkdir(parents=True, exist_ok=True)
    args = build_command(spec, fps)
    run_ffmpeg(args, duration=spec.timemap.duration, on_progress=on_progress)


def concat_intro_outro(main: Path, intro: Path | None, outro: Path | None, out: Path, W: int, H: int,
                       fps_str: str, has_audio: bool) -> None:
    """Prepend/append brand intro/outro clips (scaled + padded to the clip format)."""
    from app.pipeline.media import probe

    s = get_settings()
    parts = [p for p in (intro, main, outro) if p is not None]
    args: list[str] = []
    for p in parts:
        args += ["-i", str(p)]
    chains = []
    concat_in = ""
    extra = len(parts)
    for i, p in enumerate(parts):
        chains.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={fps_str},setsar=1,format=yuv420p[v{i}]"
        )
        pr = probe(p)
        if pr.has_audio:
            chains.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
        else:
            args += ["-f", "lavfi", "-t", f"{pr.duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            chains.append(f"[{extra}:a]anull[a{i}]")
            extra += 1
        concat_in += f"[v{i}][a{i}]"
    chains.append(f"{concat_in}concat=n={len(parts)}:v=1:a=1[vout][aout]")
    args += [
        "-filter_complex", ";".join(chains), "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-profile:v", "high", "-preset", s.x264_preset, "-crf", str(s.x264_crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "aac", "-b:a", s.audio_bitrate, str(out),
    ]
    run_ffmpeg(args)
    _ = has_audio


def link_fonts(dst: Path, font_files: list[Path]) -> Path:
    """Create a fonts dir containing (symlinks to) the given font files for libass."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in font_files:
        target = dst / f.name
        if not target.exists():
            try:
                os.symlink(f.resolve(), target)
            except OSError:
                import shutil

                shutil.copy(f, target)
    return dst


def describe(spec: RenderSpec) -> dict[str, Any]:
    return {"layout": spec.plan.layout, "width": spec.out_w, "height": spec.out_h,
            "duration": round(spec.timemap.duration, 3)}
