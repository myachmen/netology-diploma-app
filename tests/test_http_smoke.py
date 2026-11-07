"""All HTTP attempts are mocked: no live URL requests or sleeps."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from ci.http_smoke import probe

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'ci/VERSION').read_text().strip()
HTML = (ROOT / 'index.html').read_text()


class HttpSmoke(unittest.TestCase):
    def execute(self, replies, body=HTML):
        runner = Mock(side_effect=replies)
        pause = Mock()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'http-body.html').write_text(body)
            probe('https://example.invalid/', VERSION, root, run=runner, sleep=pause)
        return runner, pause

    def test_real_body_contract_after_transient_timeout_and_status(self):
        runner, pause = self.execute([subprocess.CompletedProcess([], 28, '', 'private-tripwire'),
                                     subprocess.CompletedProcess([], 0, '503', ''),
                                     subprocess.CompletedProcess([], 0, '200', '')])
        self.assertEqual(runner.call_count, 3)
        self.assertEqual(pause.call_count, 2)
        args, kwargs = runner.call_args
        self.assertIn('--max-time', args[0])
        self.assertNotIn('--location', args[0])
        self.assertEqual(kwargs['timeout'], 17)
        self.assertTrue(kwargs['capture_output'])

    def test_http_200_wrong_version_never_passes(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, '200', 'private-tripwire'))
        pause = Mock()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'http-body.html').write_text(HTML.replace('Version: ' + VERSION, 'Version: 9.9.9'))
            with self.assertRaisesRegex(ValueError, 'EXHAUSTED'):
                probe('https://example.invalid/', VERSION, root, run=runner, sleep=pause)
        self.assertEqual(runner.call_count, 5)
        self.assertEqual(pause.call_count, 4)

    def test_redirect_timeout_and_transport_exhaust_bounded_budget(self):
        for reply in (subprocess.CompletedProcess([], 0, '302', ''),
                      subprocess.CompletedProcess([], 7, '', 'private-tripwire'),
                      subprocess.TimeoutExpired('curl', 17)):
            with self.subTest(reply=type(reply).__name__):
                runner = Mock(side_effect=[reply] * 5)
                pause = Mock()
                with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
                    probe('https://example.invalid/', VERSION, Path(d), run=runner, sleep=pause)
                self.assertEqual(runner.call_count, 5)
                self.assertEqual(pause.call_count, 4)
