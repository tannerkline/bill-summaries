"""Create narrated vertical videos from the generated social image."""

from functools import lru_cache
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile


class DebugVideoError(RuntimeError):
    """Raised when local narration or video rendering fails."""


KOKORO_DATA_DIR = os.environ.get("KOKORO_DATA_DIR", "/usr/src/app/voices")
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "af_heart")
KOKORO_SPEED = os.environ.get("KOKORO_SPEED", "1.0")
# The marker is never sent to Kokoro. It lets the application ask for a precise,
# natural beat between an introductory title and the summary.
NARRATION_PAUSE_MARKER = "\n[[ONE_SECOND_PAUSE]]\n"


def _spoken_text(text: str) -> str:
    """Expand numbered legislative references without changing published copy."""
    prefixes = (
        (r"H\.?\s*Con\.?\s*Res\.?", "House concurrent resolution"),
        (r"S\.?\s*Con\.?\s*Res\.?", "Senate concurrent resolution"),
        (r"H\.?\s*J\.?\s*Res\.?", "House joint resolution"),
        (r"S\.?\s*J\.?\s*Res\.?", "Senate joint resolution"),
        (r"H\.?\s*Res\.?", "House resolution"),
        (r"S\.?\s*Res\.?", "Senate resolution"),
        (r"H\.?\s*R\.?", "House bill"),
        (r"S\.?", "Senate bill"),
    )
    for prefix, spoken in prefixes:
        # Permit compact/spaced citations, but not a suffix of e.g. U.S. 42.
        text = re.sub(
            rf"(?<![\w.]){prefix}\s*(?=\d)", f"{spoken} ", text,
            flags=re.IGNORECASE,
        )
    return re.sub(r"\bNo\.\s*(?=\d)", "number ", text, flags=re.IGNORECASE)


def _error_text(result: subprocess.CompletedProcess) -> str:
    """Return a readable subprocess error, including byte-stream output."""
    details = result.stderr or result.stdout or b""
    if isinstance(details, bytes):
        return details.decode("utf-8", errors="replace").strip()
    return details.strip()


def _run(command: list[str]) -> subprocess.CompletedProcess:
    """Run a media command and expose its useful error text to the caller."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise DebugVideoError(f"could not run {command[0]}: {error}") from error

    if result.returncode:
        details = _error_text(result)
        raise DebugVideoError(f"{command[0]} failed: {details or 'unknown error'}")
    return result


def _validate_wav(
    audio_path: Path, speech_result: subprocess.CompletedProcess | None = None
) -> None:
    """Ensure Kokoro or FFmpeg produced a readable WAV before video rendering."""
    if not audio_path.is_file() or audio_path.stat().st_size == 0:
        details = _error_text(speech_result) if speech_result is not None else ""
        raise DebugVideoError(
            "speech synthesis completed without creating a WAV file"
            f"{f': {details}' if details else ''}"
        )
    with audio_path.open("rb") as audio_file:
        if audio_file.read(12)[:4] != b"RIFF":
            raise DebugVideoError("speech synthesis created an invalid WAV file")


@lru_cache(maxsize=1)
def _kokoro():
    """Load local model files once, only when narration is requested."""
    from kokoro_onnx import Kokoro

    directory = Path(KOKORO_DATA_DIR)
    model = directory / "kokoro-v1.0.onnx"
    voices = directory / "voices-v1.0.bin"
    if not model.is_file() or not voices.is_file():
        raise DebugVideoError(
            f"Kokoro model files are missing from {directory}; rebuild the Docker image"
        )
    return Kokoro(str(model), str(voices))


def _synthesize_speech(text: str, audio_path: Path) -> None:
    """Write one spoken segment using local Kokoro inference."""
    try:
        speed = float(KOKORO_SPEED)
        if not math.isfinite(speed) or not 0.5 <= speed <= 2.0:
            raise ValueError
    except (TypeError, ValueError) as error:
        raise DebugVideoError("KOKORO_SPEED must be a number between 0.5 and 2.0") from error

    try:
        import soundfile

        engine = _kokoro()
        if KOKORO_VOICE not in engine.get_voices():
            raise DebugVideoError(f"Unknown KOKORO_VOICE: {KOKORO_VOICE}")
        samples, sample_rate = engine.create(
            _spoken_text(text), voice=KOKORO_VOICE, speed=speed, lang="en-us"
        )
        if len(samples) == 0:
            raise DebugVideoError("Kokoro returned empty audio")
        soundfile.write(str(audio_path), samples, sample_rate, subtype="PCM_16")
    except DebugVideoError:
        raise
    except Exception as error:
        raise DebugVideoError(f"Kokoro speech synthesis failed: {error}") from error
    _validate_wav(audio_path)


def _synthesize_narration(narration: str, audio_path: Path, temp_directory: Path) -> None:
    """Synthesize narration, inserting one second of actual silence when asked."""
    introduction, marker, summary = narration.partition(NARRATION_PAUSE_MARKER)
    if not marker or not introduction.strip() or not summary.strip():
        _synthesize_speech(narration, audio_path)
        return

    introduction_path = temp_directory / "introduction.wav"
    summary_path = temp_directory / "summary.wav"
    _synthesize_speech(introduction.strip(), introduction_path)
    _synthesize_speech(summary.strip(), summary_path)
    merge_result = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(introduction_path),
            "-f",
            "lavfi",
            "-t",
            "1",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-i",
            str(summary_path),
            "-filter_complex",
            (
                "[0:a]aresample=24000,aformat=channel_layouts=mono[a0];"
                "[1:a]aresample=24000,aformat=channel_layouts=mono[a1];"
                "[2:a]aresample=24000,aformat=channel_layouts=mono[a2];"
                "[a0][a1][a2]concat=n=3:v=0:a=1[a]"
            ),
            "-map",
            "[a]",
            "-c:a",
            "pcm_s16le",
            str(audio_path),
        ]
    )
    _validate_wav(audio_path, merge_result)


def create_narrated_video(image_path: Path, narration: str, video_path: Path) -> None:
    """Make a gently animated vertical MP4 that narrates ``narration``.

    The visual treatment uses a slow, centered push-in rather than a frozen
    frame. It makes the static card feel intentional in a Shorts feed without
    distracting from the narration or relying on a cloud video service. Kokoro
    and FFmpeg are both installed in the application image. The temporary WAV
    is deliberately kept outside the debug output directory so the review
    folder contains only the requested final artifacts.
    """
    if not narration.strip():
        raise DebugVideoError("refusing to create a video with empty narration")

    with tempfile.TemporaryDirectory(prefix="bill-summary-video-") as temp_directory:
        temporary_path = Path(temp_directory)
        audio_path = temporary_path / "narration.wav"
        # Kokoro is a local neural voice. Its model is fetched once when the
        # container image is built, so debug runs make no external TTS request.
        _synthesize_narration(narration, audio_path, temporary_path)

        _run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-loop",
                "1",
                "-framerate",
                "30",
                "-i",
                str(image_path),
                "-i",
                str(audio_path),
                "-vf",
                (
                    "scale=1188:2112,"
                    "zoompan=z='min(zoom+0.00018,1.08)':"
                    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                    "d=1:s=1080x1920:fps=30,"
                    "fade=t=in:st=0:d=0.45"
                ),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-tune",
                "stillimage",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                "-movflags",
                "+faststart",
                str(video_path),
            ]
        )
