# Live deployment validation

This runbook is intended for the OpenStack/Proxmox environment where HostDelta will
actually operate. The default verifier reads host/cloud state and writes only its
own state and a result file. It never stops a service, edits a firewall, or creates,
restarts or deletes a VM. Fault injection is a separate, explicitly isolated exercise.

## 1. Prepare the environment

Use a disposable validation state directory under the eventual operating identity.
Do not point acceptance tests at an active production collector's directory.

```bash
python3 --version                    # 3.10 or newer
./bin/hostdelta --version            # Expected: 0.2.0
PYTHONPATH=src python3 -m unittest discover -s tests -v
export HOSTDELTA_STATE_DIR="$HOME/.local/state/hostdelta-acceptance"
./bin/hostdelta init --json
./bin/hostdelta doctor --json
```

The test suite binds temporary localhost ports. Review test failures rather than
skipping them silently. `doctor` checks platform/command readiness; it does not prove
log access. The subsequent collection results test actual read permissions.

Check available tools and permissions: systemd/journalctl, iproute2, dpkg-query or
rpm, read access to selected logs, and outbound access to your configured API URLs.
`conntrack` and CAP_NET_ADMIN are needed only for the optional subscription test.

## 2. Configure OpenStack

Copy `examples/openstack.json` to a private validation configuration. Replace the
identity/compute/image URLs with actual reachable JSON API endpoints. Keep only
services that you intend to test. Configure a private CA with `ca_file` if needed.
Do not disable certificate verification; use `allow_http: true` only if your lab
explicitly uses HTTP and permits credentials over that network.

Use an application credential created through the cloud's normal process with
minimum permissions for the selected requests. No administrative role is needed
merely to prove a version/root endpoint is reachable if the deployment exposes it.
Authorization policies vary, so confirm with your cloud administrator.

```bash
read -r -p 'Application credential ID: ' OS_APPLICATION_CREDENTIAL_ID
read -r -s -p 'Application credential secret: ' OS_APPLICATION_CREDENTIAL_SECRET
printf '\n'
export OS_APPLICATION_CREDENTIAL_ID OS_APPLICATION_CREDENTIAL_SECRET
./bin/hostdelta config --check ./openstack-validation.json
./bin/hostdelta collect --config ./openstack-validation.json --json
```

Expected: `adapter:<name>` has an `ok` source result, identity and configured probes
are reachable, no credentials appear in output, and a durable adapter checkpoint is
saved. A 401/403 is an unknown/authentication or authorization issue; inspect role,
project and endpoint selection. A connection failure is an observation from this
host, not proof of a global outage.

## 3. Run the read-only acceptance verifier

Stop any collector using this validation directory, then run:

```bash
python3 scripts/verify_live.py \
  --config ./openstack-validation.json \
  --state-dir "$HOSTDELTA_STATE_DIR" \
  --output ./openstack-acceptance.json \
  --cycles 3
```

It waits the configured interval between cycles, verifies real source results and
SQLite integrity, and writes a private mode-0600 report. Exit 0 means all selected
checks passed. Exit 3 means review is required; the report lists the reasons. It
cannot certify your entire cloud or every distribution. Unconfigured capabilities
are not silently treated as tested.

Review `checks`, `cycles[].sources`, `status.sources` and `incidents`. Record the
Linux distribution, systemd version, OpenStack release, chosen API endpoints and
credential role scope in your acceptance notes. The report can contain internal
hostnames, paths and IPs; review it before sharing. Never send a populated credential
file, environment dump or raw Authorization header.

## 4. Verify Proxmox when available

Repeat with `examples/proxmox.json`, real endpoint/CA settings and a scoped token:

```bash
read -r -p 'Token ID (USER@REALM!TOKENID): ' PROXMOX_TOKEN_ID
read -r -s -p 'Token secret: ' PROXMOX_TOKEN_SECRET
printf '\n'
export PROXMOX_TOKEN_ID PROXMOX_TOKEN_SECRET
python3 scripts/verify_live.py \
  --config ./proxmox-validation.json \
  --state-dir "$HOSTDELTA_STATE_DIR" \
  --output ./proxmox-acceptance.json --cycles 3
```

Expected: cluster resource/state responses are readable and the token is absent
from reports. Confirm the visible resource count is consistent with the token's
scope. An intentionally stopped guest must not become an outage. A standalone node
may have no cluster quorum record; document that distinction. Inventory change
checks should use a disposable guest or a separately authorized maintenance action.

## 5. Structured application records and durable recovery

Use a separate test file, not an existing production log. Install the package into
the same Python environment or run the example with `PYTHONPATH=src`:

```bash
mkdir -p ./validation-logs
PYTHONPATH=src python3 examples/structured_app.py > ./validation-logs/app.jsonl
```

Add its absolute path to `application_logs`, collect once, and query:

```bash
./bin/hostdelta collect --config ./openstack-validation.json --json
./bin/hostdelta events --since 1h --service backup-worker --json
```

