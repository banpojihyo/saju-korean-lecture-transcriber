#!/usr/bin/env python3
"""Transcribe Korean speech from video files with faster-whisper.

Default behavior processes one sample video from a folder and writes
plain text + SRT outputs.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from faster_whisper import WhisperModel


VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".wmv",
    ".m4v",
    ".webm",
    ".flv",
}


@dataclass
class Segment:
    start: float
    end: float
    text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe Korean speech from a video folder."
    )
    parser.add_argument("--input-dir", required=True, help="Folder containing videos")
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for transcript files (default: ./output)",
    )
    parser.add_argument(
        "--model",
        default="large-v3",
        help="faster-whisper model name (default: large-v3)",
    )
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cpu", "cuda"],
        help="Inference device (default: auto)",
    )
    parser.add_argument(
        "--compute-type",
        default="int8",
        help="Compute type for faster-whisper (default: int8)",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        default=5,
        help="Beam search width (default: 5)",
    )
    parser.add_argument(
        "--language",
        default="ko",
        help="Language code for transcription (default: ko)",
    )
    parser.add_argument(
        "--sample-only",
        action="store_true",
        help="Process only one video (first in sorted order)",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Maximum number of files to process. Ignored when --sample-only is set.",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="Optional max audio duration (seconds) for quick tests.",
    )
    return parser.parse_args()


def list_videos(input_dir: Path) -> List[Path]:
    videos = [
        p
        for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return sorted(videos, key=lambda p: p.name)


def hhmmss_millis(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def sanitize_text(text: str) -> str:
    return " ".join(text.strip().split())


def write_txt(path: Path, segments: Iterable[Segment]) -> None:
    lines = [seg.text for seg in segments if seg.text]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def write_srt(path: Path, segments: Iterable[Segment]) -> None:
    parts: List[str] = []
    index = 1
    for seg in segments:
        if not seg.text:
            continue
        parts.append(str(index))
        parts.append(f"{hhmmss_millis(seg.start)} --> {hhmmss_millis(seg.end)}")
        parts.append(seg.text)
        parts.append("")
        index += 1
    path.write_text("\n".join(parts), encoding="utf-8-sig")


def transcribe_file(
    model: WhisperModel,
    video_path: Path,
    output_dir: Path,
    language: str,
    beam_size: int,
    max_seconds: float | None,
) -> tuple[Path, Path]:
    print(f"[INFO] Transcribing: {video_path}")
    segments_iter, info = model.transcribe(
        str(video_path),
        language=language,
        task="transcribe",
        beam_size=beam_size,
        vad_filter=True,
        max_initial_timestamp=0.0,
        word_timestamps=False,
        condition_on_previous_text=False,
    )
    print(
        f"[INFO] Detected language={info.language}, probability={info.language_probability:.4f}"
    )

    segments: List[Segment] = []
    for raw in segments_iter:
        if max_seconds is not None and raw.start > max_seconds:
            break
        text = sanitize_text(raw.text)
        if not text:
            continue
        end = raw.end
        if max_seconds is not None:
            end = min(end, max_seconds)
        segments.append(Segment(start=raw.start, end=end, text=text))
        if max_seconds is not None and raw.end >= max_seconds:
            break

    if not segments:
        raise RuntimeError(f"No transcript segments produced for: {video_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    txt_path = output_dir / f"{video_path.stem}.txt"
    srt_path = output_dir / f"{video_path.stem}.srt"

    write_txt(txt_path, segments)
    write_srt(srt_path, segments)
    return txt_path, srt_path


def is_cuda_runtime_error(exc: RuntimeError) -> bool:
    text = str(exc).lower()
    cuda_signals = ("cublas", "cudnn", "cuda", "libcudart", "cufft", "curand")
    return any(signal in text for signal in cuda_signals)


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"[ERROR] Invalid --input-dir: {input_dir}")
        return 1

    output_dir = Path(args.output_dir)
    videos = list_videos(input_dir)
    if not videos:
        print(f"[ERROR] No video files found in: {input_dir}")
        return 1

    if args.sample_only:
        targets = videos[:1]
    else:
        targets = videos
        if args.max_files is not None and args.max_files > 0:
            targets = targets[: args.max_files]

    print(f"[INFO] Found {len(videos)} videos. Processing {len(targets)} file(s).")
    current_device = args.device
    current_compute_type = args.compute_type
    print(
        f"[INFO] Loading model='{args.model}', device='{current_device}', compute_type='{current_compute_type}'"
    )
    model = WhisperModel(
        args.model, device=current_device, compute_type=current_compute_type
    )

    for idx, video in enumerate(targets, start=1):
        print(f"[INFO] ({idx}/{len(targets)}) Start")
        try:
            txt_path, srt_path = transcribe_file(
                model=model,
                video_path=video,
                output_dir=output_dir,
                language=args.language,
                beam_size=args.beam_size,
                max_seconds=args.max_seconds,
            )
        except RuntimeError as exc:
            if current_device == "cpu" or not is_cuda_runtime_error(exc):
                raise
            current_device = "cpu"
            if current_compute_type in {"float16", "int8_float16"}:
                current_compute_type = "int8"
            print(
                "[WARN] CUDA runtime not available. Falling back to CPU "
                f"(compute_type={current_compute_type})."
            )
            model = WhisperModel(
                args.model, device=current_device, compute_type=current_compute_type
            )
            txt_path, srt_path = transcribe_file(
                model=model,
                video_path=video,
                output_dir=output_dir,
                language=args.language,
                beam_size=args.beam_size,
                max_seconds=args.max_seconds,
            )
        print(f"[DONE] TXT: {txt_path}")
        print(f"[DONE] SRT: {srt_path}")

    print("[DONE] All tasks completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
