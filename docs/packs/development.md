# Pack development

FERPEK Lens packs are portable, declarative definitions that describe how a service is discovered, where its logs are collected from and how those logs are interpreted.

Service-specific detection logic should remain in packs whenever possible instead of being hard-coded into the agent.

## Pack structure

A pack normally contains:

    my-pack/
    ├── manifest.yaml
    └── rules/
        ├── rule-one.yaml
        └── rule-two.yaml

The manifest describes the pack, its compatibility requirements, supported platforms and log sources.

Rules describe how matching log events are interpreted.

## Compatibility

Compatibility is declared independently for the main FERPEK Lens components.

Example:

    compatibility:
      server: ">=0.5.0"
      agent: ">=0.5.0"
      pack_engine: ">=0.2.0"

The fields have different purposes:

- `server` defines the compatible FERPEK Lens Server version;
- `agent` defines the compatible FERPEK Agent version;
- `pack_engine` defines the Pack Engine version required to interpret the pack rules.

The Pack Engine is versioned independently from the Agent because pack-language capabilities can evolve separately.

If a pack declares a `pack_engine` requirement and the Agent does not report a compatible Pack Engine version, FERPEK Lens does not distribute that pack to the Agent.

This behaviour is intentionally fail-closed.

## Pack Engine 0.2.0

Pack Engine 0.2.0 introduced:

- aggregate collections;
- distinct aggregate values;
- aggregate conditions.

Packs using these capabilities must declare:

    compatibility:
      pack_engine: ">=0.2.0"

## Aggregation

Repeated matching events can be grouped over a time window.

Example:

    group_by:
      - ip

    aggregate:
      window_seconds: 300
      threshold: 5
      cooldown_seconds: 900

This counts matching events for the same group during the configured window.

The Finding becomes eligible when the threshold is reached. The cooldown prevents repeated Findings for the same group during the configured period.

## Aggregate collections

Pack Engine 0.2.0 can retain values observed during the aggregation window.

Example:

    aggregate:
      window_seconds: 300
      threshold: 5

      collect:
        users:
          field: user
          distinct: true

This exposes the template values `{users}` and `{users_count}`.

With `distinct: true`, repeated values are counted once while preserving their first-observed order.

For example, the values `root`, `admin`, `root` and `postgres` produce three distinct users.

## Aggregate conditions

Numeric aggregate conditions can be used as an additional gate before a Finding is created.

Example:

    conditions:
      users_count:
        gte: 3

Supported operators are:

- `eq`
- `ne`
- `gt`
- `gte`
- `lt`
- `lte`

Conditions currently operate on numeric aggregate values such as `count` and `<collection>_count`.

All configured conditions must match before the Finding is emitted.

## Relevant activity

Relevant activity represents individual events that are useful enough to surface without necessarily representing a problem.

For example, a successful SSH login can be Relevant activity without becoming a Finding.

## Findings

Findings represent summarized situations or patterns that may require attention.

They should reduce log noise instead of reproducing every matching log line.

For repeated events, aggregation should be preferred when it provides a clearer representation of what happened.

## Findings should describe, not prescribe

Pack Findings should describe what was observed and provide useful context.

For example:

    18 failed SSH authentication attempts from 192.0.2.10 targeted 6 usernames during the last 5 minutes.

A pack should not decide the operational response for the administrator.

FERPEK Lens interprets logs and reduces noise. The system administrator decides what action is appropriate.

## Official packs

Official FERPEK Lens packs are maintained in the separate `ferpek-lens-packs` repository.

Official packs should include:

- explicit compatibility requirements;
- platform-aware source definitions;
- useful field extraction;
- sensible aggregation thresholds;
- deduplication and cooldown behaviour;
- representative functional tests;
- deterministic build artifacts.

The full pack specification is still evolving and will be expanded as additional Pack Engine capabilities are introduced.
