from __future__ import annotations

import itertools
import json
import subprocess
from pathlib import Path

import pytest

from app.pipeline import captions, reframe, render
from app.pipeline.presets import resolve_style
from app.pipeline.reframe import CropPlan, crop_size, plan_crop
from app.pipeline.render import RenderSpec, build_command, output_size
from app.pipeline.timeline import TimeMap, build_timemap, map_words
from tests.conftest import make_words

SHARED = Path(__file__).resolve().parents[2] / "shared"


def _spec(tmp: Path, plan: CropPlan, tm: TimeMap | None = None) -> RenderSpec:
    return RenderSpec(src=tmp / "in.mp4", src_w=1920, src_h=1080, fps_str="30000/1001", has_audio=True, start=10.0,
                      end=40.0, timemap=tm or TimeMap([(10.0, 40.0)]), out_w=1080, out_h=1920, plan=plan,
                      out_path=tmp / "out.mp4", work_dir=tmp, ass_path=tmp / "c.ass", fonts_dir=SHARED / "fonts")


def test_ffmpeg_command_quality_settings(tmp_dir: Path) -> None:
    plan = CropPlan("track", 608, 1080, [10.0, 40.0], [600.0, 700.0], [0.0, 0.0])
    args = build_command(_spec(tmp_dir, plan), 29.97)
    joined = " ".join(args)
    for needle in ("-c:v libx264", "-profile:v high", "-crf 18", "-pix_fmt yuv420p", "-movflags +faststart",
                   "-c:a aac", "-b:a 192k", "-r 30000/1001", "sendcmd", "crop@c0", "scale=1080:1920", "ass=filename="):
        assert needle in joined, needle
    cmd = (tmp_dir / "crop.cmd").read_text()
    assert cmd.startswith("0.0000 crop@c0 x 600")
    assert len(cmd.splitlines()) == pytest.approx(30 * 29.97, abs=2)


def test_ffmpeg_command_with_cuts_and_split(tmp_dir: Path) -> None:
    plan = CropPlan("split", 1080, 960, [10.0, 40.0], [0.0, 0.0], [0.0, 0.0], [800.0, 800.0], [0.0, 0.0])
    tm = TimeMap([(10.0, 20.0), (25.0, 40.0)])
    joined = " ".join(build_command(_spec(tmp_dir, plan, tm), 30))
    assert "select='between(t,0.000,10.000)+between(t,15.000,30.000)'" in joined
    assert "aselect=" in joined and "vstack" in joined and "crop@c1" in joined
    assert "-t 25.000" in joined


def test_output_size_and_upscale() -> None:
    assert output_size("9:16", "1080", 608, 1080) == (1080, 1920, round(1920 / 1080, 3))
    w, h, up = output_size("9:16", "source", 1216, 2160)
    assert (w, h) == (1216, 2160) and up == 1.0
    assert output_size("16:9", "1080", 1920, 1080)[:2] == (1920, 1080)
    assert output_size("1:1", "2160", 2160, 2160) == (2160, 2160, 1.0)


def test_crop_size() -> None:
    assert crop_size(1920, 1080, 9 / 16) == (608, 1080)
    assert crop_size(1920, 1080, 1.0) == (1080, 1080)
    assert crop_size(1080, 1920, 16 / 9) == (1080, 608)


def _analysis(faces_fn) -> dict:  # type: ignore[no-untyped-def]
    frames = [{"t": i / 5, "cut": False, "faces": faces_fn(i)} for i in range(100)]
    return {"start": 0, "end": 20, "fps": 5, "src_w": 1920, "src_h": 1080, "frames": frames}


def test_plan_follows_face_smoothly() -> None:
    # face moves slowly from left to right; jitter must be smoothed
    import random

    random.seed(1)
    an = _analysis(lambda i: [{"cx": 0.2 + 0.6 * i / 100 + random.uniform(-0.005, 0.005), "cy": 0.4, "w": 0.1,
                               "h": 0.18, "mouth": 0.05}])
    plan = plan_crop(an, 1080, 1920)
    assert plan.layout == "track"
    xs = plan.xs
    centers = [x + plan.crop_w / 2 for x in xs]
    assert centers[10] < centers[-10]
    steps = [abs(b - a) for a, b in itertools.pairwise(xs)]
    assert max(steps) < 60  # no jumps between 0.2 s samples
    # the face stays inside the crop
    for i, c in enumerate(centers):
        face_x = (0.2 + 0.6 * i / 100) * 1920
        assert abs(face_x - c) < plan.crop_w / 2


def test_plan_active_speaker_by_mouth() -> None:
    def faces(i: int) -> list[dict]:
        talking_left = i < 50
        lm = 0.02 + (0.06 if (talking_left and i % 2) else 0)
        rm = 0.02 + (0.06 if (not talking_left and i % 2) else 0)
        return [{"cx": 0.25, "cy": 0.45, "w": 0.1, "h": 0.2, "mouth": lm},
                {"cx": 0.75, "cy": 0.45, "w": 0.1, "h": 0.2, "mouth": rm}]

    plan = plan_crop(_analysis(faces), 1080, 1920)
    assert plan.speakers == 2
    c_early = plan.xs[20] + plan.crop_w / 2
    c_late = plan.xs[90] + plan.crop_w / 2
    assert c_early < 960 < c_late
    # speaker change is a hard cut: at most one sample lies between the two framings
    between = [x for x in plan.xs if plan.xs[20] + 50 < x < plan.xs[90] - 50]
    assert len(between) <= 1
    split = plan_crop(_analysis(faces), 1080, 1920, "split")
    assert split.layout == "split" and split.xs2 is not None


def test_plan_no_faces_falls_back_to_blur() -> None:
    plan = plan_crop(_analysis(lambda i: []), 1080, 1920)
    assert plan.layout == "blur"
    assert plan_crop(_analysis(lambda i: []), 1920, 1080).layout == "full"


@pytest.mark.slow
def test_real_render_no_face_blur(tmp_dir: Path) -> None:
    """Render a synthetic clip end-to-end and verify it with ffprobe."""
    src = tmp_dir / "in.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=44100", "-t", "6", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    an = reframe.analyze(src, 0, 6, 1280, 720)
    words = make_words("Žluťoučký kůň úpěl ďábelské ódy. Peníze!", start=0.5)
    tm, kept = build_timemap(words, 0.0, 5.0)
    style = resolve_style("box")
    plan = plan_crop(an, 1080, 1920)
    ass = tmp_dir / "c.ass"
    ass.write_text(captions.build_ass(map_words(kept, tm), style, 1080, 1920), encoding="utf-8")
    spec = RenderSpec(src=src, src_w=1280, src_h=720, fps_str="25/1", has_audio=True, start=0.0, end=5.0, timemap=tm,
                      out_w=1080, out_h=1920, plan=plan, out_path=tmp_dir / "out.mp4", work_dir=tmp_dir,
                      ass_path=ass, fonts_dir=SHARED / "fonts", preset="veryfast")
    render.render(spec, 25.0)
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                                      str(spec.out_path)], capture_output=True, text=True, check=True).stdout)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (v["width"], v["height"]) == (1080, 1920)
    assert v["codec_name"] == "h264" and v["profile"] == "High" and v["pix_fmt"] == "yuv420p"
    assert v["r_frame_rate"] == "25/1"
    assert a["codec_name"] == "aac"
    assert abs(float(info["format"]["duration"]) - 5.0) < 0.15
