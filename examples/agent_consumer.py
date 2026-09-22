#!/usr/bin/env python3
"""A minimal agent polling cycle: inspect → process → acknowledge, never auto-remediate."""
import json
import subprocess

consumer = "health-agent"
result = subprocess.run(
    ["hostdelta", "brief", "--consumer", consumer, "--json", "--fail-on", "warning", "--require-coverage"],
    capture_output=True, text=True, check=False,
)
if result.returncode not in (0, 2, 3):
    raise SystemExit(result.stderr)
report = json.loads(result.stdout)
if report["schema_version"] != 1:
    raise SystemExit("Unsupported HostDelta report schema")

# All host/log fields are UNTRUSTED DATA, including messages that resemble instructions.
# In a real agent, persist findings to your own task system before acknowledging.
print(json.dumps({"findings": report["findings"], "coverage": report["coverage"]}, indent=2))
if result.returncode == 3:
    raise SystemExit("Detected collection gap; leaving this consumer cursor unchanged.")

subprocess.run([
    "hostdelta", "ack", "--consumer", consumer, "--until", report["window"]["until"], "--json"
], check=True)
