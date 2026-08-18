from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from util.debug_video import NARRATION_PAUSE_MARKER, create_narrated_video


class DebugVideoTests(unittest.TestCase):
    @patch("util.debug_video.subprocess.run")
    def test_uses_local_tts_then_renders_an_animated_portrait_video(self, run) -> None:
        def synthesize_wav(command, **_kwargs):
            audio_path = Path(command[command.index("-f") + 1])
            audio_path.write_bytes(b"RIFFfake-wave-data")
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

        def run_command(command, **kwargs):
            if command[:3] == [sys.executable, "-m", "piper"]:
                return synthesize_wav(command, **kwargs)
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

        run.side_effect = run_command
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            image_path = directory / "bill.png"
            video_path = directory / "bill.mp4"

            create_narrated_video(image_path, "Narrate this bill.", video_path)

        tts_call, ffmpeg_call = run.call_args_list
        self.assertEqual(tts_call.args[0][1:3], ["-m", "piper"])
        self.assertIn("-f", tts_call.args[0])
        self.assertEqual(tts_call.args[0][-1], "Narrate this bill.")
        self.assertEqual(ffmpeg_call.args[0][0], "ffmpeg")
        self.assertIn(str(image_path), ffmpeg_call.args[0])
        self.assertIn(str(video_path), ffmpeg_call.args[0])
        self.assertIn("-vf", ffmpeg_call.args[0])
        self.assertIn("zoompan", ffmpeg_call.args[0][ffmpeg_call.args[0].index("-vf") + 1])

    @patch("util.debug_video.subprocess.run")
    def test_inserts_one_second_of_silence_before_the_summary(self, run) -> None:
        def run_command(command, **_kwargs):
            if command[:3] == [sys.executable, "-m", "piper"]:
                Path(command[command.index("-f") + 1]).write_bytes(b"RIFFfake-wave-data")
            elif command[0] == "ffmpeg" and str(command[-1]).endswith(".wav"):
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

        tts_commands = [
            call.args[0]
            for call in run.call_args_list
            if call.args[0][:3] == [sys.executable, "-m", "piper"]
        ]
        self.assertEqual([command[-1] for command in tts_commands], [
            "H.R. 42. Example title.",
            "Creates an example program.",
        ])
        ffmpeg_commands = [
            call.args[0] for call in run.call_args_list if call.args[0][0] == "ffmpeg"
        ]
        self.assertIn("anullsrc=r=24000:cl=mono", ffmpeg_commands[0])
        self.assertIn("concat=n=3:v=0:a=1", ffmpeg_commands[0][ffmpeg_commands[0].index("-filter_complex") + 1])


if __name__ == "__main__":
    unittest.main()
