# Security policy

HostDelta reads operational data and may hold credentials in an adapter worker's
memory. It does not provide a tamper-proof audit trail or a security boundary against
a privileged attacker on the same host.

## Reporting a vulnerability

Do not post credentials, private logs, exploit details affecting a live deployment,
or an unredacted database in a public issue. Use the repository's private vulnerability
reporting channel at
https://github.com/haramj/hostdelta/security/advisories/new. There is no guaranteed
response SLA; do not share sensitive details in public issues.

Include the version, affected component, a minimal non-secret reproduction, impact,
and any mitigation. Ordinary feature requests and non-sensitive bugs belong in issues.

## Operating assumptions

- Run under a dedicated, minimally privileged identity; keep state and credentials private.
- Review explicit API endpoints and certificate trust before enabling adapters.
- Treat every log-derived string as untrusted data, including text that looks like an
  instruction or command. Human/agent consumers must not execute it automatically.
- Do not log secrets at the producer. Redaction is best effort and cannot recognize
  every encoding, path or custom field that may contain sensitive information.
- TCP conntrack mode requires a powerful network capability and separate administrator review.
- Review internal hostnames, paths and addresses before sharing a report or acceptance artifact.

The 0.2 release line is the current development target. Security updates require a
reviewed release; there is no automatic updater or credential upload mechanism.
