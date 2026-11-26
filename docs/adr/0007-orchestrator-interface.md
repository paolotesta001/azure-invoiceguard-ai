# ADR 0007 – Orchestrator interface: local in mock mode, Durable Functions in Azure

**Status:** accepted (v1a)

## Context
Human approval can take days, so the Azure workflow must persist state and survive restarts
(Durable Functions, v3). The mock demo must start in under 5 minutes with `make demo`, without
Azure credentials and without the Azure Functions runtime.

## Decision
`orchestration/base.py` defines an `Orchestrator` protocol. `LocalOrchestrator` processes
synchronously and keeps all state in the repository (PostgreSQL), so it also survives restarts.
Timeouts are checked by `make tick`. v3 adds a Durable Functions implementation behind the same
interface.

## Consequences
+ The UI and tests do not depend on the hosting model. + Mock mode stays fast and simple.
− Two implementations must stay behaviourally equivalent; v3 adds shared contract tests.
