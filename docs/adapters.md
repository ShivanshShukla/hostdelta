# OpenStack and Proxmox adapters

Adapters only contact URLs explicitly selected by the operator. They do not use
arbitrary URLs from a service catalog, follow redirects, read shell RC files, or
modify cloud resources. Proxy environment variables are not used by the HTTP client.

## OpenStack

Start with `examples/openstack.json`. `url` is the Keystone v3 base URL; `/v3` is
appended if omitted. Authentication is a POST to `/v3/auth/tokens` with the
`application_credential` method. The resulting X-Subject-Token exists only in the
worker's memory and is sent as X-Auth-Token to each explicitly configured service URL.
A fresh token is requested each cycle; choose an interval appropriate to your cloud.

```json
{
  "name": "production",
  "type": "openstack",
  "url": "https://identity.example.org:5000/v3",
  "credential_id_env": "OS_APPLICATION_CREDENTIAL_ID",
  "credential_secret_env": "OS_APPLICATION_CREDENTIAL_SECRET",
  "ca_file": "/etc/ssl/certs/private-cloud.pem",
  "timeout_seconds": 5,
  "services": {
    "compute": "https://compute.example.org:8774/v2.1",
    "image": "https://image.example.org:9292/v2"
  }
}
```

Use an application credential whose project and roles are sufficient for the exact
GET endpoints you configure. Role names and policies vary by deployment; do not
assume a role named `reader` is available or sufficient everywhere. API root/version
endpoints often require less permission than resource-list endpoints. Choose small
JSON responses; pagination and complete cloud resource inventory are not implemented
for OpenStack. This adapter verifies identity and selected endpoint responses.

An example shell session, using values already created through your cloud's normal
credential process:

```bash
read -r -p 'Application credential ID: ' OS_APPLICATION_CREDENTIAL_ID
read -r -s -p 'Application credential secret: ' OS_APPLICATION_CREDENTIAL_SECRET
printf '\n'
export OS_APPLICATION_CREDENTIAL_ID OS_APPLICATION_CREDENTIAL_SECRET
hostdelta collect --config ./openstack.json --json
```

Do not use `set -x`, paste secrets into JSON, or put them in command-line arguments.
Shell exports do not automatically appear in systemd services. Supply the private
EnvironmentFile described in `docs/operations.md` for a supervised deployment.

## Proxmox

Start with `examples/proxmox.json`. The adapter GETs:

- `/api2/json/cluster/resources`
- `/api2/json/cluster/status`

It authenticates using `Authorization: PVEAPIToken=USER@REALM!TOKENID=SECRET`.
`PROXMOX_TOKEN_ID` contains the entire `USER@REALM!TOKENID` portion and
`PROXMOX_TOKEN_SECRET` contains the secret. Custom environment variable names can be
configured using `token_id_env` and `token_env`.

Use an appropriately scoped read-only API token. Proxmox token privilege separation
means the token's effective permissions are constrained by its user's permissions.
Review access to cluster/resource visibility with your administrator. The adapter
reports an unavailable/unknown result when the API denies access; it never grants
roles or changes ACLs. Guest status changes are inventory observations, not automatic
claims that intentionally stopped VMs have failed.

A cluster record with `quorate=0` is unhealthy. If no cluster record exists, such as
a standalone deployment, the successful status response is treated as reachable;
it is not a claim that a distributed quorum was measured.

## Transport and failure mapping

TLS certificate and hostname verification are enabled. Configure `ca_file` for a
private CA. There is no insecure TLS toggle. HTTP requires `allow_http: true` and
sends credentials unencrypted; use it only where your deployment policy permits it.
Redirects are refused, including redirects to another path on the same host.

| Observation | Health interpretation |
| --- | --- |
| Successful expected JSON response | Up for that API probe |
| HTTP 5xx or connection failure | Down from this observer's perspective |
| HTTP 401/403, redirects, other HTTP errors | Unknown; often authorization/configuration |
| Certificate verification error | Unknown; trust configuration requires review |
| Malformed/oversized response | Unknown; source contract could not be established |
| Worker deadline/process failure | Unknown; checkpoint preserved |

Response bodies and request headers are not logged on errors. Maximum response size
is 2 MiB. A worker process imposes a wall-clock limit of at most 45 seconds in addition
to socket timeouts, so a server slowly streaming data cannot block the daemon forever.
Health confirmation is handled by the common incident state machine.

References: [OpenStack Identity API v3](https://docs.openstack.org/api-ref/identity/v3/),
[Proxmox VE API](https://pve.proxmox.com/wiki/Proxmox_VE_API), and
[Proxmox API viewer](https://pve.proxmox.com/pve-docs/api-viewer/).
