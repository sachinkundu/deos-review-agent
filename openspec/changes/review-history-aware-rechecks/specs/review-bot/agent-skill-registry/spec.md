## ADDED Requirements

### Requirement: Provide trusted recheck resources through the existing registry
The approved symbolic input contract SHALL support a reviewer-scoped history view, assigned prior-finding targets, current-head evidence, and the complete provider conversation and target roster needed by the coordinator. These resources SHALL be host-produced outside the pull request checkout and SHALL follow the existing registry isolation and audit behavior.

#### Scenario: Reviewer runs in recheck mode
- **WHEN** a registered reviewer is invoked for a recheck
- **THEN** it receives only its declared reviewer-scoped history, target, and evidence resources

#### Scenario: Coordinator runs in recheck mode
- **WHEN** the existing coordinator is invoked for a recheck
- **THEN** it receives the complete normalized conversation, complete target roster, attributed results, and existing catalog identities

#### Scenario: Pull request shadows a recheck resource
- **WHEN** the checkout contains a file, directory, symlink, or marker named like a recheck resource
- **THEN** the host-owned resource remains authoritative and is not expanded by pull request content

#### Scenario: Recheck resource is audited
- **WHEN** a host-owned recheck resource is assigned to an agent
- **THEN** the run manifest records its schema version, digest, symbolic name, and assigned target identities without copying arbitrary provider text or secrets

### Requirement: Bound reviewer history without losing target identity
Reviewer-scoped history resources SHALL have deterministic count and byte bounds. Optional context MAY be truncated deterministically, but a target's identity, provider relationship, or required evidence MUST NOT be partially supplied.

#### Scenario: Optional context exceeds the bound
- **WHEN** unrelated conversation context exceeds a reviewer resource limit
- **THEN** allowed optional context is truncated deterministically and the truncation is recorded

#### Scenario: Required target data cannot fit
- **WHEN** an assigned target's identity, relationship, or required evidence cannot fit within the configured bound
- **THEN** the run fails before that reviewer starts rather than supplying an incomplete target
