"""Evidence files for import and media tests, generated once and copied into each sandbox.

Video fixtures need ffmpeg on the controller machine. Everything is synthetic: colour bars,
test patterns and tones.
"""

import os
import shutil
import subprocess
from pathlib import Path

from .config import real_ffmpeg_tools, state_dir

FIXTURE_VERSION = "3"
DESCRIPTIONS = {
    "drive-clip-12s-640x360.mp4": "Valid H.264/AAC recording, 12 seconds. The normal happy path.",
    "dashcam-45s-1280x720.mp4": "Valid 45-second 720p recording; long enough to clip several moments.",
    "phone-portrait-rotated.mp4": "Portrait phone-style recording with 90 degree rotation metadata.",
    "no-audio-8s.mp4": "Video stream only, no audio.",
    "audio-only-8s.m4a": "Audio only, no video stream.",
    "truncated-header-ok.mp4": "First 40% of a valid file: readable header, missing frames.",
    "random-bytes.mp4": "Random bytes with a video file name.",
    "empty.mp4": "Zero-byte file.",
    "notes.txt": "Plain text file, not evidence.",
    "mislabelled-video.txt": "A valid MP4 recording saved with a .txt name.",
    "unicode ünïcødé 🚚 clip.mp4": "Valid recording with non-ASCII characters and an emoji in the name.",
    "spaces and (parens) [brackets] & ampersand.mp4": "Valid recording with shell-sensitive characters in the name.",
    ("very-long-file-name-" + "x" * 96 + ".mp4"): "Valid recording with a 120-character file name.",
    "catalogue-exported.json": "DT's own assessment catalogue, exported (valid import).",
    "catalogue-malformed.json": "Truncated JSON (invalid import).",
    "catalogue-wrong-shape.json": "Valid JSON that is not a DT catalogue.",
}


def run_ffmpeg(ffmpeg, arguments, target):
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *arguments, str(target)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-400:])


def build_cache():
    cache = state_dir() / f"fixtures-v{FIXTURE_VERSION}"
    marker = cache / ".complete"
    if marker.exists():
        return cache
    cache.mkdir(parents=True, exist_ok=True)
    notes = []
    (cache / "empty.mp4").write_bytes(b"")
    (cache / "random-bytes.mp4").write_bytes(os.urandom(200 * 1024))
    (cache / "notes.txt").write_text("Synthetic notes. This is not a recording.\n", encoding="utf-8")
    ffmpeg = real_ffmpeg_tools().get("ffmpeg")
    if ffmpeg:
        video = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
        audio = ["-c:a", "aac", "-b:a", "96k"]
        jobs = [
            ("drive-clip-12s-640x360.mp4", ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=12",
                                            "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
                                            *video, *audio, "-shortest", "-movflags", "+faststart"]),
            ("dashcam-45s-1280x720.mp4", ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=45",
                                          "-f", "lavfi", "-i", "sine=frequency=330:duration=45",
                                          *video, "-crf", "32", *audio, "-shortest"]),
            ("no-audio-8s.mp4", ["-f", "lavfi", "-i", "smptebars=size=640x360:rate=25:duration=8", *video]),
            ("audio-only-8s.m4a", ["-f", "lavfi", "-i", "sine=frequency=550:duration=8", *audio]),
        ]
        for name, arguments in jobs:
            try:
                run_ffmpeg(ffmpeg, arguments, cache / name)
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                notes.append(f"{name}: not generated ({error})")
        source = cache / "drive-clip-12s-640x360.mp4"
        if source.exists():
            portrait = cache / "phone-portrait-rotated.mp4"
            try:
                run_ffmpeg(ffmpeg, ["-display_rotation", "90", "-i", str(source), "-c", "copy"], portrait)
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                try:
                    run_ffmpeg(ffmpeg, ["-i", str(source), "-c", "copy", "-metadata:s:v:0", "rotate=90"], portrait)
                except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                    notes.append(f"phone-portrait-rotated.mp4: not generated ({error})")
            data = source.read_bytes()
            (cache / "truncated-header-ok.mp4").write_bytes(data[: int(len(data) * 0.4)])
            for name in ("mislabelled-video.txt", "unicode ünïcødé 🚚 clip.mp4",
                         "spaces and (parens) [brackets] & ampersand.mp4", "very-long-file-name-" + "x" * 96 + ".mp4"):
                try:
                    shutil.copyfile(source, cache / name)
                except OSError as error:
                    notes.append(f"{name}: not created ({error})")
    else:
        notes.append("ffmpeg was not found on this machine, so no video fixtures were generated.")
    readme = ["Jev QA fixtures (synthetic evidence files)", ""]
    for name, description in DESCRIPTIONS.items():
        readme.append(f"- {name}: {description}")
    if notes:
        readme += ["", "Notes:"] + [f"- {note}" for note in notes]
    (cache / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")
    marker.write_text("ok", encoding="utf-8")
    return cache


def install_fixtures(target):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    cache = build_cache()
    for item in cache.iterdir():
        if item.name.startswith("."):
            continue
        destination = target / item.name
        if not destination.exists():
            shutil.copyfile(item, destination)
    return sorted(path.name for path in target.iterdir())


def describe_fixtures(folder):
    folder = Path(folder)
    lines = []
    for path in sorted(folder.iterdir()) if folder.exists() else []:
        if path.name == "README.txt":
            continue
        size = path.stat().st_size
        lines.append(f"{path.name} ({size:,} bytes): {DESCRIPTIONS.get(path.name, '')}".rstrip(": "))
    return lines
