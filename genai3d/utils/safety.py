"""Upload guards (spec 10B.8)."""
from __future__ import annotations


class SafetyError(Exception):
    pass


# Magic bytes. Never trust the file extension — it is attacker-controlled and
# a .jpg that is actually an HTML document is a stored-XSS vector the moment
# something serves it back.
MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


def sniff(data: bytes) -> str | None:
    for sig, mime in MAGIC:
        if data.startswith(sig):
            return mime
    # WEBP is RIFF....WEBP
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # TIFF
    if data.startswith(b"II*\x00") or data.startswith(b"MM\x00*"):
        return "image/tiff"
    # Fallback: test if PIL can decode it safely
    try:
        import io
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        fmt = (img.format or "").lower()
        if fmt in ("jpeg", "jpg", "png", "gif", "webp", "bmp", "tiff", "ico", "avif", "heic"):
            return f"image/{fmt}"
    except Exception:
        pass
    return None


def check_upload(data: bytes, max_mb: int = 8) -> str:
    """Validate an upload. Returns the sniffed MIME type or raises SafetyError."""
    if not data:
        raise SafetyError("empty upload")
    size_mb = len(data) / (1024 * 1024)
    if size_mb > max_mb:
        raise SafetyError(f"upload is {size_mb:.1f} MB, limit is {max_mb} MB")
    mime = sniff(data)
    if mime is None:
        raise SafetyError("not a recognised image (magic bytes did not match)")
    return mime


def check_subject_area(alpha_fraction: float) -> None:
    """The cut-out must be a single clear subject."""
    if alpha_fraction < 0.01:
        raise SafetyError(
            "no clear subject found — it fills less than 1% of the frame"
        )


# Refused outright (spec 10B.8). ARIA builds objects, not people.
PERSON_WORDS = {
    "person", "people", "man", "woman", "boy", "girl", "child", "baby",
    "face", "portrait", "selfie", "human", "someone", "myself", "himself",
    "herself", "my friend", "my wife", "my husband", "my son", "my daughter",
}


def check_not_a_person(hint: str) -> None:
    h = (hint or "").lower()
    for w in PERSON_WORDS:
        if w in h:
            raise SafetyError(
                "I can build objects, not people. Try a piece of furniture "
                "or an object instead."
            )
