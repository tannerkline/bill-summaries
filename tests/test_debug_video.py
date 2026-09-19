from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from util.debug_video import (
    DebugVideoError, NARRATION_PAUSE_MARKER, _synthesize_speech, create_narrated_video,
)


class DebugVideoTests(unittest.TestCase):
    @patch("util.debug_video._synthesize_speech")
    @patch("util.debug_video.subprocess.run")
    def test_uses_local_tts_then_renders_an_animated_portrait_video(self, run, synthesize) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, stdout=b"", stderr=b"")
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            image_path = directory / "bill.png"
            video_path = directory / "bill.mp4"

            create_narrated_video(image_path, "Narrate this bill.", video_path)

        synthesize.assert_called_once()
        self.assertEqual(synthesize.call_args.args[0], "Narrate this bill.")
        ffmpeg_call = run.call_args
        self.assertEqual(ffmpeg_call.args[0][0], "ffmpeg")
        self.assertIn(str(image_path), ffmpeg_call.args[0])
        self.assertIn(str(video_path), ffmpeg_call.args[0])
        self.assertIn("-vf", ffmpeg_call.args[0])
        self.assertIn("zoompan", ffmpeg_call.args[0][ffmpeg_call.args[0].index("-vf") + 1])

    @patch("util.debug_video._synthesize_speech")
    @patch("util.debug_video.subprocess.run")
    def test_inserts_one_second_of_silence_before_the_summary(self, run, synthesize) -> None:
        def run_command(command, **_kwargs):
            if command[0] == "ffmpeg" and str(command[-1]).endswith(".wav"):
                Path(command[-1]).write_bytes(b"RIFFfake-wave-data")
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

        run.side_effect = run_command
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            create_narrated_video(
                directory / "bill.png",
                f"H.R. 42. Example title.{NARRATION_PAUSE_MARKER}Creates an example program.",
                directory / "bill.mp4",
            )

        self.assertEqual([call.args[0] for call in synthesize.call_args_list], [
            "H.R. 42. Example title.",
            "Creates an example program.",
        ])
        ffmpeg_commands = [
            call.args[0] for call in run.call_args_list if call.args[0][0] == "ffmpeg"
        ]
        self.assertIn("anullsrc=r=24000:cl=mono", ffmpeg_commands[0])
        self.assertIn("concat=n=3:v=0:a=1", ffmpeg_commands[0][ffmpeg_commands[0].index("-filter_complex") + 1])


class KokoroSpeechTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = Mock()
        self.engine.get_voices.return_value = ["af_heart", "am_michael"]
        self.engine.create.return_value = ([0.1, -0.1], 24000)
        self.soundfile = Mock()
        self.soundfile.write.side_effect = lambda path, *_args, **_kwargs: Path(path).write_bytes(
            b"RIFFfake-wave-data"
        )
        self.engine_patch = patch("util.debug_video._kokoro", return_value=self.engine)
        self.module_patch = patch.dict("sys.modules", {"soundfile": self.soundfile})
        self.engine_patch.start()
        self.module_patch.start()
        self.addCleanup(self.engine_patch.stop)
        self.addCleanup(self.module_patch.stop)

    @patch("util.debug_video.KOKORO_VOICE", "am_michael")
    @patch("util.debug_video.KOKORO_SPEED", "0.95")
    def test_writes_pcm_audio_with_configured_voice_and_speed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "speech.wav"
            _synthesize_speech("This bill supports libraries.", output)
            self.assertTrue(output.is_file())
            self.soundfile.write.assert_called_once_with(
                str(output), [0.1, -0.1], 24000, subtype="PCM_16"
            )
        self.engine.create.assert_called_once_with(
            "This bill supports libraries.", voice="am_michael", speed=0.95, lang="en-us"
        )

    def test_rejects_invalid_speed_before_inference(self) -> None:
        for speed in ["fast", "nan", "inf", "0", "2.1"]:
            with self.subTest(speed=speed), patch("util.debug_video.KOKORO_SPEED", speed):
                with self.assertRaisesRegex(DebugVideoError, "KOKORO_SPEED"):
                    _synthesize_speech("Text", Path("unused.wav"))
        self.engine.create.assert_not_called()

    @patch("util.debug_video.KOKORO_VOICE", "unknown")
    def test_rejects_unknown_voice(self) -> None:
        with self.assertRaisesRegex(DebugVideoError, "Unknown KOKORO_VOICE"):
            _synthesize_speech("Text", Path("unused.wav"))
        self.engine.create.assert_not_called()

    @patch("util.debug_video.KOKORO_VOICE", "af_heart")
    def test_empty_audio_stops_video_generation(self) -> None:
        self.engine.create.return_value = ([], 24000)
        with self.assertRaisesRegex(DebugVideoError, "empty audio"):
            _synthesize_speech("Text", Path("unused.wav"))
        self.soundfile.write.assert_not_called()

    @patch("util.debug_video.KOKORO_VOICE", "af_heart")
    def test_inference_failure_becomes_video_error(self) -> None:
        self.engine.create.side_effect = RuntimeError("model failure")
        with self.assertRaisesRegex(DebugVideoError, "Kokoro speech synthesis failed: model failure"):
            _synthesize_speech("Text", Path("unused.wav"))


if __name__ == "__main__":
    unittest.main()
