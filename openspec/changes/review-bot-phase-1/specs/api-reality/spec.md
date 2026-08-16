## Purpose

Run an API-reality sub-agent that flags hallucinated or misused GitHub, Linear, and Cloudflare APIs, methods, fields, or response shapes in the changed code.

## ADDED Requirements

### Requirement: Provide provider contract context
The system SHALL supply the API-reality agent with accurate provider contract summaries for GitHub, Linear, and Cloudflare APIs that the changed code interacts with.

#### Scenario: Contract context is available
- **WHEN** the changed code uses a GitHub, Linear, or Cloudflare API
- **THEN** the agent receives a summary of the real API methods, request fields, response fields, and error behavior

### Requirement: API-reality agent produces structured findings
The system SHALL run an API-reality sub-agent that reads the shared context, diff, and provider contract summaries, and emits findings matching the review output schema.

#### Scenario: Hallucinated method found
- **WHEN** the changed code calls a GitHub, Linear, or Cloudflare method that does not exist
- **THEN** the agent emits a finding that names the real contract and the hallucinated usage

#### Scenario: Agent output is invalid
- **WHEN** the API-reality agent returns JSON that does not match the schema
- **THEN** the system reports a schema validation error and stops the review run

### Requirement: Ground findings in provider contracts
Every API-reality finding SHALL reference the real provider contract that contradicts the changed code.

#### Scenario: Misused response field
- **WHEN** the changed code reads a response field that the provider does not return
- **THEN** the finding cites the documented response shape and explains why the field is not available

### Requirement: Distinguish provider versions where relevant
The system SHALL allow the agent to consider the exact provider API version or package version in use when judging whether a method or field exists.

#### Scenario: Version-specific method
- **WHEN** the changed code uses a method introduced in a specific Cloudflare Sandbox package version
- **THEN** the agent checks the version declared in the project and flags only methods not available in that version

### Requirement: Every API-reality finding includes a concrete failure scenario
The system SHALL require every API-reality finding to describe a concrete failure scenario and a suggested fix.

#### Scenario: Invalid webhook header
- **WHEN** the changed code references a Linear webhook header that does not exist
- **THEN** the finding explains how the signature verification will fail at runtime and suggests the correct header name

### Requirement: API-reality findings are limited to provider contract violations
The API-reality agent SHALL NOT flag logic bugs, style issues, or general architecture opinions. It SHALL flag only hallucinated or misused provider APIs.

#### Scenario: Logic bug unrelated to provider API
- **WHEN** the changed code has a logic bug that does not involve a provider API
- **THEN** the API-reality agent does not emit a finding
