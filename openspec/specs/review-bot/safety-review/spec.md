# Safety Review Specification

## Purpose

Provide a narrowly scoped safety review for high-confidence hardcoded-secret exposure and obvious injection paths introduced by pull-request changes.

## Requirements

### Requirement: Safety review agent produces structured findings
The system SHALL run a safety review agent that reads the shared review context and the complete provider-originated diff and emits output matching the shared review schema.

#### Scenario: Safety review completes
- **WHEN** the safety review agent finishes analyzing a pull request
- **THEN** it returns structured findings, an overall verdict and explanation, confidence scores, and a status field

#### Scenario: Another agent's input excludes a file
- **WHEN** a changed file is excluded from the correctness, API-reality, and tests agent-review diff
- **THEN** the safety agent still receives that file's complete patch in the provider-originated diff

#### Scenario: Safety review output is invalid
- **WHEN** the safety review agent returns output that does not match the shared review schema
- **THEN** the agent pipeline applies its existing partial-failure behavior and does not treat the invalid output as successful findings

### Requirement: Detect high-confidence hardcoded secrets
The safety review agent SHALL emit a finding when changed content contains a credential or secret value with concrete evidence that it may be usable or exposed.

#### Scenario: Usable credential is committed
- **WHEN** a changed line embeds a live-looking API key, private key, password, or access token in source or configuration
- **THEN** the agent emits one finding describing the exposure path and how the credential could be abused

#### Scenario: Placeholder or secret reference is used
- **WHEN** changed content contains only an obvious placeholder, test-only dummy value, redacted example, or reference to an external secret provider
- **THEN** the agent does not report a hardcoded-secret finding without additional evidence of exposure

### Requirement: Detect obvious injection paths
The safety review agent SHALL emit a finding when attacker-controlled input reaches a command, query, or interpreter context without the context-appropriate separation, escaping, or validation needed to prevent injection.

#### Scenario: Untrusted input reaches a shell command
- **WHEN** changed code interpolates user-controlled input into a shell command that is executed
- **THEN** the agent emits one finding with a concrete malicious input, resulting command behavior, and safer construction

#### Scenario: Input is safely separated
- **WHEN** untrusted input is passed through a context-appropriate parameterized interface that prevents it from changing command or query structure
- **THEN** the agent does not emit an injection finding

### Requirement: Limit safety findings to approved categories
The safety review agent SHALL NOT emit general hardening advice, dependency-vulnerability speculation, authentication design opinions, or other security commentary that is not a high-confidence hardcoded-secret exposure or obvious injection path.

#### Scenario: General defense-in-depth suggestion
- **WHEN** a change could add another security control but no secret exposure or concrete injection path is present
- **THEN** the agent emits no finding

### Requirement: Every safety finding is evidence-backed
Every safety review finding SHALL identify one exposed value or one source-to-sink injection path, a concrete abuse or failure scenario, and a suggested fix.

#### Scenario: Valid injection finding
- **WHEN** the agent reports an injection path
- **THEN** the finding names the untrusted input, unsafe sink, concrete payload or state, diff-valid location, confidence and priority values, and context-appropriate remediation
