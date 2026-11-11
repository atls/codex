import os
import select
import subprocess
import sys
import unittest

from fixtures.process import native_process


class NativeProcessTests(unittest.TestCase):
    def test_fixture_closes_descendants_after_the_launcher_exits(self):
        command = [
            sys.executable,
            "-c",
            "import subprocess,sys; subprocess.Popen([sys.executable, '-c', "
            "\"import time; print('ready', flush=True); time.sleep(30)\"])",
        ]
        with native_process(command, stdout=subprocess.PIPE) as process:
            self.assertEqual(process.stdout.readline(), b"ready\n")
            process.wait(timeout=5)
            output = os.dup(process.stdout.fileno())
        try:
            self.assertTrue(select.select([output], [], [], 5)[0])
            self.assertEqual(os.read(output, 1), b"")
        finally:
            os.close(output)
