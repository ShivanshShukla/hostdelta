# Architecture

```text
journal / JSONL / HTTP logs / systemd / cloud APIs / optional TCP
                           |
                bounded source collectors
                           |
          normalized events + health observations + checkpoint
                           |
               one SQLite transaction per source
                           |
        archive events + incidents + source coverage + offsets
                           |
              brief / events / incidents / agent JSON
```

The collector is a supervised foreground process. `collector.lock` excludes a second
collector or retention writer for the same state directory. SQLite WAL and a busy
timeout allow concurrent readers and ordinary CLI writes. Each source commits its
events, deduplication keys, checkpoint, coverage result and health transitions
atomically. Filesystem reads and network probes occur outside that transaction.

## Module boundaries

| Module | Responsibility |
| --- | --- |
| `collect.py`, `events.py`, `requests.py` | On-demand Linux state and existing log readers |
| `tail.py` | Incremental application/HTTP records, rotation and offset state |
| `telemetry.py` | Application SDK, normalization and redaction |
| `adapters.py` | Bounded OpenStack/Proxmox HTTP workers |
| `health.py`, `conntrack.py` | Systemd identity and optional TCP evidence |
| `incidents.py` | Pure sampled health transition state machine |
| `archive.py`, `store.py` | Persistence, transactions, queries, migration and retention |
| `daemon.py` | Single-writer scheduling, source isolation and lifecycle |
| `brief.py`, `cli.py` | Human/JSON reports and command contracts |

## Failure semantics

`unknown` is not `down` and never closes an open incident. Unknown observations break
consecutive confirmation counts and mark coverage gaps. Polling gaps greater than
three configured intervals do the same. Initial unhealthy observations produce
left-censored incidents: the failure may predate the collector.

Recovery is first-good after the last-bad observation, confirmed by the configured
number of good samples. Displayed duration bounds describe a sampled episode,
assuming continuity between bad samples; they are not packet-level proof of continuous
downtime. The lower duration is zero when a known coverage gap exists. Multiple
short incidents inside one polling interval can be missed or merged.

A same-boot change in systemd InvocationID confirms a new service execution. The
collector reports a count lower bound of one, not an exact count of all restarts.
No changes are inferred from a failed source collection.

## Bounded work

| Source | Limit |
| --- | --- |
| Journal | Newest 10,000 raw records per poll, eight-second subprocess timeout |
| Durable JSONL/HTTP | 32 configured files per type; 4 MiB or 5,000 records per file per cycle; 64 KiB per record |
| On-demand HTTP | 32 files; 8 MiB per file, including bounded gzip decompression |
| Watched configuration | 3,000 files; 2 MiB per file |
| Systemd health | 32 explicitly configured units; eight-second subprocess timeout |
| TCP samples | 4 MiB per table; 10,000 established sockets |
| Conntrack stream | 4 MiB drained per cycle; bounded record buffer; explicit netlink/subscription gaps |
| Adapters | 32 adapters; 16 configured OpenStack service URLs per adapter; 2 MiB response; at most 45 seconds per worker |
| Proxmox inventory | 2,000 resources; event contains counts and a bounded identity sample |
| Event queries | 10,000 records; explicit truncation flag |
| Incident query | Newest 1,000 overlapping incidents |

Collectors run sequentially by source. If the workload exceeds the configured cycle
interval, the next cycle starts after completion. Use status timestamps and source
warnings to detect backlog. The daemon does not claim a sustained fleet-scale event
throughput target.

Journal polling uses a 60-second overlap with cursor-based event deduplication. The
journal scan ceiling and source retention can still cause losses; such detected gaps
are recorded. Late arrivals beyond the overlap can be missed. JSONL offsets do not
require timestamps to arrive in order.

## Retention and migration

Database schema version 2 adds the event archive, HTTP index, source checkpoints,
source-run coverage, monitors and incidents. Opening a version-1 state database
creates the new tables while preserving legacy snapshots, sessions, settings and
agent records. Unsupported future versions are rejected. Back up the database before
an upgrade; downgrading version 2 with the version-1 binary is unsupported.

Retention deletes archived events by ingestion time; HTTP index rows cascade with
them. It also expires old coverage runs, legacy agent records, old session history
and closed incidents. Named snapshots, the newest snapshot, one snapshot at/before
the cutoff, the last session, all open incidents and all consumer/source cursors are
preserved. The recorded retention floor never moves backward after an extension.

Open incidents and named snapshots can grow indefinitely. Monitor disk usage. SQLite
reuses freed pages; offline VACUUM is a separate operator action after backup and
stopping writers. Checkpoints for removed sources are retained so re-adding a source
can resume; clean them only as part of an intentional state reset.
