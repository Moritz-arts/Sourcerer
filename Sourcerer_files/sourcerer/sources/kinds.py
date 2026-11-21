"""What a file's name says it is: the content type of a picture, a clip, a sound or a plain file, by its extension.

A listing often gives no type (a forum's media address ends in /full, Fanbox and Fantia hand out a file name only), and a video, a sound or an
animated picture must be told from a still one before anything is fetched. Imports nothing of Sourcerer's: every site module may use it.
"""

TYPES = {"gif": "image/gif", "webp": "image/webp", "apng": "image/apng", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
         "jpe": "image/jpeg", "jfif": "image/jpeg", "avif": "image/avif", "bmp": "image/bmp", "heic": "image/heic", "heif": "image/heic",
         "tif": "image/tiff", "tiff": "image/tiff", "svg": "image/svg+xml",
         "mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "mov": "video/quicktime", "ogv": "video/ogg", "mkv": "video/x-matroska",
         "avi": "video/x-msvideo", "wmv": "video/x-ms-wmv", "flv": "video/x-flv", "mpg": "video/mpeg", "mpeg": "video/mpeg",
         "3gp": "video/3gpp", "3g2": "video/3gpp2", "ts": "video/mp2t", "m2ts": "video/mp2t", "mts": "video/mp2t",
         "mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac", "ogg": "audio/ogg", "oga": "audio/ogg", "opus": "audio/ogg",
         "wav": "audio/wav", "flac": "audio/flac", "wma": "audio/x-ms-wma"}

# Files that are neither a picture, a clip nor a sound (a post's attachments): shown as a name, never fetched as a tile's picture.
FILES = {"zip", "rar", "7z", "tar", "gz", "psd", "clip", "sai", "sai2", "csp", "kra", "xcf", "ai", "pdf", "txt", "doc", "docx", "xls", "xlsx",
         "ppt", "pptx", "blend", "fbx", "obj", "exe", "swf", "ico"}
FILE = "application/octet-stream"


def type_of(name):
    """The content type a file's extension says ("movie.mp4", or just "mp4"); FILE for a plain file, "" when it says nothing."""
    name = str(name or "").strip().lower().rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1] if "." in name else name
    return TYPES.get(ext) or (FILE if ext in FILES else "")


def plays(mime):
    """Whether a content type is played (a clip or a sound) rather than shown."""
    return (mime or "").lower().startswith(("video/", "audio/"))


def is_file(mime):
    """Whether a content type names a plain file: no picture to ask for, nothing to show."""
    return (mime or "").lower() == FILE


def typed(name):
    """The Media fields a file name settles: {"mime", "video"} (a sound plays in the clip's player, so it counts as a clip there)."""
    kind = type_of(name)
    return {"mime": kind, "video": plays(kind)}
