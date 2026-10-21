"""Live conversion of videos browsers cannot play (mkv, avi, …) into fragmented MP4, with ffmpeg."""
import asyncio
import json
import os
import tempfile

from app import stream, subtitles

FFMPEG = os.getenv("FFMPEG", "ffmpeg")
FFPROBE = os.getenv("FFPROBE", "ffprobe")
PROBE_BYTES = 4 * 1024 * 1024  # the codec is in the first bytes of the file


def video_args(codec):
    if codec == "h264":
        return ["-c:v", "copy"]  # already what browsers play: only repackage it, almost free
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]


async def _probe(source, *args):
    """ffprobe's answer about the start of the (maybe still downloading) file; ffprobe is more reliable on a file than on a pipe."""
    head = b"".join([c async for c in stream.iter_bytes(source, 0, min(source.size, PROBE_BYTES) - 1)])
    with tempfile.NamedTemporaryFile() as f:
        f.write(head)
        f.flush()
        proc = await asyncio.create_subprocess_exec(
            FFPROBE, "-v", "error", *args, f.name, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await proc.communicate()
    return out.decode()


async def probe_codec(source):
    """Name of the first video stream's codec."""
    return (await _probe(source, "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0")).strip() or None


async def probe_audio(source):
    """The audio tracks of the file: [{index, lang, label, codec, channels}], index counting audio tracks only.

    shortcut: read from the first 4 MB, so an mp4 whose index is at the end of the file lists nothing.
    """
    out = await _probe(
        source, "-select_streams", "a", "-show_entries", "stream=codec_name,channels:stream_tags=language,title", "-of", "json"
    )
    try:
        streams = json.loads(out).get("streams", [])
    except ValueError:
        return []
    tracks = []
    for i, s in enumerate(streams):
        tags = s.get("tags") or {}
        lang = subtitles.CODES.get((tags.get("language") or "").lower())
        label = subtitles.LABELS.get(lang) or tags.get("title") or (tags.get("language") or "").upper() or f"Track {i + 1}"
        tracks.append({"index": i, "lang": lang, "label": label, "codec": s.get("codec_name"), "channels": s.get("channels")})
    return tracks


async def convert(source, audio=0, start=0):
    """Start ffmpeg on the source and return an async iterator of MP4 bytes (raises FileNotFoundError without ffmpeg).

    `audio` picks the audio track, `start` skips the first seconds (what the member had already watched).

    shortcut: a live conversion cannot be sliced, so the player cannot seek in what has not been produced yet;
    a movie that is fully downloaded could be converted once to a seekable file.
    """
    codec = await probe_codec(source)
    proc = await asyncio.create_subprocess_exec(
        FFMPEG, "-v", "error", "-i", "pipe:0",
        # shortcut: skipping is done on the output side (a pipe cannot be seeked), so everything before `start` is still read,
        # and with a copied video the picture resumes at the next keyframe
        *(["-ss", str(start)] if start else []),
        "-map", "0:v:0", "-map", f"0:a:{audio}?",  # first video, the chosen audio if any: no subtitle streams in an mp4
        *video_args(codec), "-c:a", "aac", "-b:a", "128k",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",  # playable before the end is written
        "-f", "mp4", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    return _pump(source, proc)


async def _pump(source, proc):
    async def feed():
        try:
            async for chunk in stream.iter_bytes(source, 0, source.size - 1):
                proc.stdin.write(chunk)
                await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, stream.StreamStalled):
            pass  # ffmpeg stopped reading, or the download stalled: what was produced so far is all there is
        finally:
            proc.stdin.close()

    feeder = asyncio.create_task(feed())
    try:
        while chunk := await proc.stdout.read(64 * 1024):
            yield chunk
    finally:  # also when the viewer leaves: never leave an ffmpeg running
        feeder.cancel()
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
