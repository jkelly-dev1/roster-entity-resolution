# Security Policy

## Reporting a Vulnerability

Please report suspected vulnerabilities privately, not through public issues or
pull requests.

Preferred channel: use GitHub's private vulnerability reporting for this
repository (the "Report a vulnerability" button on the Security tab). It opens a
private advisory visible only to the maintainer.

Aim is to acknowledge a report within 5 business days and to share a resolution
or mitigation plan within 30 days. Timelines may vary, as this is maintained in
personal time.

Please include enough detail to reproduce the issue: the affected file or
endpoint, the version or commit, steps to reproduce, and the impact you observed.

## Supported Versions

This is a personal learning and portfolio project. Only the latest commit on the
`main` branch is supported; there are no maintained release branches or
backports.

## Scope

These are self-contained demo projects, not production services. Nothing here
calls a hosted API and no key is ever needed to run it. The one credential-
shaped string in the repository is deliberate and is not a secret:
`stack/compose.yaml` sets a fixed Postgres user and password, because Postgres
requires them to start and the single port it exposes is bound to loopback on
one machine. Do not reuse that pair anywhere reachable.

There is no corpus and no downloaded data. Every row the experiments run on is
generated from a fixed seed by `scripts/generate_roster.py`, so no real
provider, member, address or identifier appears anywhere in this repository.
The National Provider Identifiers in the generated data are arithmetically
valid and belong to nobody: they are produced by a bijection over the digit
space and were never drawn from any registry.

Limitations that the README documents as deliberate, out-of-scope seams are
noted but may not be actioned.
