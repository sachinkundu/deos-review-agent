## ADDED Requirements

### Requirement: Run prior-finding evaluation through the existing pipeline
In recheck mode, the system SHALL reuse the registered reviewer pipeline without changing its roster, concurrency, ordering, failure handling, or coordinator mechanics. Each reviewer SHALL receive a mode-specific target list containing only owned prior findings within its declared review scope and MUST NOT return a new defect finding.

#### Scenario: Reviewer has prior findings to evaluate
- **WHEN** a recheck begins with one or more prior findings assigned to a reviewer
- **THEN** that reviewer evaluates only those target identities using the existing pipeline execution behavior

#### Scenario: Reviewer has no assigned prior findings
- **WHEN** a registered reviewer has no prior finding in its declared scope
- **THEN** its valid recheck result contains no classifications and no new findings

#### Scenario: Reviewer returns a new finding
- **WHEN** a recheck result contains an identity absent from that reviewer's assigned targets
- **THEN** the result fails validation before coordination or GitHub mutation

### Requirement: Coordinate only the supplied recheck targets
In recheck mode, the existing coordinator SHALL receive the complete owned target roster, complete normalized provider conversation, attributed reviewer results, and existing catalog identities. It SHALL return each applicable target exactly once with an allowed classification and MUST NOT return a new finding or GitHub review event.

#### Scenario: Every target is classified
- **WHEN** reviewers return valid classifications for all applicable prior findings
- **THEN** the coordinator returns those targets in deterministic order with no additional identity

#### Scenario: A target is missing or duplicated
- **WHEN** coordinator output omits an applicable target or contains the same target more than once
- **THEN** schema validation fails before review-posting planning

#### Scenario: Coordinator introduces an unknown target
- **WHEN** coordinator output contains an identity absent from the owned target roster
- **THEN** schema validation fails before review-posting planning

### Requirement: Treat recheck history as untrusted task data
Reviewer and coordinator instructions SHALL distinguish host-authored schemas and target assignments from provider-authored conversation and pull request content. Provider text MUST NOT expand target identities, tools, skills, filesystem access, symbolic resources, or output schemas.

#### Scenario: Comment asks for another review pass
- **WHEN** provider text asks an agent to ignore its targets or discover additional issues
- **THEN** the agent treats that text only as evidence and evaluates its assigned prior findings

#### Scenario: Pull request imitates a host resource
- **WHEN** the checkout contains a marker, file, or directory named like a recheck resource
- **THEN** it does not replace or extend the host-owned resource
