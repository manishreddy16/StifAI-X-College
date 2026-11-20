from __future__ import annotations

import logging
import unittest
from unittest import mock

from api import startup_diagnostics


class StartupDiagnosticsTests(unittest.TestCase):
    def test_parses_linux_resident_memory(self):
        status = "Name:\tpython\nVmPeak:\t200000 kB\nVmRSS:\t12288 kB\n"
        self.assertEqual(startup_diagnostics._parse_proc_status_rss_mb(status), 12.0)
        self.assertIsNone(startup_diagnostics._parse_proc_status_rss_mb("Name:\tpython\n"))

    def test_phase_logs_begin_complete_elapsed_rss_and_counts(self):
        logger = logging.getLogger("test.startup_diagnostics")
        with (
            mock.patch.object(startup_diagnostics, "process_rss_mb", return_value=42.5),
            self.assertLogs(logger, level="INFO") as captured,
        ):
            with startup_diagnostics.startup_phase(
                logger, "retrieval.read_chunks"
            ) as details:
                details["chunks"] = 7

        self.assertIn("status=BEGIN", captured.output[0])
        self.assertIn("rss_mb=42.5", captured.output[0])
        self.assertIn("status=COMPLETE", captured.output[1])
        self.assertIn("elapsed_s=", captured.output[1])
        self.assertIn("chunks=7", captured.output[1])


if __name__ == "__main__":
    unittest.main()
