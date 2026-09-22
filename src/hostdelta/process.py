"""Subprocess capture with time and output budgets, without unbounded pipe buffers."""

import os
import subprocess
import tempfile
import time


def bounded_run(args, timeout=8, max_bytes=8 * 1024 * 1024, env=None):
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(args, stdout=stdout, stderr=stderr, env=env)
        reason = None
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if os.fstat(stdout.fileno()).st_size > max_bytes or os.fstat(stderr.fileno()).st_size > 65536:
                    reason = "output"
                    break
                if time.monotonic() >= deadline:
                    reason = "timeout"
                    break
                try:
                    process.wait(timeout=0.02)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
        stdout.seek(0)
        stderr.seek(0)
        output = stdout.read(max_bytes + 1)
        errors = stderr.read(65536).decode("utf-8", errors="replace")
        if reason == "timeout":
            return subprocess.CompletedProcess(args, 124, "", "Collector subprocess exceeded its time budget")
        if reason == "output" or len(output) > max_bytes:
            output = output[:max_bytes].rsplit(b"\n", 1)[0]
            errors += "\nCollector output limit reached; some records were omitted."
        return subprocess.CompletedProcess(args, 0 if reason == "output" else process.returncode,
                                           output.decode("utf-8", errors="replace"), errors)
