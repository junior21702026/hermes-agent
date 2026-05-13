from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins.youtube_agent_watch.transcripts import fetch_auto_subs_fallback, fetch_transcript, fetch_whisper_fallback, purge_transcript


class TranscriptFallbackTests(unittest.TestCase):
    def test_yt_dlp_uses_cookie_file_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            cookie_file = Path(td) / "cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            seen = {}

            def fake_run(cmd, **kwargs):
                seen["cmd"] = cmd

                class Proc:
                    returncode = 1
                    stderr = "blocked"

                return Proc()

            config = {"ingest": {"yt_dlp_path": "yt-dlp", "cookie_file": str(cookie_file), "yt_dlp_args": ["--impersonate", ""]}}
            with patch("plugins.youtube_agent_watch.transcripts.subprocess.run", fake_run):
                fetch_auto_subs_fallback("abc123", config, Path(td), logger=lambda *_: None)

            self.assertIn("--cookies", seen["cmd"])
            self.assertIn(str(cookie_file), seen["cmd"])
            self.assertIn("--impersonate", seen["cmd"])
            self.assertIn("--skip-download", seen["cmd"])

    def test_yt_dlp_uses_browser_cookies_when_cookie_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            seen = {}

            def fake_run(cmd, **kwargs):
                seen["cmd"] = cmd

                class Proc:
                    returncode = 1
                    stderr = "blocked"

                return Proc()

            config = {"ingest": {"yt_dlp_path": "yt-dlp", "cookie_file": str(Path(td) / "missing.txt"), "cookies_from_browser": "chrome"}}
            with patch("plugins.youtube_agent_watch.transcripts.subprocess.run", fake_run):
                fetch_auto_subs_fallback("abc123", config, Path(td), logger=lambda *_: None)

            self.assertIn("--cookies-from-browser", seen["cmd"])
            self.assertIn("chrome", seen["cmd"])
            self.assertNotIn("--cookies", seen["cmd"])


