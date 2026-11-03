"""AI reframing: face analysis, active-speaker selection and a smooth virtual camera path."""

from __future__ import annotations

import logging
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.config import get_settings

log = logging.getLogger(__name__)

FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
YUNET_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/"
    "face_detection_yunet_2023mar.onnx"
)
ANALYSIS_WIDTH = 960
MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


def _model(env: str, name: str, url: str) -> Path:
    import os

    p = Path(os.environ[env]) if os.environ.get(env) else MODELS_DIR / name
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        log.info("Downloading %s to %s", name, p)
        try:
            urllib.request.urlretrieve(url, p)  # noqa: S310 - fixed https URL
        except OSError as e:
            log.warning("Model download failed (%s)", e)
    return p


def face_model_path() -> Path:
    return _model("FACE_MODEL_PATH", "face_landmarker.task", FACE_MODEL_URL)


def yunet_model_path() -> Path:
    return _model("YUNET_MODEL_PATH", "face_detection_yunet_2023mar.onnx", YUNET_URL)


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------

class _Detector:
    """Face detection with OpenCV YuNet (robust for small faces in wide shots, Haar cascade as
    a last resort) + MediaPipe FaceLandmarker on each face crop to measure mouth openness
    (used for active-speaker detection)."""

    def __init__(self) -> None:
        import cv2

        self.kind = "haar"
        self._yunet: Any = None
        self._lm: Any = None
        self._size: tuple[int, int] | None = None
        yp = yunet_model_path()
        if yp.exists():
            try:
                self._yunet = cv2.FaceDetectorYN.create(str(yp), "", (320, 320), 0.6, 0.3, 50)
                self.kind = "yunet"
            except cv2.error as e:  # pragma: no cover
                log.warning("YuNet unavailable: %s", e)
        if self._yunet is None:
            self._haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")  # type: ignore[attr-defined]
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision

            model = face_model_path()
            if model.exists():
                opts = vision.FaceLandmarkerOptions(
                    base_options=mp_python.BaseOptions(model_asset_path=str(model)),
                    running_mode=vision.RunningMode.IMAGE,
                    num_faces=1,
                    min_face_detection_confidence=0.3,
                    min_face_presence_confidence=0.3,
                )
                self._lm = vision.FaceLandmarker.create_from_options(opts)
                self._mp = mp
                self.kind += "+mediapipe"
        except Exception as e:  # pragma: no cover - depends on platform wheels
            log.warning("MediaPipe unavailable (%s); active speaker falls back to face size", e)

    def _mouth(self, rgb: np.ndarray, x: float, y: float, w: float, h: float) -> float:
        """Mouth openness (inner lip distance / face height) on an upscaled face crop; -1 if unknown."""
        if self._lm is None:
            return -1.0
        import cv2

        H, W = rgb.shape[:2]
        m = 0.45
        x0, y0 = int(max(0, x - w * m)), int(max(0, y - h * m))
        x1, y1 = int(min(W, x + w * (1 + m))), int(min(H, y + h * (1 + m)))
        crop = rgb[y0:y1, x0:x1]
        if crop.size == 0:
            return -1.0
        side = 256
        scale = side / max(crop.shape[:2])
        crop = cv2.resize(crop, (max(1, int(crop.shape[1] * scale)), max(1, int(crop.shape[0] * scale))))
        img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(crop))
        res = self._lm.detect(img)
        if not res.face_landmarks:
            return -1.0
        lms = res.face_landmarks[0]
        face_h = max(1e-4, abs(lms[152].y - lms[10].y))
        return round(float(abs(lms[14].y - lms[13].y) / face_h), 4)

    def detect(self, rgb: np.ndarray, ts_ms: int) -> list[dict[str, float]]:
        import cv2

        h, w = rgb.shape[:2]
        boxes: list[tuple[float, float, float, float]] = []
        if self._yunet is not None:
            if self._size != (w, h):
                self._yunet.setInputSize((w, h))
                self._size = (w, h)
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            _, found = self._yunet.detect(bgr)
            for row in found if found is not None else []:
                boxes.append((float(row[0]), float(row[1]), float(row[2]), float(row[3])))
        else:
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            found = self._haar.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6,
                                                minSize=(int(h * 0.06), int(h * 0.06)))
            boxes = [(float(a), float(b), float(c), float(d)) for a, b, c, d in found]
        faces: list[dict[str, float]] = []
        for x, y, fw, fh in boxes:
            if fw < 12 or fh < 12:
                continue
            faces.append({
                "cx": (x + fw / 2) / w, "cy": (y + fh / 2) / h, "w": fw / w, "h": fh / h,
                "mouth": self._mouth(rgb, x, y, fw, fh),
            })
        return faces

    def close(self) -> None:
        if self._lm is not None:
            self._lm.close()


