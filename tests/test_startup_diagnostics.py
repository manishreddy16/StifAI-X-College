from __future__ import annotations

import io
import logging
import unittest
from contextlib import redirect_stderr
from unittest import mock

from api import startup_diagnostics


class StartupDiagnosticsTests(unittest.TestCase):
    def test_parses_linux_resident_memory(self):
        status = "Name:\tpython\nVmPeak:\t200000 kB\nVmRSS:\t12288 kB\n"
        self.assertEqual(startup_diagnostics._parse_proc_status_rss_mb(status), 12.0)
        self.assertIsNone(startup_diagnostics._parse_proc_status_rss_mb("Name:\tpython\n"))

    def test_phase_logs_begin_complete_elapsed_rss_and_counts(self):
        logger = logging.getLogger("test.startup_diagnostics")
        logger.setLevel(logging.WARNING)
        output = io.StringIO()
        with (
            mock.patch.object(startup_diagnostics, "process_rss_mb", return_value=42.5),
            redirect_stderr(output),
        ):
            with startup_diagnostics.startup_phase(
                logger, "retrieval.read_chunks"
            ) as details:
                details["chunks"] = 7

        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("status=BEGIN", lines[0])
        self.assertIn("rss_mb=42.5", lines[0])
        self.assertIn("status=COMPLETE", lines[1])
        self.assertIn("elapsed_s=", lines[1])
        self.assertIn("chunks=7", lines[1])

    def test_phase_logs_failed_when_application_logger_is_warning(self):
        logger = logging.getLogger("test.startup_diagnostics.warning")
        logger.setLevel(logging.WARNING)
        output = io.StringIO()
        with (
            mock.patch.object(startup_diagnostics, "process_rss_mb", return_value=18.0),
            redirect_stderr(output),
            self.assertRaisesRegex(RuntimeError, "boom"),
        ):
            with startup_diagnostics.startup_phase(logger, "retrieval.read_chunks"):
                raise RuntimeError("boom")

        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("status=BEGIN", lines[0])
        self.assertIn("status=FAILED", lines[1])
        self.assertIn("rss_mb=18.0", lines[1])


if __name__ == "__main__":
    unittest.main()
