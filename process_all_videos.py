import subprocess
import sys
from pathlib import Path


# ------------------------------------------------------------
# Video file types to process
# ------------------------------------------------------------

VIDEO_EXTENSIONS = {
    ".avi",
    ".mkv",
    ".mp4",
    ".mov",
    ".wmv",
    ".flv",
}


TRANSCRIBE_SCRIPT = "transcribe.py"
ROMAJI_SCRIPT = "romaji.py"


def main():

    if len(sys.argv) != 2:
        print(
            f"Usage: python {Path(sys.argv[0]).name} <directory>"
        )
        sys.exit(1)

    directory = Path(sys.argv[1])

    if not directory.is_dir():
        print(f"Directory not found: {directory}")
        sys.exit(1)

    videos = sorted(
        f
        for f in directory.iterdir()
        if f.is_file()
        and f.suffix.lower() in VIDEO_EXTENSIONS
    )

    if not videos:
        print("No matching video files found.")
        return

    print(f"Found {len(videos)} video(s).\n")

    for video in videos:

        print("=" * 70)
        print(f"Processing: {video.name}")

        try:

            # ------------------------------------------------
            # Step 1: Transcribe Japanese audio
            # ------------------------------------------------

            subprocess.run(
                [
                    sys.executable,
                    TRANSCRIBE_SCRIPT,
                    str(video),
                ],
                check=True,
            )

            japanese_srt = video.with_suffix(".srt")

            # ------------------------------------------------
            # Step 2:
            #
            # Convert Japanese -> romaji
            # Extract English subtitle from MKV
            # Combine English + romaji
            # ------------------------------------------------

            subprocess.run(
                [
                    sys.executable,
                    ROMAJI_SCRIPT,
                    str(video),
                    str(japanese_srt),
                ],
                check=True,
            )

            print(f"Finished: {video.name}\n")

        except subprocess.CalledProcessError as e:

            print(f"Failed on {video.name}")
            print(e)
            print()

    print("Done.")


if __name__ == "__main__":
    main()