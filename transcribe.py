import os
import sys
import subprocess
import tempfile
from pathlib import Path

from faster_whisper import WhisperModel

from subtitle_repetition import has_runaway_repetition


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

MODEL = "large-v3"
DEVICE = "cuda"
COMPUTE_TYPE = "float16"
LANGUAGE = "ja"


# ------------------------------------------------------------
# Input
# ------------------------------------------------------------

if len(sys.argv) != 2:
    print(f"Usage: python {Path(sys.argv[0]).name} <video>")
    sys.exit(1)

input_file = Path(sys.argv[1])

if not input_file.exists():
    print(f"File not found: {input_file}")
    sys.exit(1)


# ------------------------------------------------------------
# Find Japanese audio track
# ------------------------------------------------------------

print("Finding Japanese audio track...")

probe = subprocess.run(
    [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a",
        "-show_entries",
        "stream=index:stream_tags=language,title",
        "-of", "default=noprint_wrappers=1",
        str(input_file),
    ],
    capture_output=True,
    text=True,
    check=True,
)

lines = probe.stdout.splitlines()

audio_streams = []
current = None

for line in lines:
    if "=" not in line:
        continue

    key, value = line.split("=", 1)

    if key == "index":
        if current is not None:
            audio_streams.append(current)

        current = {
            "index": value,
            "language": "",
            "title": "",
        }

    elif current is not None:
        if key == "TAG:language":
            current["language"] = value.lower()

        elif key == "TAG:title":
            current["title"] = value.lower()

if current is not None:
    audio_streams.append(current)


# Prefer Japanese language metadata
japanese_audio = None

for stream in audio_streams:
    if stream["language"] in {"ja", "jpn", "japanese"}:
        japanese_audio = stream["index"]
        break


# If language metadata didn't identify it, check the title
if japanese_audio is None:
    for stream in audio_streams:
        if "japanese" in stream["title"]:
            japanese_audio = stream["index"]
            break


if japanese_audio is None:
    print("Could not find a Japanese audio track.")
    print("Available audio streams:")

    for stream in audio_streams:
        print(
            f"  Stream {stream['index']}: "
            f"language={stream['language']!r}, "
            f"title={stream['title']!r}"
        )

    sys.exit(1)


print(f"Using Japanese audio stream: {japanese_audio}")


# ------------------------------------------------------------
# Extract audio
# ------------------------------------------------------------

audio_extensions = {
    ".wav",
    ".mp3",
    ".flac",
    ".m4a",
    ".aac",
    ".opus",
    ".ogg",
    ".wma",
}

temp_audio = None

if input_file.suffix.lower() in audio_extensions:
    audio_file = str(input_file)

else:
    temp_audio = tempfile.NamedTemporaryFile(
        suffix=".wav",
        delete=False
    )
    temp_audio.close()

    print("Extracting audio...")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", str(input_file),
            "-map", f"0:{japanese_audio}",
            "-ac", "1",
            "-ar", "16000",
            "-vn",
            temp_audio.name,
        ],
        check=True,
    )

    audio_file = temp_audio.name


# ------------------------------------------------------------
# Whisper
# ------------------------------------------------------------

model = WhisperModel(
    MODEL,
    device=DEVICE,
    compute_type=COMPUTE_TYPE,
)

print("Transcribing...")

segments, info = model.transcribe(
    audio_file,
    language=LANGUAGE,
    beam_size=8,
    best_of=8,
    vad_filter=True,
    vad_parameters=dict(
        min_silence_duration_ms=250,
    ),
    word_timestamps=True,
    condition_on_previous_text=False,
    temperature=0.0,
)


# ------------------------------------------------------------
# Timestamp formatting
# ------------------------------------------------------------

def format_timestamp(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    millis = int(
        round(
            (
                seconds
                - secs
                - minutes * 60
                - hours * 3600
            )
            * 1000
        )
    )

    if millis == 1000:
        millis = 0
        secs += 1

    if secs == 60:
        secs = 0
        minutes += 1

    if minutes == 60:
        minutes = 0
        hours += 1

    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


# ------------------------------------------------------------
# Write Japanese SRT
# ------------------------------------------------------------

output_file = input_file.with_suffix(".srt")

with open(output_file, "w", encoding="utf-8") as f:

    i = 0
    for seg in segments:
        text = seg.text.strip()
        if has_runaway_repetition(text):
            continue

        i += 1
        f.write(f"{i}\n")

        f.write(
            f"{format_timestamp(seg.start)} --> "
            f"{format_timestamp(seg.end)}\n"
        )

        f.write(text)
        f.write("\n\n")


# ------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------

if temp_audio is not None:
    os.remove(temp_audio.name)


print(f"Done! Wrote {output_file}")
