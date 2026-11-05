"""Process lifecycle tests use real child processes, without provider or media keys."""
import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import tempfile
import unittest
from unittest.mock import patch

from app.media_process import (RenderCancelled, RenderControl, VideoProcessingError,
                               execute, media_operation)


class MediaProcessTests(unittest.TestCase):
    def child(self, script):
        return [sys.executable, "-c", script]

    def test_drains_both_pipes_and_bounds_error(self):
        script = "import sys; sys.stdout.write('x'*1000000); sys.stderr.write('y'*1000000); sys.exit(1)"
        with self.assertRaises(VideoProcessingError) as caught:
            execute(self.child(script), timeout=10)
        self.assertLess(len(str(caught.exception)), 4100)
        self.assertIn("yyyy", str(caught.exception))

    def test_timeout_reaps_child(self):
        started = time.monotonic()
        real_popen = subprocess.Popen
        children = []
        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child
        with patch("app.media_process.subprocess.Popen", side_effect=spawn):
            with self.assertRaisesRegex(VideoProcessingError, "time limit"):
                execute(self.child("import time; time.sleep(30)"), timeout=0.2)
        self.assertLess(time.monotonic() - started, 5)
        self.assertIsNotNone(children[0].poll())

    def test_cancel_is_local_to_operation(self):
        control = RenderControl()
        timer = threading.Timer(0.2, control.cancel)
        def cancelled():
            with media_operation(control):
                execute(self.child("import time; time.sleep(30)"))
        timer.start()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(cancelled)
                second = pool.submit(execute, self.child("print('independent')"))
                self.assertEqual(second.result(timeout=10).strip(), "independent")
                with self.assertRaises(RenderCancelled):
                    first.result(timeout=10)
        finally:
            timer.cancel()
            timer.join()

    def test_cancel_before_start_and_total_deadline(self):
        control = RenderControl()
        control.cancel()
        with patch("app.media_process.subprocess.Popen") as spawn:
            with self.assertRaises(RenderCancelled), media_operation(control):
                execute(self.child("print('no')"))
            spawn.assert_not_called()
        with self.assertRaisesRegex(VideoProcessingError, "time limit"), media_operation(RenderControl(timeout=0)):
            pass

    def test_missing_binary_has_readable_error(self):
        with self.assertRaisesRegex(VideoProcessingError, "Could not start"):
            execute(["vyro-nonexistent-tool-426.exe"])

    def test_failed_operation_removes_partial_output_only(self):
        from app.video_processor import _run
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "original.mp4")
            source.write_bytes(b"original")
            output = Path(directory, "partial.mp4")
            script = "import pathlib,sys,time; pathlib.Path(sys.argv[-1]).write_bytes(b'partial'); time.sleep(30)"
            with self.assertRaisesRegex(VideoProcessingError, "time limit"), media_operation(RenderControl(timeout=0.3)):
                _run([sys.executable, "-c", script, str(output)])
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), b"original")

    def test_invalid_probe_payloads_and_audio_only(self):
        from app.video_processor import probe_video_metadata
        cases = [({"streams": []}, "no video stream"),
                 ({"streams": [{"width": 10, "height": 10}], "format": {"duration": "nan"}}, "invalid values"),
                 ({"streams": [{}]}, "metadata")]
        for payload, message in cases:
            with self.subTest(payload=payload), patch("app.video_processor.execute", return_value=json.dumps(payload)):
                with self.assertRaisesRegex(VideoProcessingError, message):
                    probe_video_metadata("test.mp4")

    def test_fps_and_quality_reject_unknown_settings(self):
        from app.video_processor import output_fps, quality_crf
        self.assertEqual(quality_crf({"quality": "high"}), "18")
        with patch("app.video_processor.execute", return_value='{"streams":[{"avg_frame_rate":"30000/1001"}]}'):
            self.assertEqual(output_fps({"fps": "source"}, Path("x.mp4")), "30000/1001")
        for value in ("nan", "0", "240"):
            with self.assertRaises(VideoProcessingError):
                output_fps({"fps": value}, Path("x.mp4"))
        with self.assertRaises(VideoProcessingError):
            quality_crf({"quality": "unbounded"})


if __name__ == "__main__":
    unittest.main()
