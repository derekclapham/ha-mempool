# Security

This integration talks to an address the user chooses and reports on money. It
runs inside Home Assistant with the same privileges as everything else there,
and it is installed by people who will never read its source. That combination
sets the bar for how it is written.

This document describes the principles it is held to and the mechanisms that
enforce them. It is not a changelog — the commit history covers what changed and
when.

## Reporting a vulnerability

**Please report privately, not in a public issue.**

Use [GitHub's private vulnerability reporting][advisory] on this repository. That
opens a channel visible only to you and the maintainer, and it is the fastest
route to a fix.

[advisory]: https://github.com/derekclapham/ha-mempool/security/advisories/new

Useful things to include: what an attacker has to control to reach the problem
(the configured instance, a network position, a DNS record, an installed
integration), what they get out of it, and a payload or sequence that
demonstrates it. A proof of concept is welcome but not required — a clear
description of the mechanism is enough.

This is a single-maintainer hobby project. There is no bounty and no guaranteed
response time, but security reports are prioritised over everything else, and you
will get an acknowledgement. Please give a reasonable window for a fix before
disclosing publicly. Credit is offered in the advisory unless you prefer
otherwise.

Only the latest release is supported. Fixes ship in a new version rather than as
patches to older ones.

## What this integration is trusted with

There is no credential here — the mempool API needs none, and this integration
supports none. What it is trusted with instead:

1. **The address of your node.** For a self-hosted user this is usually an
   internal hostname or a LAN address, and it is the one piece of configuration
   that describes your network rather than your preferences.
2. **A picture of your interest in Bitcoin.** Which fiat you price in, and that
   you care enough to run a node. Individually dull, but it is yours.
3. **Standing in your Home Assistant instance.** Anything it does badly —
   burning memory, blocking the event loop, filling the recorder, corrupting
   statistics — lands on the whole instance, not just on itself.

The third is the important one, and it is where most of the effort goes. This
integration holds nothing an attacker would want to steal. What it has is
*reach*: a foothold inside a trusted process, fed by data from somewhere else.

### Why the instance is the threat, not the target

Most integrations worry about protecting a credential from the outside world.
The shape here is inverted. There is no secret to leak, but there is a
continuous stream of attacker-shaped input arriving from a server the user
nominated, parsed by code with full access to their home automation.

A hostile response does not need to be exotic to do damage. A number can be
large enough that computing with it exhausts memory. A string can carry terminal
escapes into the log of whoever is debugging. A list can be long enough that
writing it to the database is the attack. None of these require a bug in the
usual sense — they require only that the code believed what it was told.

### What a hostile instance cannot do

The API is read-only and so is this integration: it issues `GET` requests
exclusively, registers no entity that controls anything, and has no code path
that writes to the instance. Nothing a response says can cause a transaction, a
transfer, or a change to your node.

The realistic worst case is therefore disruption and disclosure — degrading your
Home Assistant instance, or writing misleading data into it — rather than loss
of funds. That is worth preventing, and it is not the same as losing money. Both
halves of that sentence matter.

## Principles

### 1. The instance is not trusted

Everything arriving over the network is treated as hostile input. This holds
regardless of whether the instance is the public mempool.space or a machine in
the user's own rack, because a compromised host, a hijacked DNS record, an
intercepting proxy and a typo all produce the same thing.

Concretely, the parsing layer assumes the response is trying to break it:

- **Every response is bounded in size.** Bodies are read in chunks against a
  ceiling and abandoned past it, rather than being materialised first and
  measured afterwards. A `Content-Length` the server is free to misstate is not
  consulted. This matters more than it sounds: the HTTP layer decompresses
  transparently and without any ratio limit, so a small reply can expand to
  hundreds of megabytes and exhaust a modest Home Assistant host.
- **Every number must be finite.** `NaN` and `Infinity` are refused, and so is
  any ordinary-looking literal that overflows to infinity — the two are
  different spellings of the same problem and blocking only the obvious one is
  no defence. Numbers are validated as they are parsed, so nothing non-finite
  exists in the parsed structure at all.
- **Values used in arithmetic are range-checked, not merely type-checked.** Some
  fields are not just displayed but computed with, and one of them is used as an
  exponent. For those, being a number is not sufficient: being a *believable*
  number is the requirement, because the failure mode of an absurd value is
  unbounded work inside the event loop rather than a wrong reading on a card.
  These checks are applied at ingest and repeated where the value is used, since
  the cost of the single check being bypassed is the whole instance.
- **Every collection is bounded on ingest.** Arrays are truncated and the set of
  currencies exposed as attributes is capped, applied where the data enters
  rather than where it is read. Attributes and statistics rows are written to the
  recorder database, so an unbounded collection is not a slow poll — it is
  durable damage that outlives a restart. Limits sit far above anything a real
  instance produces.
- **Every string is sanitised.** Names from the API become sensor states and
  text in log lines. Control and format characters are stripped: these carry
  terminal escape sequences that rewrite the screen of anyone tailing the log,
  newlines that forge log entries, and direction overrides that make a name
  display as something it is not. Lengths are capped, because a state Home
  Assistant refuses outright takes the sensor down and logs the raw string on
  the way.
- **Nothing structural is inferred from the payload.** Responses are checked to
  be the shape they are supposed to be before anything reads them, so a reshaped
  reply fails the update cleanly instead of raising somewhere unrelated. A
  missing field yields no value rather than an exception, and a failed update
  marks that group's sensors unavailable with a reason.

### 2. The user chooses the destination, deliberately

Pointing at an arbitrary host is not an accident here, it is the feature: a
self-hosted node is normally on a private network, so blocking private address
ranges would break the primary use case rather than protect it. The address is
therefore accepted as given, with two guards that cost nothing:

- It must be a syntactically valid `http` or `https` URL with a host, checked
  before any request is attempted, so a malformed or non-HTTP value is rejected
  in the config flow instead of becoming a confusing connection error.
- It must answer as a real mempool API before an entry is created, so a URL that
  merely responds is not accepted.

Two consequences are worth stating rather than implying. **Turning off
certificate verification means what it says** — it is offered for self-signed
certificates on a trusted network, and on an untrusted one it permits
interception. And **this integration can reach anything Home Assistant can
reach**, so the address deserves the same care as any other outbound target you
configure.

### 3. Minimum surface

- **No third-party runtime dependencies.** The integration declares none, so
  installing it adds no packages to your Home Assistant environment and no
  supply chain beyond this repository.
- **No credentials, anywhere.** There is nothing to store, redact, or leak.
  Instances requiring authentication are unsupported rather than half-supported.
- **Read-only, all the way down.** `GET` requests only, no controllable
  entities, and the one action it registers writes to Home Assistant's own
  statistics rather than to the instance.
- **No `eval`, no dynamic imports, no deserialisation of anything but JSON**, and
  no filesystem access.
- **A shared HTTP session, not a private one.** The integration borrows Home
  Assistant's client, so it inherits the platform's connection handling and
  certificate store instead of maintaining its own.

### 4. Data minimisation in what is shared

The diagnostics download is designed to be pasted into a public issue, so it
assumes an untrusted reader.

The instance address is redacted — for a self-hosted user it is an internal
hostname, and it is the only user-identifying value the integration holds. It
reaches the configuration by three separate routes, and all three are handled
rather than just the obvious one. Which *kind* of instance is in use is
preserved, because it is the single most useful fact when reading a bug report
and the public instance is not a secret.

Everything else in the download is public blockchain data: chain tip, fees,
mempool state, difficulty, mining pools and spot price. It is identical for
every user in the world and carries no information about the person sharing it.

### 5. Correctness is part of security here

This integration writes to Home Assistant's long-term statistics, which is
durable, aggregated and awkward to correct after the fact. Corrupting it is a
quieter failure than crashing, and a longer-lived one.

So the statistics path is treated as a security boundary in its own right: rows
are bounded, values are validated before import, imports are idempotent so a
retry cannot duplicate history, and the sensor's own statistical semantics are
chosen to match what the data actually is rather than what would satisfy a
convention.

Relatedly, a sensor that cannot produce a value says so. It reports `unknown`
when the instance answered but the value was absent, and `unavailable` when the
instance could not be reached — a sensor that quietly holds its last good value
is worse than one that admits it is broken.

### 6. The release pipeline is part of the product

Users install a zip built by CI and run it with full Home Assistant privileges.
The pipeline is therefore treated as production code:

- Values an author controls — notably the release tag — are passed to build
  scripts as environment variables, never interpolated into a shell command.
  GitHub substitutes template expressions before the shell parses the line, so
  quoting does not contain them, and git permits shell metacharacters in tag
  names.
- The release job refuses to build from anything that is not a plain semantic
  version tag.
- Git credentials are dropped immediately after checkout, since nothing later in
  the build needs them.
- Concurrent publishes of the same tag are serialised, so two overlapping runs
  cannot interleave and leave the wrong artifact attached.
- A `SHA256SUMS` file is published beside the zip, so a later substitution of the
  asset can be detected rather than merely suspected.
- Workflows declare read-only permissions explicitly rather than inheriting a
  default that could be widened later. Pull requests from forks run without
  access to any secret, and the repository holds none.

### 7. Findings are proven, then pinned

Two working rules, because both failure modes have bitten this project:

**A vulnerability is reproduced before it is fixed.** Plausible-sounding analysis
is not evidence. Every security change here starts with a payload or a request
that demonstrably causes the bad outcome, and finishes by replaying it. More
than one confident hypothesis has failed that bar and been dropped rather than
"fixed" — which is the point of setting it.

**A hardening change is re-tested against benign input.** Tightening a limit is
an easy way to silently break the normal path, and a bound that rejects real
data is its own kind of outage. Every limit here has a paired test asserting
that ordinary values — including values sitting exactly on the boundary — still
work.

Each confirmed issue leaves behind a regression test that reproduces the
original attack, so a later refactor cannot quietly reopen it. The test suite
runs on every push, with type checking and a coverage floor alongside it.

## Scope

**In scope:** anything in this repository — the integration, its workflows, and
its published artifacts.

**Out of scope**, though still worth telling us about if the interaction is
interesting:

- Vulnerabilities in Home Assistant itself. Report those to the
  [Home Assistant security team](https://www.home-assistant.io/security/).
- Vulnerabilities in the mempool software or in mempool.space. Report those to
  [the mempool project](https://github.com/mempool/mempool).
- Attacks that require an attacker to already have arbitrary code execution on
  the Home Assistant host or access to its storage.
- Consequences of deliberately pointing the integration at a host you know to be
  hostile, beyond what is described above. Choosing the destination is the
  feature; the guarantee is that a hostile response is contained, not that a
  hostile destination is prevented.

## What this cannot protect you from

Stated plainly, because a security document that implies more than it delivers is
itself a hazard:

- **Home Assistant's own trust model.** Integrations are not sandboxed from one
  another. Any integration you install runs with the same access as this one.
  Only install code you are willing to extend that trust to — including this.
- **Your own instance's exposure.** If your Home Assistant is reachable from the
  internet without authentication, nothing here helps.
- **A hostile network path with verification disabled.** Turning off certificate
  verification is a supported option for self-signed certificates, and it
  removes the protection it names. On a network you do not control, that is a
  meaningful loss.
- **What your instance already knows.** A self-hosted node sees your queries
  because you run it. mempool.space sees your IP address and polling pattern if
  you use it. This governs what reaches your logs, your database and anything
  you share — not what the other end observes.
- **A compromised maintainer account.** The pipeline hardening raises the cost of
  an accidental or opportunistic compromise; it does not defend against someone
  who controls the account that publishes releases.