def _hist(rgb: np.ndarray) -> np.ndarray:
    import cv2

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def analyze(src: Path, start: float, end: float, src_w: int, src_h: int, fps: float | None = None) -> dict[str, Any]:
    """Sample frames in [start, end] and detect faces. Coordinates are normalised 0..1."""
    import cv2

    fps = fps or get_settings().face_sample_fps
    aw = ANALYSIS_WIDTH
    ah = max(2, int(round(src_h * aw / max(1, src_w) / 2) * 2))
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
        "-i", str(src), "-vf", f"fps={fps},scale={aw}:{ah}", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    det = _Detector()
    frames: list[dict[str, Any]] = []
    frame_bytes = aw * ah * 3
    prev_hist = None
    i = 0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            rgb = np.frombuffer(buf, dtype=np.uint8).reshape(ah, aw, 3)
            t = start + i / fps
            hist = _hist(rgb)
            cut = prev_hist is not None and cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL) < 0.55
            prev_hist = hist
            faces = det.detect(rgb, int(i * 1000 / fps))
            frames.append({"t": round(t, 3), "cut": bool(cut), "faces": faces})
            i += 1
    finally:
        det.close()
        proc.stdout.close()
        proc.wait()
    return {"start": start, "end": end, "fps": fps, "src_w": src_w, "src_h": src_h, "detector": det.kind, "frames": frames}


# ---------------------------------------------------------------------------
# tracking + camera path
# ---------------------------------------------------------------------------

@dataclass
class CropPlan:
    layout: str  # track | split | blur | full
    crop_w: int
    crop_h: int
    times: list[float]  # source seconds
    xs: list[float]  # crop left (px)
    ys: list[float]  # crop top (px)
    # split layout: second crop (bottom panel)
    xs2: list[float] | None = None
    ys2: list[float] | None = None
    face_ratio: float = 0.0
    speakers: int = 0

    def at(self, t: float, second: bool = False) -> tuple[float, float]:
        xs = self.xs2 if second and self.xs2 is not None else self.xs
        ys = self.ys2 if second and self.ys2 is not None else self.ys
        if not self.times:
            return 0.0, 0.0
        return float(np.interp(t, self.times, xs)), float(np.interp(t, self.times, ys))


def crop_size(src_w: int, src_h: int, target_aspect: float) -> tuple[int, int]:
    if src_w / src_h > target_aspect:
        h = src_h
        w = int(round(h * target_aspect / 2) * 2)
    else:
        w = src_w
        h = int(round(w / target_aspect / 2) * 2)
    return min(w, src_w - src_w % 2), min(h, src_h - src_h % 2)