Expected: five records from this example, with correlated operation/HTTP events;
no query token; completion duration; no raw request body. Capture a trace_id and
query it with `events --trace-id VALUE`. Run collection again without writing a new
line: inserted application-record count should be zero.

Rotation test on this test file only:

```bash
mv ./validation-logs/app.jsonl ./validation-logs/app.jsonl.1
PYTHONPATH=src python3 examples/structured_app.py > ./validation-logs/app.jsonl
./bin/hostdelta collect --config ./openstack-validation.json --json
```

Expected: five additional records, distinct event IDs, no duplicate old records.
Then test copytruncate on the disposable file and confirm the coverage warning.
For incomplete writes, append a JSON object without a newline: it must not be ingested
until its newline arrives. Malformed lines must increment warning counts without
putting their raw text into reports. These cases are also automated in the unit suite.

## 6. Supervision, restart and retention

Install the reviewed service template using the same identity, directory and config.
For the custom validation directory, set `HOSTDELTA_STATE_DIR` in the service's
EnvironmentFile too; shell exports are not inherited automatically by systemd.

```bash
systemctl --user start hostdelta-collector.service
./bin/hostdelta status --json
systemctl --user restart hostdelta-collector.service
./bin/hostdelta status --json
./bin/hostdelta events --since 1h --service backup-worker --json
```

Expected: fresh heartbeat, the same committed log offsets, no re-ingestion of old
records. SIGTERM should exit cleanly and log `collector.stopped`. A second collector
using the same directory must fail with a clear lock error.

Stop the collector and run `prune --keep-days 30 --dry-run --json`. Confirm preservation
of labeled snapshots, the boundary baseline and open incidents. Do not shorten a
production retention policy just to force a test. Automated retention tests use
isolated temporary databases and injected historical timestamps.

## 7. Negative cases without production fault injection

Use a copied configuration and separate validation state for each case. Never edit
production credentials or block production endpoints to run a negative test.

| Case | Safe setup | Expected result |
| --- | --- | --- |
| Missing credential | Reference a nonexistent environment variable in the copied config | Unknown health, no HTTP request |
| Wrong credential | Use a deliberately invalid test value only in the validation process | 401/403 as unknown; no fabricated outage |
| Unreachable API | Point only the copied config to an unused loopback port | Down from this observer; incident after confirmation threshold |
| Invalid CA | Point copied config to an unrelated test CA | Unknown/TLS error; verification is not bypassed |
| Unreadable log | Configure a disposable file denied to the test identity | Unavailable source; other sources continue |
| Stale collector | Stop the validation daemon and wait more than three intervals | `status` returns 3 and archive coverage is not healthy |

Redirect refusal, HTTP 503 classification, bounded workers, response-body redaction,
transaction rollback and repeated ingestion are covered by the automated protocol
and persistence tests. Run them on the target host as well.

## 8. Isolated service outage/restart exercise

**Only on a disposable Linux VM or a separately authorized lab service. Never stop
Keystone, networking, storage or production VM workloads for this test.**

Have the lab administrator create a dedicated long-running systemd service named
`hostdelta-test.service` (for example, a sleep process). Add that literal service to
`services` in a validation config, set a five-second interval and use two-sample
failure/recovery confirmation. Start the collector and obtain two healthy samples.

1. Restart only `hostdelta-test.service`; after the next sample, verify one
   `service_restart` record with different invocation IDs on the same boot.
2. Stop only the test service and wait for at least two cycles. Verify an open
   incident with last-good/first-bad bounds, not an invented exact start time.
3. Start only the test service and wait for two cycles. Verify recovery bounds and
   the first-good timestamp as the interval end, with later confirmation time.
4. Repeat with the collector stopped during part of the episode. Verify a coverage
   gap and that an unknown observation does not count as recovery.
5. Remove the test service from configuration and clean up the lab service.

Use `hostdelta incidents --since 1h --json` and retain the resulting incident IDs and
bounds in your acceptance report. Continuous downtime between observations remains
a sampling assumption; short failures between polls can be missed.

## 9. Optional TCP checks

For `sample`, use a disposable local client/server connection that remains open for
at least two collection intervals. Confirm appearance/disappearance records and
that a failed TCP source read does not claim every connection closed. Check IPv4
and IPv6 if both are enabled in your environment.

For `conntrack`, use a reviewed system service with the documented capability,
`conntrack` installed and `tcp.mode=conntrack`. Generate traffic only to your test
server. Confirm NEW/DESTROY flow records, unknown direction and
`handshake_confirmed=false`. Restart the subscription and verify the explicit gap.
A one-shot verifier cannot validate a persistent conntrack subscription; its report
marks that source for separate review. Netlink losses are not a guarantee of a full
packet or request history.

## Report back

Provide the reviewed acceptance JSON, HostDelta version, distribution/Python/systemd
versions, enabled collector types, and the failing test/check names. Include only
sanitized error codes and relevant source warnings. State which optional features
were not tested. Keep the secret values and populated credential files on your host.
