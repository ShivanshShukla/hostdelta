"""Synthetic, deterministic incident data; never reads or writes the real host."""

from .brief import build


def report():
    start, end = "2026-09-18T04:00:00.000000+00:00", "2026-09-21T12:00:00.000000+00:00"
    old = {"at": start, "host": "demo-compute-1 (synthetic data)", "domains": {
        "packages": {"status": "ok", "data": {"openvswitch-switch": "3.3.0-1", "libssl3": "3.0.13-0"}},
        "services": {"status": "ok", "data": {"vm-save.service": {"active": "inactive", "sub": "dead"}}},
        "files": {"status": "ok", "scope": ["/etc/systemd/system"], "data": {}},
        "system": {"status": "ok", "data": {"reboot_required": False}}}}
    import copy
    new = copy.deepcopy(old)
    new["at"] = end
    new["domains"]["packages"]["data"] = {"openvswitch-switch": "3.3.0-2", "libssl3": "3.0.13-1"}
    new["domains"]["services"]["data"]["vm-save.service"] = {"active": "failed", "sub": "failed"}
    new["domains"]["system"]["data"]["reboot_required"] = True
    new["domains"]["files"]["data"]["/etc/systemd/system/vm-save.timer.d/override.conf"] = {"sha256": "example-hash"}
    def event(second, category, kind, severity, summary):
        return {"at": f"2026-09-21T11:13:{second:02}.000000+00:00", "category": category, "kind": kind,
                "severity": severity, "summary": summary, "source": "synthetic", "ref": f"demo:{second}", "unit": ""}
    events = [event(0, "system", "auto_update_activity", "info", "Unattended-upgrades emitted a log record"),
              event(8, "services", "service_lifecycle", "info", "Stopped Open vSwitch forwarding daemon."),
              event(14, "network", "network_warning", "warning", "br-ex: Lost carrier"),
              event(30, "services", "service_failure", "critical", "vm-save.service: Failed with result 'exit-code'."),
              event(45, "agents", "agent_failure", "critical", "backup-agent: OpenStack endpoint health check failed"),
              event(59, "access", "ssh_success", "info", "SSH authentication accepted")]
    requests = {"status": "ok", "total": 1427, "errors_5xx": 18, "slow_requests": 23,
                "status_codes": {"200": 1394, "404": 15, "503": 18},
                "top_paths": [("GET /v3/auth/tokens", 980), ("GET /health", 447)],
                "top_clients": [("192.0.2.10", 1000), ("198.51.100.4", 427)], "warnings": [],
                "files_read": 1, "first_request": start, "last_request": end}
    return build(new, old, {"events": events, "status": "ok", "warnings": []}, requests, start, end,
                 notes=["DEMO: synthetic events and counts. No real host data was collected.",
                        "HTTP counts describe retained access logs, not every network connection."])