def _assign_tracks(frames: list[dict[str, Any]]) -> list[dict[int, dict[str, float]]]:
    """Greedy nearest-centre association -> per-frame {track_id: face}."""
    tracks: dict[int, tuple[float, float, int]] = {}  # id -> (cx, cy, last_frame)
    next_id = 0
    out: list[dict[int, dict[str, float]]] = []
    for fi, fr in enumerate(frames):
        assigned: dict[int, dict[str, float]] = {}
        for face in sorted(fr["faces"], key=lambda f: -f["w"] * f["h"]):
            best, best_d = None, 0.18
            for tid, (cx, cy, last) in tracks.items():
                if tid in assigned or fi - last > 25:
                    continue
                d = ((face["cx"] - cx) ** 2 + (face["cy"] - cy) ** 2) ** 0.5
                if d < best_d:
                    best, best_d = tid, d
            if best is None:
                best = next_id
                next_id += 1
            tracks[best] = (face["cx"], face["cy"], fi)
            assigned[best] = face
        out.append(assigned)
    return out


def _activity(series: list[float | None], idx: int, half: int) -> float:
    vals = [v for v in series[max(0, idx - half) : idx + half + 1] if v is not None and v >= 0]
    if len(vals) < 3:
        return 0.0
    return float(np.std(vals))


def _choose_speaker(per_frame: list[dict[int, dict[str, float]]], fps: float) -> list[int | None]:
    ids = sorted({tid for fr in per_frame for tid in fr})
    if not ids:
        return [None] * len(per_frame)
    mouth = {tid: [fr[tid]["mouth"] if tid in fr else None for fr in per_frame] for tid in ids}
    area = {tid: [fr[tid]["w"] * fr[tid]["h"] if tid in fr else 0.0 for fr in per_frame] for tid in ids}
    has_mouth = any(v is not None and v >= 0 for s in mouth.values() for v in s)
    half = max(2, int(fps * 0.7))
    hold = max(2, int(fps * 0.8))
    chosen: list[int | None] = []
    cur: int | None = None
    challenger: int | None = None
    streak = 0
    for i, fr in enumerate(per_frame):
        if not fr:
            chosen.append(cur)
            continue
        present = list(fr)
        if has_mouth and len(present) > 1:
            acts = {tid: _activity(mouth[tid], i, half) for tid in present}
            best = max(acts, key=lambda k: acts[k])
            if acts[best] < 0.008:
                best = cur if cur in present else max(present, key=lambda k: area[k][i])
        else:
            best = cur if cur in present else max(present, key=lambda k: area[k][i])
        if cur is None or cur not in present:
            cur, streak, challenger = best, 0, None
        elif best != cur:
            if best == challenger:
                streak += 1
            else:
                challenger, streak = best, 1
            if streak >= hold:
                cur, streak, challenger = best, 0, None
        else:
            streak, challenger = 0, None
        chosen.append(cur)
    return chosen


def _smooth_path(targets: list[float | None], cuts: list[bool], dead_zone: float, fps: float) -> list[float]:
    """Dead-zone follower + moving average, reset at scene cuts."""
    n = len(targets)
    if n == 0:
        return []
    # split into shots
    shots: list[tuple[int, int]] = []
    s = 0
    for i in range(1, n):
        if cuts[i]:
            shots.append((s, i))
            s = i
    shots.append((s, n))
    out = [0.0] * n
    for a, b in shots:
        seg = targets[a:b]
        known = [v for v in seg if v is not None]
        if not known:
            for i in range(a, b):
                out[i] = float("nan")
            continue
        filled: list[float] = []
        last = known[0]
        for v in seg:
            last = v if v is not None else last
            filled.append(last)
        # dead-zone follower
        p = float(np.median(filled[: max(1, int(fps))]))
        follow: list[float] = []
        for v in filled:
            diff = v - p
            if abs(diff) > dead_zone:
                p += (diff - np.sign(diff) * dead_zone) * 0.45
            follow.append(p)
        # moving average (~1 s)
        k = max(1, int(fps))
        arr = np.array(follow)
        if len(arr) > k:
            pad = np.pad(arr, (k, k), mode="edge")
            kernel = np.ones(2 * k + 1) / (2 * k + 1)
            arr = np.convolve(pad, kernel, mode="valid")
        out[a:b] = [float(x) for x in arr]
    return out


