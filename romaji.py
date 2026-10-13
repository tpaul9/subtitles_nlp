import re
import sys
import subprocess
import tempfile
from pathlib import Path

from fugashi import Tagger
from pykakasi import kakasi


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

ROMAJI_FONT = "Impress BT"
ROMAJI_SIZE = 24
ROMAJI_COLOR = "#f7c3ae"


# ------------------------------------------------------------
# Japanese -> Romaji
# ------------------------------------------------------------

tagger = Tagger()

kks = kakasi()
converter = kks.convert


def japanese_to_romaji(text):
    words = []

    for token in tagger(text):
        surface = token.surface

        # Preserve punctuation and spaces
        if re.fullmatch(
            r"[、。！？!?・…（）「」『』\s]+",
            surface
        ):
            words.append(surface)
            continue

        reading = None

        try:
            feats = token.feature

            if hasattr(feats, "kana"):
                reading = feats.kana
            elif hasattr(feats, "pron"):
                reading = feats.pron

        except Exception:
            pass

        source = reading if reading else surface

        romaji = "".join(
            item["hepburn"]
            for item in converter(source)
        )

        words.append(romaji)

    text = " ".join(words)

    # Cleanup spacing around punctuation
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ------------------------------------------------------------
# SRT parsing
# ------------------------------------------------------------

timestamp_pattern = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})"
    r"\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})$"
)


def timestamp_to_seconds(timestamp):
    match = re.match(
        r"(\d{2}):(\d{2}):(\d{2}),(\d{3})",
        timestamp
    )

    if not match:
        raise ValueError(
            f"Invalid timestamp: {timestamp}"
        )

    hours, minutes, seconds, millis = map(
        int,
        match.groups()
    )

    return (
        hours * 3600
        + minutes * 60
        + seconds
        + millis / 1000
    )


def seconds_to_timestamp(seconds):
    total_millis = round(seconds * 1000)

    hours = total_millis // 3_600_000
    total_millis %= 3_600_000

    minutes = total_millis // 60_000
    total_millis %= 60_000

    secs = total_millis // 1_000
    millis = total_millis % 1_000

    return (
        f"{hours:02}:"
        f"{minutes:02}:"
        f"{secs:02},"
        f"{millis:03}"
    )


def parse_srt(filename):
    """
    Parse an SRT file.

    Returns:

        [
            {
                "start": float,
                "end": float,
                "text": str
            },
            ...
        ]
    """

    with open(
        filename,
        "r",
        encoding="utf-8-sig"
    ) as f:
        content = f.read()

    blocks = re.split(
        r"\n\s*\n",
        content.strip()
    )

    subtitles = []

    for block in blocks:
        lines = block.splitlines()

        if len(lines) < 3:
            continue

        timestamp_index = None

        for i, line in enumerate(lines):
            if timestamp_pattern.match(line.strip()):
                timestamp_index = i
                break

        if timestamp_index is None:
            continue

        timestamp_line = lines[
            timestamp_index
        ].strip()

        match = timestamp_pattern.match(
            timestamp_line
        )

        start = timestamp_to_seconds(
            f"{match.group(1)}:"
            f"{match.group(2)}:"
            f"{match.group(3)},"
            f"{match.group(4)}"
        )

        end = timestamp_to_seconds(
            f"{match.group(5)}:"
            f"{match.group(6)}:"
            f"{match.group(7)},"
            f"{match.group(8)}"
        )

        text = "\n".join(
            lines[timestamp_index + 1:]
        ).strip()

        subtitles.append(
            {
                "start": start,
                "end": end,
                "text": text,
            }
        )

    return subtitles


# ------------------------------------------------------------
# Extract English "Full" subtitle
# ------------------------------------------------------------

def extract_english_subtitle(video_file):
    print("Finding English Full subtitle track...")

    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-select_streams", "s",
            "-show_entries",
            "stream=index:stream_tags=language,title",
            "-of", "default=noprint_wrappers=1",
            str(video_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.splitlines()

    streams = []
    current = None

    for line in lines:
        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        if key == "index":
            if current is not None:
                streams.append(current)

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
        streams.append(current)

    english_stream = None

    for stream in streams:
        language = stream["language"]
        title = stream["title"]

        is_english = (
            language in {"eng", "en", "english"}
            or "nglish" in title
        )

        is_full = "full" in title

        if is_english and is_full:
            english_stream = stream["index"]
            break

    if not english_stream:
        #Take any stream with title nglish
        english_stream = streams[0]["index"]

    if english_stream is None:
        print(
            "\nCould not find an English subtitle "
            "track containing 'Full'."
        )

        print("\nAvailable subtitle streams:")

        for stream in streams:
            print(
                f"  Stream {stream['index']}: "
                f"language={stream['language']!r}, "
                f"title={stream['title']!r}"
            )

        raise RuntimeError(
            "English Full subtitle track not found."
        )

    print(
        f"Using English Full subtitle stream: "
        f"{english_stream}"
    )

    temp_file = tempfile.NamedTemporaryFile(
        suffix=".srt",
        delete=False
    )

    temp_file.close()

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", str(video_file),
            "-map", f"0:{english_stream}",
            "-c:s", "srt",
            temp_file.name,
        ],
        check=True,
    )

    return Path(temp_file.name)