class WhisperFallbackTests(unittest.TestCase):
    def _config(self, **whisper_overrides):
        whisper = {
            "enabled": True,
            "binary": "/tmp/fake-whisper",
            "model": "small.en",
            "language": "en",
            "output_format": "txt",
            "audio_format": "m4a",
            "audio_quality": "0",
            "ffmpeg_location": "/opt/homebrew/bin",
            "audio_download_timeout_seconds": 300,
            "whisper_timeout_seconds": 1800,
            "delete_audio_after": True,
            "min_chars": 200,
        }
        whisper.update(whisper_overrides)
        return {
            "ingest": {
                "yt_dlp_path": "yt-dlp",
                "yt_dlp_args": ["--impersonate", ""],
                "transcript": {"languages": ["en"], "whisper_fallback": whisper},
            }
        }

    def test_fetch_transcript_skips_whisper_when_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            config = self._config(enabled=False)
            fake_youtube_transcript_api = types.SimpleNamespace(YouTubeTranscriptApi=lambda: (_ for _ in ()).throw(Exception("blocked")))
            with patch.dict("sys.modules", {"youtube_transcript_api": fake_youtube_transcript_api}), \
                 patch("plugins.youtube_agent_watch.transcripts.fetch_auto_subs_fallback", return_value=("", "none")), \
                 patch("plugins.youtube_agent_watch.transcripts.fetch_whisper_fallback") as whisper:
                self.assertEqual(fetch_transcript("abc123", config, Path(td), logger=lambda *_: None), ("", "none"))
                whisper.assert_not_called()

    def test_fetch_transcript_invokes_whisper_after_subtitle_none(self):
        with tempfile.TemporaryDirectory() as td:
            config = self._config(enabled=True)
            fake_youtube_transcript_api = types.SimpleNamespace(YouTubeTranscriptApi=lambda: (_ for _ in ()).throw(Exception("blocked")))
            with patch.dict("sys.modules", {"youtube_transcript_api": fake_youtube_transcript_api}), \
                 patch("plugins.youtube_agent_watch.transcripts.fetch_auto_subs_fallback", return_value=("", "none")), \
                 patch("plugins.youtube_agent_watch.transcripts.fetch_whisper_fallback", return_value=("hello world", "whisper-fallback")) as whisper:
                self.assertEqual(fetch_transcript("abc123", config, Path(td), logger=lambda *_: None), ("hello world", "whisper-fallback"))
                whisper.assert_called_once()

    def test_whisper_binary_missing_graceful_none(self):
        with tempfile.TemporaryDirectory() as td:
            logs = []
            config = self._config(binary=str(Path(td) / "missing-whisper"))
            with patch("plugins.youtube_agent_watch.transcripts.subprocess.run", side_effect=AssertionError("should not run")):
                self.assertEqual(fetch_whisper_fallback("abc123", config, Path(td), logger=logs.append), ("", "none"))
            self.assertTrue(any("whisper binary not found" in msg for msg in logs))

    def test_yt_dlp_audio_command_uses_cookie_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            whisper_bin = root / "whisper"
            whisper_bin.write_text("", encoding="utf-8")
            cookie_file = root / "cookies.txt"
            cookie_file.write_text("# cookie\n", encoding="utf-8")
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                class Proc:
                    returncode = 1
                    stderr = "blocked"
                (root / "abc123.m4a").write_bytes(b"partial audio")
                return Proc()

            config = self._config(binary=str(whisper_bin))
            config["ingest"]["cookie_file"] = str(cookie_file)
            with patch("plugins.youtube_agent_watch.transcripts.subprocess.run", fake_run):
                self.assertEqual(fetch_whisper_fallback("abc123", config, root, logger=lambda *_: None), ("", "none"))
            self.assertEqual(len(calls), 1)
            cmd = calls[0]
            self.assertIn("-x", cmd)
            self.assertIn("--audio-format", cmd)
            self.assertIn("m4a", cmd)
            self.assertIn("--ffmpeg-location", cmd)
            self.assertIn("--cookies", cmd)
            self.assertIn(str(cookie_file), cmd)
            self.assertIn("https://www.youtube.com/watch?v=abc123", cmd)
            self.assertFalse((root / "abc123.m4a").exists())

    def test_yt_dlp_audio_uses_browser_cookies_when_cookie_file_absent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            whisper_bin = root / "whisper"
            whisper_bin.write_text("", encoding="utf-8")
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                class Proc:
                    returncode = 1
                    stderr = "blocked"
                return Proc()

            config = self._config(binary=str(whisper_bin))
            config["ingest"]["cookie_file"] = str(root / "missing.txt")
            config["ingest"]["cookies_from_browser"] = "chrome"
            with patch("plugins.youtube_agent_watch.transcripts.subprocess.run", fake_run):
                fetch_whisper_fallback("abc123", config, root, logger=lambda *_: None)
            cmd = calls[0]
            self.assertIn("--cookies-from-browser", cmd)
            self.assertIn("chrome", cmd)
            self.assertNotIn("--cookies", cmd)

    def test_successful_whisper_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            whisper_bin = root / "whisper"
            whisper_bin.write_text("", encoding="utf-8")
            text = "lorem ipsum " * 150

            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                class Proc:
                    returncode = 0
                    stderr = ""
                if "-x" in cmd:
                    (root / "abc123.m4a").write_bytes(b"audio")
                else:
                    (root / "abc123.txt").write_text(text, encoding="utf-8")
                return Proc()

            with patch("plugins.youtube_agent_watch.transcripts.subprocess.run", fake_run):
                result = fetch_whisper_fallback("abc123", self._config(binary=str(whisper_bin)), root, logger=lambda *_: None)
            self.assertEqual(result, (text, "whisper-fallback"))
            self.assertEqual(len(calls), 2)
            whisper_cmd = calls[1]
            self.assertEqual(whisper_cmd[:2], [str(whisper_bin), str(root / "abc123.m4a")])
            self.assertIn("--model", whisper_cmd)
            self.assertIn("small.en", whisper_cmd)
            self.assertIn("--language", whisper_cmd)
            self.assertIn("en", whisper_cmd)
            self.assertIn("--output_format", whisper_cmd)
            self.assertIn("txt", whisper_cmd)
            self.assertIn("--output_dir", whisper_cmd)
            self.assertIn(str(root), whisper_cmd)
            self.assertIn("--fp16", whisper_cmd)
            self.assertIn("False", whisper_cmd)
            self.assertEqual((root / "abc123.txt").read_text(encoding="utf-8"), text)
            self.assertFalse((root / "abc123.m4a").exists())

    def test_whisper_nonzero_returns_none_and_cleans_audio(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            whisper_bin = root / "whisper"
            whisper_bin.write_text("", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                class Proc:
                    stderr = "failed"
                if "-x" in cmd:
                    (root / "abc123.m4a").write_bytes(b"audio")
                    Proc.returncode = 0
                else:
                    Proc.returncode = 1
                return Proc()

            with patch("plugins.youtube_agent_watch.transcripts.subprocess.run", fake_run):
                self.assertEqual(fetch_whisper_fallback("abc123", self._config(binary=str(whisper_bin)), root, logger=lambda *_: None), ("", "none"))
            self.assertFalse((root / "abc123.m4a").exists())

    def test_whisper_output_below_min_chars_returns_none_and_removes_txt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            whisper_bin = root / "whisper"
            whisper_bin.write_text("", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                class Proc:
                    returncode = 0
                    stderr = ""
                if "-x" in cmd:
                    (root / "abc123.m4a").write_bytes(b"audio")
                else:
                    (root / "abc123.txt").write_text("too short", encoding="utf-8")
                return Proc()

            with patch("plugins.youtube_agent_watch.transcripts.subprocess.run", fake_run):
                self.assertEqual(fetch_whisper_fallback("abc123", self._config(binary=str(whisper_bin), min_chars=200), root, logger=lambda *_: None), ("", "none"))
            self.assertFalse((root / "abc123.txt").exists())

    def test_whisper_timeout_returns_none_without_escaping(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            whisper_bin = root / "whisper"
            whisper_bin.write_text("", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                if "-x" in cmd:
                    (root / "abc123.m4a").write_bytes(b"audio")
                    class Proc:
                        returncode = 0
                        stderr = ""
                    return Proc()
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1))

            import subprocess
            with patch("plugins.youtube_agent_watch.transcripts.subprocess.run", fake_run):
                self.assertEqual(fetch_whisper_fallback("abc123", self._config(binary=str(whisper_bin)), root, logger=lambda *_: None), ("", "none"))

    def test_logger_redacts_cookie_path_and_cookie_headers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            whisper_bin = root / "whisper"
            whisper_bin.write_text("", encoding="utf-8")
            cookie_file = root / "sentinel-secret-cookies.txt"
            cookie_file.write_text("secret", encoding="utf-8")
            logs = []

            def fake_run(cmd, **kwargs):
                class Proc:
                    returncode = 1
                    stderr = f"oops {cookie_file}\nCookie: session=secret\nSet-Cookie: x=y\n"
                return Proc()

            config = self._config(binary=str(whisper_bin))
            config["ingest"]["cookie_file"] = str(cookie_file)
            with patch("plugins.youtube_agent_watch.transcripts.subprocess.run", fake_run):
                fetch_whisper_fallback("abc123", config, root, logger=logs.append)
            joined = "\n".join(logs)
            self.assertNotIn("sentinel-secret", joined)
            self.assertNotIn("Cookie:", joined)
            self.assertNotIn("Set-Cookie:", joined)
            self.assertIn("<cookie_file>", joined)

    def test_purge_transcript_removes_audio_and_transcript_siblings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for suffix in [".m4a", ".txt", ".vtt"]:
                (root / f"abc123{suffix}").write_text("x", encoding="utf-8")
            purge_transcript("abc123", root, retain=False)
            self.assertFalse(any((root / f"abc123{suffix}").exists() for suffix in [".m4a", ".txt", ".vtt"]))


if __name__ == "__main__":
    unittest.main()
