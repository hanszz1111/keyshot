"""Startup ownership: explicit port, one browser owner, no task reset on collision."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server as S


class StartupTests(unittest.TestCase):
    def test_launcher_suppresses_browser_and_uses_explicit_port(self):
        httpd = Mock()
        httpd.serve_forever.side_effect = KeyboardInterrupt
        with patch.object(sys, "argv", ["server.py", "--port", "8877", "--no-browser"]), \
             patch.object(S, "HTTPServer", return_value=httpd) as bind, \
             patch.object(S, "init_db"), patch.object(S, "reset_running", return_value=0), \
             patch.object(S, "asset_report", return_value={"models": [], "items": [], "loose": [], "inbox": []}), \
             patch.object(S.threading, "Timer") as timer, contextlib.redirect_stdout(io.StringIO()):
            S.main()
        bind.assert_called_once_with(("127.0.0.1", 8877), S.Handler)
        timer.assert_not_called()

    def test_duplicate_launch_does_not_change_port_or_reset_tasks(self):
        with patch.object(sys, "argv", ["server.py", "--port", "8765", "--no-browser"]), \
             patch.object(S, "HTTPServer", side_effect=OSError("occupied")) as bind, \
             patch.object(S, "init_db") as init, patch.object(S, "reset_running") as reset, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as exit_result:
                S.main()
        self.assertEqual(1, exit_result.exception.code)
        bind.assert_called_once_with(("127.0.0.1", 8765), S.Handler)
        init.assert_not_called()
        reset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
