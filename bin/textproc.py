"""Text processing shared by the Stop hook and the TTS daemon. Stdlib-only.

- ``pick_speech_source`` / ``clean_for_speech`` turn a raw reply into pleasant
  spoken prose (used by the Stop hook before sending to the daemon).
- ``chunk_text`` splits spoken text into synthesis-sized pieces; the first
  chunk is a single sentence so first audio lands sooner (see Task 04).
"""

import re

MAX_CHUNK_CHARS = 280


def pick_speech_source(text):
    """Return only the part of the reply meant to be spoken.

    Preferred: the final paragraph the assistant marks with a 🔊 line-start.
    Fallback: the whole reply (speak-time truncation caps it at max_chars).
    """
    matches = list(re.finditer(
        r"^\s*🔊\s*(?:voice summary\s*:?\s*)?",
        text, re.IGNORECASE | re.MULTILINE,
    ))
    if matches:
        rest = text[matches[-1].end():].split("\n\n", 1)[0].strip()
        if rest:
            return rest
    return text


def clean_for_speech(text):
    """Make text pleasant to hear: drop code, markdown, URLs, symbols, emoji."""
    text = re.sub(r"```.*?```", " code block omitted. ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)   # [label](url) -> label
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"^[\s|:\-]+$", "", text, flags=re.MULTILINE)  # md table rules
    text = text.replace("|", " ")
    text = re.sub(r"^[#>\-\*\+•▪◦‣]+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"(?<=\d)\s*[–—-]\s*(?=\d)", " to ", text)     # 5-10 -> 5 to 10
    text = re.sub(r"\s*[–—]+\s*", ", ", text)
    text = re.sub(r"\s-{1,3}\s", ", ", text)
    text = re.sub(r"\.{3,}|…", ". ", text)
    text = re.sub(r"\s*(?:->|=>|→|⇒|⟶)\s*", " to ", text)       # arrows -> "to"
    text = re.sub(r"[\*~`#^<>=+\\{}\[\]\"]", "", text)
    text = text.replace("/", " ").replace("_", " ")
    text = re.sub(
        r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
        r"✀-➿←-⇿⬀-⯿️‍✓✔✗✘]+",
        " ",
        text,
    )
    text = re.sub(r"\s*,\s*(?=[,.;:!?])", "", text)
    text = re.sub(r"([,.;:!?])\1+", r"\1", text)
    text = re.sub(r"\s+([,.;:!?])(?=\s|$)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def chunk_text(text, max_chars=MAX_CHUNK_CHARS, small_first=True):
    """Split into sentence groups so each generation stays short.

    With ``small_first`` the first chunk is a single sentence, so the first
    audio lands after one sentence of synthesis instead of a full group.
    """
    sentences = re.split(r"(?<=[.!?;:])\s+", text)
    chunks, current = [], ""
    for s in sentences:
        while len(s) > max_chars:  # pathological run-on: hard split
            chunks.append(s[:max_chars])
            s = s[max_chars:]
        # Emit the very first sentence on its own for low time-to-first-audio.
        if small_first and not chunks and current:
            chunks.append(current)
            current = s
        elif len(current) + len(s) + 1 > max_chars and current:
            chunks.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    if current:
        chunks.append(current)
    return chunks
