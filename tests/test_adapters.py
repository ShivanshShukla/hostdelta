from contextlib import contextmanager
import json
import os
import unittest
from unittest.mock import patch

from hostdelta.adapters import HTTPClient, ProbeError, poll, bounded_poll


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, url, headers=None, body=None):
        self.calls.append((url, headers, body))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


class AdapterTests(unittest.TestCase):
    def test_openstack_credentials_only_to_configured_endpoints(self):
        cfg = {"name": "cloud", "type": "openstack", "url": "https://identity.test/v3", "services": {"nova": "https://nova.test/v2.1"}}
        client = FakeClient([({"token": {"catalog": [{"endpoints": [{"url": "https://untrusted.test"}]}]}}, {"X-Subject-Token": "secret-token"}), ({"versions": []}, {})])
        with patch.dict(os.environ, {"OS_APPLICATION_CREDENTIAL_ID": "id", "OS_APPLICATION_CREDENTIAL_SECRET": "secret-value"}):
            result = poll(cfg, client=client)
        self.assertEqual([c[0] for c in client.calls], ["https://identity.test/v3/auth/tokens", "https://nova.test/v2.1"])
        self.assertEqual(client.calls[1][1], {"X-Auth-Token": "secret-token"})
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("secret-value", json.dumps(result))
        self.assertNotIn("secret-token", json.dumps(result))

    def test_auth_failure_is_unknown_not_cloud_outage(self):
        cfg = {"name": "cloud", "type": "openstack", "url": "https://identity.test/v3", "services": {"nova": "https://nova.test/v2.1"}}
        with patch.dict(os.environ, {"OS_APPLICATION_CREDENTIAL_ID": "id", "OS_APPLICATION_CREDENTIAL_SECRET": "secret"}):
            result = poll(cfg, client=FakeClient([ProbeError("http_401")]))
        self.assertTrue(all(o["health"] == "unknown" for o in result["observations"]))

    def test_connection_failure_is_observer_unreachable(self):
        cfg = {"name": "cloud", "type": "openstack", "url": "https://identity.test/v3"}
        with patch.dict(os.environ, {"OS_APPLICATION_CREDENTIAL_ID": "id", "OS_APPLICATION_CREDENTIAL_SECRET": "secret"}):
            result = poll(cfg, client=FakeClient([ProbeError("connection_failed", "down")]))
        self.assertEqual(result["observations"][0]["health"], "down")

    def test_missing_credentials_do_not_make_request(self):
        client = FakeClient([])
        cfg = {"name": "cloud", "type": "openstack", "url": "https://identity.test", "credential_id_env": "HD_TEST_MISSING"}
        with patch.dict(os.environ, {}, clear=True):
            result = poll(cfg, client=client)
        self.assertEqual(client.calls, [])
        self.assertEqual(result["observations"][0]["health"], "unknown")

    def test_proxmox_inventory_and_quorum(self):
        cfg = {"name": "pve", "type": "proxmox", "url": "https://pve.test:8006"}
        responses = [({"data": [{"id": "qemu/100", "type": "qemu", "name": "worker", "status": "running", "node": "pve1"}]}, {}), ({"data": [{"type": "cluster", "quorate": 0}]}, {})]
        client = FakeClient(responses)
        with patch.dict(os.environ, {"PROXMOX_TOKEN_ID": "monitor@pve!hostdelta", "PROXMOX_TOKEN_SECRET": "secret"}):
            result = poll(cfg, previous={"resources": {}}, client=client)
        self.assertEqual(client.calls[0][1]["Authorization"], "PVEAPIToken=monitor@pve!hostdelta=secret")
        self.assertEqual(result["events"][0]["kind"], "inventory_changed")
        self.assertEqual(result["observations"][-1]["health"], "down")
        self.assertNotIn("secret", json.dumps(result))

    def test_worker_timeout_preserves_checkpoint(self):
        import subprocess
        cfg = {"name": "pve", "type": "proxmox", "url": "https://pve.test"}
        with patch("hostdelta.adapters.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 1)):
            result = bounded_poll(cfg, {"resources": {}})
        self.assertIsNone(result["checkpoint"])
        self.assertTrue(all(o["health"] == "unknown" for o in result["observations"]))


class HTTPIntegrationTests(unittest.TestCase):
    @contextmanager
    def server(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path, body))
                self.send_response(201)
                self.send_header("X-Subject-Token", "fixture-token")
                self.end_headers()
                self.wfile.write(b'{"token":{"catalog":[]}}')

            def do_GET(self):
                calls.append((self.path, self.headers.get("X-Auth-Token")))
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/should-not-receive-token")
                    self.end_headers()
                elif self.path == "/broken":
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(b'secret-debug-body')
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"versions":[]}')
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", calls
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_real_http_auth_probe_and_worker(self):
        with self.server() as (base, calls), patch.dict(os.environ, {"OS_APPLICATION_CREDENTIAL_ID": "fixture-id", "OS_APPLICATION_CREDENTIAL_SECRET": "fixture-secret"}):
            cfg = {"name": "fixture", "type": "openstack", "url": base + "/v3", "allow_http": True, "services": {"compute": base + "/compute"}}
            result = bounded_poll(cfg)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(calls[0][0], "/v3/auth/tokens")
        self.assertEqual(calls[1], ("/compute", "fixture-token"))
        self.assertNotIn("fixture-secret", json.dumps(result))

    def test_redirect_cannot_forward_token(self):
        with self.server() as (base, calls):
            with self.assertRaises(ProbeError) as failure:
                HTTPClient({"allow_http": True}).request(base + "/redirect", {"X-Auth-Token": "secret"})
        self.assertEqual(failure.exception.code, "http_302")
        self.assertEqual(len(calls), 1)

    def test_error_response_body_is_not_exposed(self):
        with self.server() as (base, calls):
            with self.assertRaises(ProbeError) as failure:
                HTTPClient({"allow_http": True}).request(base + "/broken")
        self.assertEqual(failure.exception.health, "down")
        self.assertNotIn("secret", str(failure.exception))


if __name__ == "__main__":
    unittest.main()
