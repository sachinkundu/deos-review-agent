# Api Reality Specification

## Purpose

Run an API-reality review agent that flags hallucinated or misused APIs, methods, fields, or response shapes of any dependency in the changed code.

## Requirements

### Requirement: Provide web-fetch tooling
The system SHALL provide the API-reality agent with a web-fetch tool so it can consult the dependency's published API documentation.

#### Scenario: Agent consults documentation
- **WHEN** the changed code uses an API method
- **THEN** the agent can fetch the dependency's real documentation and compare the claimed contract against it

### Requirement: API-reality agent produces structured findings
The system SHALL run an API-reality review agent that reads the shared context and diff, consults provider documentation via web-fetch tooling, and emits findings matching the review output schema.

#### Scenario: Hallucinated method found
- **WHEN** the changed code calls a dependency method that does not exist
- **THEN** the agent emits a finding that cites the real documentation and the hallucinated usage

#### Scenario: Agent output is invalid
- **WHEN** the API-reality agent returns JSON that does not match the schema
- **THEN** the system reports a schema validation error and stops the review run

### Requirement: Ground findings in provider documentation
Every API-reality finding SHALL reference the published provider documentation URL that contradicts the changed code.

#### Scenario: Misused response field
- **WHEN** the changed code reads a response field that the provider does not return
- **THEN** the finding cites the documented response shape, includes the documentation URL, and explains why the field is not available

### Requirement: Distinguish provider versions where relevant
The system SHALL allow the agent to consider the exact provider API version or package version in use when judging whether a method or field exists.

#### Scenario: Version-specific method
- **WHEN** the changed code uses a method introduced in a specific version of a dependency
- **THEN** the agent checks the version declared in the project and flags only methods not available in that version

### Requirement: Every API-reality finding includes a concrete failure scenario
The system SHALL require every API-reality finding to describe a concrete failure scenario and a suggested fix.

#### Scenario: Invalid webhook header
- **WHEN** the changed code references a webhook header that does not exist
- **THEN** the finding explains how the signature verification will fail at runtime, cites the real documentation, and suggests the correct header name

### Requirement: API-reality findings are limited to documented API violations
The API-reality agent SHALL NOT flag logic bugs, style issues, or general architecture opinions. It SHALL flag only hallucinated or misused provider APIs grounded in published documentation.

#### Scenario: Logic bug unrelated to provider API
- **WHEN** the changed code has a logic bug that does not involve a provider API
- **THEN** the API-reality agent does not emit a finding