def plan_crop(analysis: dict[str, Any], out_w: int, out_h: int, layout: str = "auto") -> CropPlan:
    """Compute the crop path for an output of out_w x out_h."""
    sw, sh = int(analysis["src_w"]), int(analysis["src_h"])
    fps = float(analysis["fps"])
    frames = analysis["frames"]
    times = [float(f["t"]) for f in frames]
    target_aspect = out_w / out_h
    cw, ch = crop_size(sw, sh, target_aspect)
    with_faces = sum(1 for f in frames if f["faces"])
    face_ratio = with_faces / max(1, len(frames))
    per_frame = _assign_tracks(frames)
    track_ids = {tid for fr in per_frame for tid in fr}
    presence = {tid: sum(1 for fr in per_frame if tid in fr) for tid in track_ids}
    main_tracks = [t for t, c in sorted(presence.items(), key=lambda kv: -kv[1]) if c >= 0.25 * len(frames)]

    no_crop_needed = abs(sw / sh - target_aspect) < 0.02
    if layout == "auto":
        if no_crop_needed:
            layout = "full"
        elif face_ratio < 0.15:
            layout = "blur"
        else:
            layout = "track"
    if layout == "split" and len(main_tracks) < 2:
        layout = "track" if face_ratio >= 0.15 else "blur"
    if layout in ("full", "blur", "center") or not frames:
        cx = (sw - cw) / 2
        cy = (sh - ch) / 2
        return CropPlan("full" if layout == "full" else layout, cw, ch, times or [0.0], [cx] * max(1, len(times)),
                        [cy] * max(1, len(times)), face_ratio=face_ratio, speakers=len(main_tracks))

    cuts = [bool(f["cut"]) for f in frames]

    def path_for(get_face: list[dict[str, float] | None], pw: int, ph: int, dz: float) -> tuple[list[float], list[float]]:
        tx = [None if f is None else f["cx"] * sw - pw / 2 for f in get_face]
        # keep the face a bit above the centre of the frame (headroom)
        ty = [None if f is None else f["cy"] * sh - ph * 0.42 for f in get_face]
        xs = _smooth_path(tx, cuts, dz * pw, fps)
        ys = _smooth_path(ty, cuts, dz * ph, fps)
        xs = [((sw - pw) / 2 if np.isnan(v) else min(max(0.0, v), sw - pw)) for v in xs]
        ys = [((sh - ph) / 2 if np.isnan(v) else min(max(0.0, v), sh - ph)) for v in ys]
        return xs, ys

    if layout == "split":
        left, right = sorted(main_tracks[:2], key=lambda t: float(np.mean([fr[t]["cx"] for fr in per_frame if t in fr])))
        pw, ph = crop_size(sw, sh, out_w / (out_h / 2))
        fa = [fr.get(left) for fr in per_frame]
        fb = [fr.get(right) for fr in per_frame]
        xs, ys = path_for(fa, pw, ph, 0.12)
        xs2, ys2 = path_for(fb, pw, ph, 0.12)
        return CropPlan("split", pw, ph, times, xs, ys, xs2, ys2, face_ratio=face_ratio, speakers=len(main_tracks))

    speaker = _choose_speaker(per_frame, fps)
    faces = [fr.get(sp) if sp is not None else None for fr, sp in zip(per_frame, speaker, strict=True)]
    # a change of the active speaker is a hard cut (like an editor would do), not a slow pan
    for i in range(1, len(speaker)):
        if speaker[i] is not None and speaker[i - 1] is not None and speaker[i] != speaker[i - 1]:
            cuts[i] = True
    xs, ys = path_for(faces, cw, ch, 0.08)
    return CropPlan("track", cw, ch, times, xs, ys, face_ratio=face_ratio, speakers=len(main_tracks))