# ------------------------------------------------------------
# Find active subtitles
# ------------------------------------------------------------

def get_active_subtitles(subtitles, start, end):
    """
    Return all subtitles that are active during the
    interval [start, end].

    A subtitle is considered active if its time range
    overlaps the interval.
    """

    active = []

    for subtitle in subtitles:

        if (
            subtitle["start"] < end
            and subtitle["end"] > start
        ):
            active.append(subtitle)

    active.sort(
        key=lambda subtitle: subtitle["start"]
    )

    return active


# ------------------------------------------------------------
# Combine subtitle timelines
# ------------------------------------------------------------

def combine_subtitles(
    english_subtitles,
    romaji_subtitles
):
    """
    Merge two subtitle timelines without changing their
    underlying timing.

    Every start/end timestamp from either subtitle stream
    becomes a boundary.

    For each resulting interval, the currently active
    English and romaji subtitles are displayed.

    This means a long romaji subtitle can span multiple
    English subtitle changes without causing those English
    subtitles to be merged.
    """

    boundaries = set()

    for subtitle in english_subtitles:
        boundaries.add(subtitle["start"])
        boundaries.add(subtitle["end"])

    for subtitle in romaji_subtitles:
        boundaries.add(subtitle["start"])
        boundaries.add(subtitle["end"])

    boundaries = sorted(boundaries)

    combined = []

    for i in range(len(boundaries) - 1):

        start = boundaries[i]
        end = boundaries[i + 1]

        if end <= start:
            continue

        active_english = get_active_subtitles(
            english_subtitles,
            start,
            end
        )

        active_romaji = get_active_subtitles(
            romaji_subtitles,
            start,
            end
        )

        # Nothing displayed during this interval
        if not active_english and not active_romaji:
            continue

        english_texts = []
        romaji_texts = []

        # Preserve all active English text.
        for subtitle in active_english:

            text = subtitle["text"].strip()

            if text and text not in english_texts:
                english_texts.append(text)

        # Preserve all active romaji text.
        for subtitle in active_romaji:

            text = subtitle["text"].strip()

            if text and text not in romaji_texts:
                romaji_texts.append(text)

        lines = []

        if english_texts:
            lines.extend(english_texts)

        if romaji_texts:

            romaji_text = " ".join(
                romaji_texts
            )

            romaji_text = (
                f'<font face="{ROMAJI_FONT}" '
                f'size="{ROMAJI_SIZE}" '
                f'color="{ROMAJI_COLOR}">'
                f'{romaji_text}'
                f'</font>'
            )

            lines.append(romaji_text)

        if not lines:
            continue

        combined.append(
            {
                "start": start,
                "end": end,
                "text": "\n".join(lines),
            }
        )

    return combined


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

if len(sys.argv) != 3:
    print(
        f"Usage: python {Path(sys.argv[0]).name} "
        f"<video> <japanese.srt>"
    )
    sys.exit(1)


video_file = Path(sys.argv[1])
japanese_srt = Path(sys.argv[2])

if not video_file.exists():
    print(f"Video not found: {video_file}")
    sys.exit(1)

if not japanese_srt.exists():
    print(
        f"Subtitle file not found: {japanese_srt}"
    )
    sys.exit(1)


# ------------------------------------------------------------
# Read Japanese transcription
# ------------------------------------------------------------

print("Reading Japanese transcription...")

japanese_subtitles = parse_srt(
    japanese_srt
)


# ------------------------------------------------------------
# Convert Japanese -> Romaji
# ------------------------------------------------------------

print("Converting Japanese to romaji...")

romaji_subtitles = []

for subtitle in japanese_subtitles:

    romaji_subtitles.append(
        {
            "start": subtitle["start"],
            "end": subtitle["end"],
            "text": japanese_to_romaji(
                subtitle["text"]
            ),
        }
    )


# ------------------------------------------------------------
# Extract English subtitle
# ------------------------------------------------------------

english_srt = extract_english_subtitle(
    video_file
)

try:

    print("Reading English subtitles...")

    english_subtitles = parse_srt(
        english_srt
    )

    # --------------------------------------------------------
    # Merge timelines
    # --------------------------------------------------------

    print("Merging subtitle timelines...")

    combined_subtitles = combine_subtitles(
        english_subtitles,
        romaji_subtitles
    )

    # --------------------------------------------------------
    # Write combined SRT
    # --------------------------------------------------------

    output_file = video_file.with_suffix(
        ".combined.srt"
    )

    print("Writing combined subtitles...")

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as fout:

        for i, subtitle in enumerate(
            combined_subtitles,
            start=1
        ):

            fout.write(f"{i}\n")

            fout.write(
                f"{seconds_to_timestamp(subtitle['start'])}"
                f" --> "
                f"{seconds_to_timestamp(subtitle['end'])}\n"
            )

            fout.write(
                subtitle["text"]
            )

            fout.write("\n\n")

    print(f"Wrote {output_file}")

finally:

    # Delete temporary extracted English subtitle
    try:
        english_srt.unlink()
    except Exception:
        pass