import re
import unicodedata


MAX_REPEATS = 8

# A first occurrence plus eight backreferences is nine total occurrences.
REPEATED_WORD = re.compile(
    rf"(?<!\w)([^\W_]+)(?:[\W_]+\1(?!\w)){{{MAX_REPEATS}}}"
)

# Japanese words and sounds often repeat without spaces. Check units up to
# 16 characters, including the prolonged sound mark.
REPEATED_JAPANESE = re.compile(
    rf"([\u3041-\u3096\u309D-\u309F\u30A1-\u30FA\u30FC-\u30FF"
    rf"\u3400-\u4DBF\u4E00-\u9FFF\u3005]{{1,16}})\1{{{MAX_REPEATS}}}"
)


def has_runaway_repetition(text):
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return bool(
        REPEATED_JAPANESE.search(normalized)
        or REPEATED_WORD.search(normalized)
    )
