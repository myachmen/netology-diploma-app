"""Offline only: kubectl, PID state, SSH log reading and sleeps are all mocked."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from ci.api_access import COMMAND, classify, poll, read_tail

TRIPWIRE = 'PRIVATE_TOKEN_KEY_CERT_ENDPOINT_USER_TRIPWIRE'


class ApiAccess(unittest.TestCase):
    def check_failure(self, api='', ssh='', running=True, expected='API_UNKNOWN'):
        runner = Mock(return_value=subprocess.CompletedProcess([], 1, None, api + TRIPWIRE))
        logger, pause = Mock(), Mock()
        result = poll(123, Path('private-path-' + TRIPWIRE), run=runner,
                      is_alive=lambda _: running, sleep=pause,
                      read_error=lambda _: ssh + TRIPWIRE, emit=logger)
        self.assertFalse(result)
        output = '\n'.join(c.args[0] for c in logger.call_args_list)
        self.assertIn('category=' + expected, output)
        self.assertNotIn(TRIPWIRE, output)
        self.assertEqual(runner.call_count, 1 if running else 0)
        pause.assert_not_called()
        return output

    def test_terminal_ssh_errors_never_get_or_respawn(self):
        for error, category in [
            ('Host key verification failed', 'SSH_HOST_KEY_FAILURE'),
            ('REMOTE HOST IDENTIFICATION HAS CHANGED', 'SSH_HOST_KEY_FAILURE'),
            ('Permission denied (publickey)', 'SSH_AUTH_FAILURE'),
            ('Load key /private/key: error in libcrypto', 'SSH_AUTH_FAILURE'),
            ('bind: Address already in use', 'SSH_LOCAL_BIND_FAILURE'),
            ('channel 2: open failed: administratively prohibited', 'SSH_FORWARD_FAILURE'),
            ('connect: Connection timed out', 'SSH_CONNECT_TIMEOUT'),
            ('connect: No route to host', 'SSH_NETWORK_FAILURE'),
            ('unexpected private server error', 'SSH_PROCESS_EXITED')]:
            with self.subTest(category=category):
                self.check_failure(ssh=error, running=False, expected=category)

    def test_tls_auth_rbac_notfound_and_unknown_are_redacted_terminal(self):
        for error, category in [
            ('Unable to connect: x509: certificate signed by unknown authority', 'API_TLS_FAILURE'),
            ('tls: failed to verify certificate: wrong private SAN', 'API_TLS_FAILURE'),
            ('error: You must be logged in to the server (Unauthorized)', 'API_AUTH_401'),
            ('the server has asked for the client to provide credentials', 'API_AUTH_401'),
            ('Error from server (Forbidden): deployments.apps is forbidden: User private', 'API_RBAC_403'),
            ('Error from server (NotFound): deployments.apps "diploma-app" not found', 'API_NOT_FOUND_404'),
            ('unrecognized private error', 'API_UNKNOWN')]:
            with self.subTest(category=category):
                self.check_failure(api=error, expected=category)

    def test_local_forwarding_error_while_ssh_alive_is_visible(self):
        self.check_failure(ssh='channel 2: open failed: connect failed: Connection refused',
                           expected='SSH_FORWARD_FAILURE')

    def test_api_response_outranks_old_forward_error_not_a_root_cause_claim(self):
        self.assertEqual(classify('error (Forbidden)', 'open failed: connect failed', True), 'API_RBAC_403')
        self.assertEqual(classify('error (Unauthorized)', 'open failed: connect failed', True), 'API_AUTH_401')

    def test_transient_failure_then_success_uses_only_the_fixed_deployment_get(self):
        runner = Mock(side_effect=[subprocess.CompletedProcess([], 1, None, 'connection refused'),
                                   subprocess.CompletedProcess([], 0, None, '')])
        pause, logger = Mock(), Mock()
        self.assertTrue(poll(123, Path('private'), run=runner, is_alive=lambda _: True,
                             sleep=pause, read_error=lambda _: '', emit=logger))
        self.assertEqual(runner.call_count, 2)
        pause.assert_called_once_with(1)
        for call in runner.call_args_list:
            self.assertEqual(call.args, (COMMAND,))
            self.assertEqual(call.kwargs['timeout'], 7)
            self.assertEqual(call.kwargs['stdout'], subprocess.DEVNULL)
            self.assertEqual(call.kwargs['stderr'], subprocess.PIPE)
            self.assertNotIn('shell', call.kwargs)
        self.assertIn('DEPLOYMENT_GET_OK', logger.call_args.args[0])

    def test_timeout_and_connection_failures_stop_at_ten_with_nine_delays(self):
        for outcome in [subprocess.TimeoutExpired(COMMAND, 7, stderr=TRIPWIRE),
                        subprocess.CompletedProcess([], 1, None, 'i/o timeout ' + TRIPWIRE),
                        subprocess.CompletedProcess([], 1, None, 'connection refused ' + TRIPWIRE)]:
            runner = Mock(side_effect=[outcome] * 10)
            pause, logger = Mock(), Mock()
            with self.subTest(outcome=type(outcome).__name__):
                self.assertFalse(poll(123, Path('private'), run=runner, is_alive=lambda _: True,
                                      sleep=pause, read_error=lambda _: '', emit=logger))
                self.assertEqual(runner.call_count, 10)
                self.assertEqual(pause.call_count, 9)
                text = '\n'.join(c.args[0] for c in logger.call_args_list)
                self.assertNotIn(TRIPWIRE, text)
                self.assertIn('POLL_BUDGET_EXHAUSTED', text)

    def test_ssh_exit_during_get_cannot_report_success(self):
        logger = Mock()
        self.assertFalse(poll(123, Path('private'), is_alive=Mock(side_effect=[True, False]),
                              run=Mock(return_value=subprocess.CompletedProcess([], 0, None, '')),
                              sleep=Mock(), read_error=lambda _: '', emit=logger))
        self.assertIn('SSH_PROCESS_EXITED', logger.call_args.args[0])

    def test_tool_error_cannot_leak_exception_or_retry(self):
        runner, logger, pause = Mock(side_effect=OSError(TRIPWIRE)), Mock(), Mock()
        self.assertFalse(poll(123, Path('private'), run=runner, is_alive=lambda _: True,
                              sleep=pause, read_error=lambda _: '', emit=logger))
        self.assertIn('LOCAL_TOOL_ERROR', logger.call_args.args[0])
        self.assertNotIn(TRIPWIRE, str(logger.call_args_list))
        pause.assert_not_called()

    def test_ssh_tail_is_bounded_missing_file_safe(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'private'
            self.assertEqual(read_tail(p), '')
            p.write_bytes(b'x' * 100000 + b'Host key verification failed')
            tail = read_tail(p)
            self.assertEqual(len(tail), 65536)
            self.assertTrue(tail.endswith('Host key verification failed'))

    def test_nonzero_helper_propagates_safe_stage_and_stops_before_patch(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / 'ci/deploy.sh').read_text()
        trap_line = next(l for l in script.splitlines() if l.endswith("' ERR"))
        # Invalid PID is local-only: no os.kill, kubectl or network operation.
        command = ('set -euo pipefail\nstage=ssh_api_access\n' + trap_line +
                   '\npython3 -m ci.api_access --tunnel-pid -1 --ssh-error private\n' +
                   'echo MUTATION_MUST_NOT_BE_REACHED\n')
        run = subprocess.run(['bash', '-c', command], cwd=root, capture_output=True,
                             text=True, timeout=5)
        self.assertEqual(run.returncode, 1)
        self.assertIn('category=LOCAL_DIAGNOSTIC_ERROR', run.stdout)
        self.assertIn('CD FAIL stage=ssh_api_access exit=1', run.stderr)
        self.assertNotIn('MUTATION_MUST_NOT_BE_REACHED', run.stdout)
        self.assertNotIn('Traceback', run.stdout + run.stderr)

    def test_integration_gate_stays_before_any_mutation_and_preserves_cleanup(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / 'ci/deploy.sh').read_text()
        self.assertIn('python3 -m ci.api_access --tunnel-pid "$tunnel_pid" --ssh-error "$work_dir/ssh-error"', script)
        self.assertLess(script.index('python3 -m ci.api_access'), script.index('stage=baseline'))
        self.assertLess(script.index('stage=baseline'), script.index('stage=guarded_patch'))
        self.assertIn('trap cleanup EXIT', script)
        self.assertIn('trap \'rc=$?', script)
        self.assertNotIn('cat "$work_dir/ssh-error"', script)
        self.assertNotIn('ready=false', script)
