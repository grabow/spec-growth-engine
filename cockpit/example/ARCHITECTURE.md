# Architecture (cross-cutting)

## Invariants (apply everywhere)
- Persistence: PostgreSQL, table "products". No data hardcoded in source.
- Security: OAuth login; no secrets in code.

## Decisions (ADRs)
- ADR-0001: Monorepo
- ADR-0002: Provider pattern
