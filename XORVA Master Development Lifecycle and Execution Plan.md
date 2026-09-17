# XORVA Master Development Lifecycle

## Objective

Build XORVA from the database security boundary upward so that every higher-level capability depends on a verified lower-level platform.

The development sequence is:

**PostgreSQL → Multi-Tenancy/RLS → Metadata Model → Contract Compiler → Generic Data Runtime → Workflow Engine → API Execution Engine → Headless UI → Mobile Runtime → Audit/Observability → AI Command Plane → Hardening → Dockerization → Air-Gapped Distribution**

The AI Command Plane is intentionally late in the lifecycle. Before AI generates a contract, XORVA must already be capable of safely validating, publishing, rendering, and executing a manually authored contract.

---

# Phase 0 — Architecture Freeze and Engineering Foundation

## Purpose

Establish the architectural invariants, repository boundaries, terminology, development standards, and acceptance criteria before implementation begins.

### Task 0.1 — Define XORVA Architectural Invariants

**Input**

- Existing XORVA architecture
- Multi-tenant requirements
- Air-gap requirements
- Metadata-driven execution requirements

**Work**

Define non-negotiable platform rules covering:

- tenant isolation;
- contract immutability;
- no arbitrary SQL execution;
- no arbitrary JavaScript execution;
- capability allowlisting;
- contract versioning;
- user identity propagation;
- RLS enforcement;
- auditability;
- offline operation;
- deterministic execution.

**Output**

`Architecture Invariants` document.

**Done when**

Every future architecture decision can be checked against a written set of platform invariants.

---

### Task 0.2 — Define Core XORVA Terminology

**Input**

- Architecture model
- Metadata concepts

**Work**

Standardize terms such as:

- Tenant
- Module
- Entity
- Record
- Relationship
- Contract
- Contract Version
- Capability
- Action
- Workflow
- Execution Primitive
- Component Registry
- Command Plane
- Data Plane
- Certified Extension

**Output**

Canonical XORVA glossary.

**Done when**

The database, API, UI, and AI teams use identical terminology.

---

### Task 0.3 — Define Architecture Decision Record Process

**Input**

- Architecture governance requirements

**Work**

Define how significant architecture decisions are documented.

Examples:

- JSONB vs physical tables;
- shared DB vs isolated DB;
- workflow DSL design;
- RPC design;
- contract versioning;
- authentication strategy.

**Output**

ADR template and ADR directory.

**Done when**

Major architectural changes cannot occur without an ADR.

---

### Task 0.4 — Define Repository Boundaries

**Input**

- Next.js
- React Native
- PostgreSQL/Supabase
- Future Python AI system

**Work**

Define monorepo package boundaries.

Expected domains:

- web application;
- mobile application;
- metadata specification;
- contract compiler;
- runtime SDK;
- web component registry;
- mobile component registry;
- database;
- AI builder;
- deployment;
- security;
- tests.

**Output**

Approved repository architecture.

**Done when**

Every future component has a clearly defined ownership location.

---

### Task 0.5 — Define Environment Strategy

**Input**

Deployment requirements.

**Work**

Define:

- local development;
- CI;
- integration;
- staging;
- production SaaS;
- dedicated enterprise;
- sovereign/air-gap.

**Output**

Environment matrix.

**Done when**

Configuration differences between environments are explicitly known.

---

### Task 0.6 — Define Phase 1 Proof-of-Concept Domains

**Input**

Metadata engine goals.

**Work**

Select two deliberately different domains.

Recommended:

- Fleet Management
- Audit Management

**Output**

Two reference domain specifications.

**Done when**

The platform must prove both applications run without domain-specific backend models/controllers.

---

## Phase 0 Exit Gate

Proceed only when:

- architectural invariants are approved;
- terminology is frozen;
- repository boundaries are established;
- environment model is defined;
- Fleet and Audit reference domains are selected.

---

# Phase 1 — PostgreSQL and Supabase Foundation

## Purpose

Create the core persistence layer before any dynamic execution behavior exists.

---

### Task 1.1 — Establish PostgreSQL/Supabase Development Environment

**Input**

- Repository
- local development environment

**Work**

Create the database development lifecycle including:

- local PostgreSQL/Supabase;
- migration execution;
- database reset;
- seed execution;
- database test execution.

**Output**

Repeatable local database environment.

**Done when**

A developer can recreate XORVA's database from zero deterministically.

---

### Task 1.2 — Define PostgreSQL Schema Boundaries

**Input**

XORVA architecture.

**Work**

Separate logical schemas such as:

- core;
- metadata;
- application data;
- private/internal functions;
- public API functions;
- audit.

**Output**

Database namespace specification.

**Done when**

Every table/function has an intended schema and exposure level.

---

### Task 1.3 — Create Tenant Registry Model

**Input**

Tenant architecture.

**Work**

Define persistent representation for:

- tenant identity;
- tenant status;
- tenant slug;
- tenant settings;
- timestamps.

**Output**

Tenant persistence model.

**Done when**

A tenant can be uniquely identified and lifecycle-managed.

---

### Task 1.4 — Create Tenant Membership Model

**Input**

- tenant model;
- Supabase authentication identity.

**Work**

Define associations between:

- authenticated user;
- tenant;
- status;
- roles;
- permissions.

**Output**

Tenant membership persistence model.

**Done when**

One user can safely belong to one or more tenants.

---

### Task 1.5 — Define Generic Entity Record Envelope

**Input**

Metadata-driven storage requirements.

**Work**

Define stable columns such as:

- record ID;
- tenant ID;
- module key;
- entity key;
- contract version;
- workflow state;
- record version;
- JSONB payload;
- creation identity/time;
- update identity/time;
- archive state.

**Output**

Canonical entity record model.

**Done when**

Arbitrary business records can be represented without adding physical business tables.

---

### Task 1.6 — Define Generic Relationship Store

**Input**

Entity record model.

**Work**

Define relationship representation for:

- source record;
- source entity;
- target record;
- target entity;
- relationship type/key;
- tenant scope;
- optional metadata.

**Output**

Generic relationship model.

**Done when**

Logical foreign-key relationships can exist without generated physical tables.

---

### Task 1.7 — Define JSONB Storage Rules

**Input**

Entity model.

**Work**

Define what belongs:

**Outside JSONB**

- tenant ID;
- module;
- entity;
- workflow state;
- versioning;
- timestamps.

**Inside JSONB**

- tenant-defined business fields.

**Output**

JSONB storage standard.

**Done when**

Developers cannot arbitrarily choose where system-level fields live.

---

### Task 1.8 — Establish Baseline Index Strategy

**Input**

Expected access patterns.

**Work**

Define initial indexes for:

- tenant;
- module;
- entity;
- state;
- creation time;
- JSONB containment.

**Output**

Phase 1 indexing strategy.

**Done when**

Basic record filtering does not require full-table scans under expected POC loads.

---

### Task 1.9 — Define Record Versioning Strategy

**Input**

Concurrent ERP editing requirements.

**Work**

Define optimistic concurrency behavior.

**Output**

Record-version specification.

**Done when**

Concurrent updates cannot silently overwrite each other.

---

### Task 1.10 — Define Soft-Delete / Archive Semantics

**Input**

Auditability requirements.

**Work**

Specify:

- normal archive behavior;
- restore policy;
- visibility rules;
- physical deletion rules.

**Output**

Data lifecycle specification.

**Done when**

Normal users cannot accidentally destroy auditable business history.

---

## Phase 1 Exit Gate

Proceed only when:

- database initializes from zero;
- tenants exist;
- memberships exist;
- generic records exist;
- relationships exist;
- JSONB rules are frozen;
- record concurrency is defined.

---

# Phase 2 — Authentication, Authorization, and Tenant Isolation

## Purpose

Prove tenant isolation before exposing dynamic CRUD.

---

### Task 2.1 — Define Authentication Boundary

**Input**

Supabase Auth.

**Work**

Define how user identity reaches:

- Next.js;
- Supabase client;
- PostgreSQL;
- RLS;
- audit events.

**Output**

Identity propagation design.

**Done when**

The authenticated user remains identifiable all the way to PostgreSQL.

---

### Task 2.2 — Define Tenant Context Resolution

**Input**

Authenticated user and tenant membership.

**Work**

Determine how active tenant context is selected and verified.

**Output**

Tenant-context specification.

**Done when**

A request cannot simply claim an arbitrary tenant ID without membership verification.

---

### Task 2.3 — Define Permission Naming Convention

**Input**

Module/entity architecture.

**Work**

Define canonical permission patterns such as:

- module.entity.read;
- module.entity.create;
- module.entity.update;
- module.entity.delete;
- module.action.execute.

**Output**

Permission namespace standard.

**Done when**

Permissions can be deterministically derived from metadata.

---

### Task 2.4 — Implement Tenant Membership Security Functions

**Input**

Tenant/membership schema.

**Work**

Create internal authorization functions for:

- tenant membership;
- permissions;
- roles if retained.

**Output**

Central database authorization layer.

**Done when**

RLS policies do not duplicate complex membership logic.

---

### Task 2.5 — Apply RLS to Tenant-Scoped Tables

**Input**

All Phase 1 tables.

**Work**

Apply RLS to:

- tenant data;
- module contracts;
- relationships;
- audit data where appropriate.

**Output**

RLS-secured database.

**Done when**

Rows are inaccessible without authorized tenant context.

---

### Task 2.6 — Define Table Grants Separately from RLS

**Input**

RLS architecture.

**Work**

Determine permitted database operations for runtime roles.

**Output**

Grant matrix.

**Done when**

Runtime roles have only the minimum object-level privileges required.

---

### Task 2.7 — Protect Against Service-Role Runtime Usage

**Input**

Supabase runtime design.

**Work**

Establish policy forbidding RLS-bypassing credentials from ordinary application execution paths.

**Output**

Credential handling standard.

**Done when**

Tenant requests cannot execute using privileged backend credentials.

---

### Task 2.8 — Build Cross-Tenant Security Test Matrix

**Input**

RLS policies.

**Work**

Test:

- read;
- create;
- update;
- archive;
- relationships;
- contract access;
- aggregate access.

**Output**

Automated tenant-isolation test suite.

**Done when**

Tenant A cannot read or mutate Tenant B data under any tested runtime operation.

---

### Task 2.9 — Test Multi-Membership Scenarios

**Input**

Users belonging to multiple tenants.

**Work**

Validate tenant switching without data leakage.

**Output**

Multi-membership security tests.

**Done when**

Changing active tenant context never causes mixed results.

---

## Phase 2 Exit Gate

No metadata execution work begins until the cross-tenant isolation suite passes completely.

---

# Phase 3 — Metadata Contract Specification

## Purpose

Define the XORVA language before building an interpreter for it.

---

### Task 3.1 — Define Contract Root Structure

**Input**

Fleet metadata example.

**Work**

Define sections including:

- contract header;
- runtime policy;
- security model;
- schema definition;
- workflows;
- UI layout;
- actions;
- visualization nodes.

**Output**

XORVA Module Contract Specification v1.

**Done when**

Every contract has a deterministic top-level structure.

---

### Task 3.2 — Define Supported Field Types

**Input**

ERP data requirements.

**Work**

Define canonical field types.

Examples:

- string;
- number;
- integer;
- boolean;
- UUID;
- date;
- datetime;
- enum;
- object;
- array;
- relationship.

**Output**

Field-type specification.

**Done when**

Every supported field type has validation and rendering semantics.

---

### Task 3.3 — Define Field Constraints

**Input**

Field types.

**Work**

Specify:

- required;
- nullable;
- min/max;
- length;
- enum;
- pattern;
- uniqueness;
- defaults.

**Output**

Field validation specification.

**Done when**

Business field validation can be represented declaratively.

---

### Task 3.4 — Define Relationship Metadata

**Input**

Generic relationship storage.

**Work**

Specify:

- one-to-one;
- one-to-many;
- many-to-many;
- target entity;
- delete behavior;
- required relationship rules.

**Output**

Relationship contract specification.

**Done when**

Relationships can be defined independently of physical schema migrations.

---

### Task 3.5 — Define Workflow Metadata

**Input**

ERP lifecycle requirements.

**Work**

Define:

- initial state;
- allowed states;
- state transitions;
- transition permissions;
- preconditions.

**Output**

Workflow contract format.

**Done when**

Record lifecycle behavior can be described without backend controller code.

---

### Task 3.6 — Define UI Metadata

**Input**

Web/mobile rendering requirements.

**Work**

Specify:

- pages;
- blocks;
- grids;
- component IDs;
- icons;
- data sources;
- responsive behavior;
- forms;
- tables;
- dashboards;
- Kanban layouts.

**Output**

UI contract specification.

**Done when**

A complete basic application page can be represented as metadata.

---

### Task 3.7 — Define Action Hook Metadata

**Input**

CRUD and workflow requirements.

**Work**

Specify:

- action ID;
- label;
- icon;
- permission;
- confirmation;
- capability binding;
- inputs;
- response behavior;
- cache invalidation.

**Output**

Action contract specification.

**Done when**

UI actions can reference runtime capabilities without arbitrary executable code.

---

### Task 3.8 — Define Visualization Metadata

**Input**

Presentation/diagram requirements.

**Work**

Define nodes and edges for architecture visualizations.

**Output**

Visualization-node specification.

**Done when**

A contract can be transformed into a module diagram without inference.

---

### Task 3.9 — Define Metadata Extension Policy

**Input**

Long-term extensibility goals.

**Work**

Determine:

- reserved namespaces;
- vendor extensions;
- tenant extensions;
- compatibility behavior.

**Output**

Metadata extension standard.

**Done when**

Future metadata evolution does not require breaking existing contracts.

---

### Task 3.10 — Publish Contract JSON Schema v1

**Input**

Tasks 3.1–3.9.

**Work**

Convert specification into machine-validatable schema.

**Output**

Canonical XORVA Contract Schema v1.

**Done when**

A contract can objectively pass or fail structural validation.

---

## Phase 3 Exit Gate

Fleet and Audit contracts must both validate against the same contract specification.

---

# Phase 4 — Contract Registry and Lifecycle

## Purpose

Create immutable, versioned business application definitions.

---

### Task 4.1 — Create Module Contract Registry

**Input**

Contract schema.

**Work**

Store contracts by:

- tenant;
- module;
- version;
- lifecycle status.

**Output**

Persistent contract registry.

**Done when**

Multiple modules and versions can coexist.

---

### Task 4.2 — Define Contract Lifecycle States

**Input**

Release requirements.

**Work**

Define:

- draft;
- validated;
- staged;
- published;
- retired.

**Output**

Contract lifecycle model.

**Done when**

Contract deployment has explicit states.

---

### Task 4.3 — Enforce Published Contract Immutability

**Input**

Lifecycle model.

**Work**

Prevent published contract body mutation.

**Output**

Immutable contract history.

**Done when**

Changing a live module requires publishing a new version.

---

### Task 4.4 — Define Canonicalization

**Input**

JSON contract.

**Work**

Define deterministic representation for hashing and signing.

**Output**

Canonical contract serialization specification.

**Done when**

Equivalent contracts produce identical canonical representation.

---

### Task 4.5 — Define Contract Hashing

**Input**

Canonical contract.

**Work**

Generate integrity hash.

**Output**

Contract integrity mechanism.

**Done when**

Tampered contract content can be detected.

---

### Task 4.6 — Define Contract Compatibility Rules

**Input**

Versioning model.

**Work**

Classify changes as:

- backwards compatible;
- migration required;
- breaking;
- prohibited.

**Output**

Contract compatibility matrix.

**Done when**

Version upgrades have predictable semantics.

---

### Task 4.7 — Define Record-to-Contract Version Binding

**Input**

Generic entity storage.

**Work**

Persist the contract version under which each record was created.

**Output**

Version-aware record model.

**Done when**

Historical records remain interpretable after module upgrades.

---

### Task 4.8 — Define Rollback Strategy

**Input**

Multiple contract versions.

**Work**

Define how prior compatible versions are reactivated.

**Output**

Contract rollback procedure.

**Done when**

A failed release can be reverted without modifying historical versions.

---

## Phase 4 Exit Gate

The system can publish Fleet v1, publish Fleet v2, retain v1 history, and identify which contract version produced each record.

---

# Phase 5 — Deterministic Contract Compiler

## Purpose

Create the primary security boundary between generated metadata and runtime execution.

---

### Task 5.1 — Define Compiler Pipeline

**Input**

Contract specification.

**Work**

Define stages:

- parse;
- schema validation;
- semantic validation;
- security linting;
- dependency validation;
- canonicalization;
- publication artifact generation.

**Output**

Compiler architecture.

**Done when**

The publishing process is deterministic and documented.

---

### Task 5.2 — Implement Structural Validation

**Input**

Contract JSON Schema.

**Work**

Reject malformed contracts.

**Output**

Structural validator.

**Done when**

Invalid contract shapes cannot reach publication.

---

### Task 5.3 — Implement Entity Semantic Validation

**Input**

Schema definition.

**Work**

Validate:

- duplicate fields;
- unsupported types;
- invalid defaults;
- inconsistent required/nullability rules.

**Output**

Entity semantic validator.

**Done when**

Structurally valid but logically invalid schemas are rejected.

---

### Task 5.4 — Validate Relationship Graphs

**Input**

Relationship metadata.

**Work**

Check:

- referenced entities exist;
- target fields exist;
- relationship keys are unique;
- invalid cycles where prohibited.

**Output**

Relationship validator.

**Done when**

Broken references cannot be published.

---

### Task 5.5 — Validate Workflow Graphs

**Input**

Workflow metadata.

**Work**

Verify:

- initial state exists;
- transitions use valid states;
- unreachable states;
- invalid transition references.

**Output**

Workflow graph validator.

**Done when**

Invalid state machines cannot become runtime contracts.

---

### Task 5.6 — Validate Component References

**Input**

UI component registry.

**Work**

Reject unknown:

- page components;
- form controls;
- icons where restricted;
- data-source types.

**Output**

UI component validator.

**Done when**

Metadata cannot request arbitrary React components.

---

### Task 5.7 — Validate Capability References

**Input**

Capability registry.

**Work**

Reject unknown action capabilities.

**Output**

Capability validator.

**Done when**

Metadata cannot invent executable backend functions.

---

### Task 5.8 — Build Security Linter

**Input**

Entire contract.

**Work**

Reject metadata containing forbidden execution constructs.

Examples:

- arbitrary SQL;
- JavaScript;
- shell commands;
- filesystem commands;
- unknown RPCs;
- arbitrary HTTP targets.

**Output**

Contract security linter.

**Done when**

Metadata remains declarative.

---

### Task 5.9 — Validate Permissions

**Input**

Security model and actions.

**Work**

Verify:

- referenced permissions exist;
- action permissions are coherent;
- required entity permissions exist.

**Output**

Permission validator.

**Done when**

Contracts cannot publish internally inconsistent authorization rules.

---

### Task 5.10 — Produce Compiled Contract Artifact

**Input**

Validated contract.

**Work**

Generate canonical runtime artifact including:

- normalized metadata;
- computed defaults;
- capability bindings;
- integrity hash.

**Output**

Compiled contract package.

**Done when**

Runtime consumes compiler output rather than raw AI/user JSON.

---

## Phase 5 Exit Gate

Intentionally malformed or malicious contracts must consistently fail compilation.

---

# Phase 6 — Capability Registry and Certified Extensions Framework

## Purpose

Separate generic metadata behavior from trusted implementation logic.

---

### Task 6.1 — Define Capability Identifier Standard

**Input**

Runtime functions.

**Work**

Create names such as:

- core.entity.create.v1;
- core.entity.update.v1;
- core.transaction.execute.v1.

**Output**

Capability naming specification.

**Done when**

Capabilities have stable, versioned identifiers.

---

### Task 6.2 — Build Capability Registry

**Input**

Approved operations.

**Work**

Store mapping between:

- capability ID;
- implementation endpoint/RPC;
- version;
- safety classification;
- enabled state.

**Output**

Trusted capability registry.

**Done when**

Metadata can execute only registered capabilities.

---

### Task 6.3 — Define Capability Safety Classes

**Input**

Runtime risk model.

**Work**

Classify capabilities such as:

- generic;
- transactional;
- certified;
- privileged.

**Output**

Capability risk model.

**Done when**

Higher-risk operations can require stronger controls.

---

### Task 6.4 — Define Certified Extension Interface

**Input**

Regulatory and complex algorithms.

**Work**

Specify how future functionality such as VAT or Peppol plugs into the runtime.

**Output**

Certified extension architecture.

**Done when**

Complex business logic does not need to be forced into the metadata DSL.

---

### Task 6.5 — Define Capability Version Compatibility

**Input**

Contract versioning.

**Work**

Determine how capability upgrades affect existing contracts.

**Output**

Capability compatibility policy.

**Done when**

Updating an implementation cannot unexpectedly change historical contract behavior.

---

## Phase 6 Exit Gate

A contract can reference approved capabilities but cannot choose arbitrary backend implementation names.

---

# Phase 7 — Generic Data Execution Runtime

## Purpose

Implement CRUD without vertical-specific models.

---

### Task 7.1 — Define Generic Query Contract

**Input**

Generic entity model.

**Work**

Specify query inputs:

- tenant;
- module;
- entity;
- filtering;
- sorting;
- pagination.

**Output**

Query runtime specification.

**Done when**

All entity reads can use the same runtime interface.

---

### Task 7.2 — Implement Generic Record Creation Flow

**Input**

Compiled entity definition.

**Work**

Define execution stages:

- authenticate;
- authorize;
- load contract;
- validate payload;
- create record;
- audit;
- return result.

**Output**

Generic create operation.

**Done when**

Fleet and Audit records use the exact same creation mechanism.

---

### Task 7.3 — Implement Generic Update Flow

**Input**

Existing record and metadata.

**Work**

Support:

- validation;
- authorization;
- optimistic locking;
- audit trail.

**Output**

Generic update operation.

**Done when**

No domain-specific update controller exists.

---

### Task 7.4 — Implement Archive Flow

**Input**

Existing record.

**Work**

Perform permission-aware soft deletion.

**Output**

Generic archive operation.

**Done when**

Business records can be removed from active workflows without destroying history.

---

### Task 7.5 — Implement Generic Relationship Operations

**Input**

Relationship metadata.

**Work**

Support relationship creation/removal under metadata rules.

**Output**

Relationship runtime.

**Done when**

Entities can reference each other without hardcoded relationship handlers.

---

### Task 7.6 — Implement Runtime Payload Validation

**Input**

Compiled schema.

**Work**

Apply validation before persistence.

**Output**

Runtime validator.

**Done when**

Invalid business payloads cannot enter storage through normal APIs.

---

### Task 7.7 — Add Database-Side Validation Layer

**Input**

Runtime validation specification.

**Work**

Enforce essential validation close to persistence.

**Output**

Defense-in-depth validation.

**Done when**

Bypassing the Next.js layer does not trivially bypass critical record constraints.

---

### Task 7.8 — Implement Pagination and Limits

**Input**

Query runtime.

**Work**

Define safe defaults and maximums.

**Output**

Bounded generic querying.

**Done when**

Metadata cannot accidentally request unbounded datasets.

---

### Task 7.9 — Implement Generic Aggregations

**Input**

Dashboard requirements.

**Work**

Support safe operations such as:

- count;
- sum;
- average;
- grouped count.

**Output**

Metadata-driven aggregation runtime.

**Done when**

Metrics cards can obtain data without domain-specific endpoints.

---

## Phase 7 Exit Gate

Fleet and Audit CRUD operate through identical runtime interfaces.

---

# Phase 8 — Workflow and Transaction Execution Engine

## Purpose

Move beyond CRUD into real ERP business execution.

---

### Task 8.1 — Define XORVA Execution Primitive Set

**Input**

Fleet workflow examples.

**Work**

Define minimal allowed primitives.

Examples:

- assert state;
- assert field;
- set state;
- patch payload;
- create relation;
- remove relation;
- create record.

**Output**

Execution DSL v1.

**Done when**

Every primitive has precise deterministic semantics.

---

### Task 8.2 — Explicitly Define Forbidden Primitives

**Input**

Threat model.

**Work**

Exclude:

- arbitrary SQL;
- arbitrary code;
- arbitrary HTTP;
- shell execution.

**Output**

DSL security boundary.

**Done when**

The workflow language cannot become an uncontrolled programming environment.

---

### Task 8.3 — Build Action Resolver

**Input**

Action key and published contract.

**Work**

Resolve action definitions server-side.

**Output**

Trusted action lookup.

**Done when**

The browser cannot submit its own execution plan.

---

### Task 8.4 — Build Input Resolver

**Input**

Action definition and request inputs.

**Work**

Resolve:

- record references;
- form inputs;
- context variables.

**Output**

Normalized action inputs.

**Done when**

Every action input is validated before execution.

---

### Task 8.5 — Implement Preconditions

**Input**

Workflow action.

**Work**

Evaluate declared state/field conditions.

**Output**

Precondition engine.

**Done when**

Invalid transitions stop before any mutation occurs.

---

### Task 8.6 — Implement Atomic Action Transactions

**Input**

Validated execution plan.

**Work**

Execute all action steps inside one transaction.

**Output**

Atomic workflow execution.

**Done when**

Partial business-state changes cannot survive failed actions.

---

### Task 8.7 — Implement Record Locking Strategy

**Input**

Multi-record transactions.

**Work**

Define locking order and concurrency behavior.

**Output**

Concurrent action safety.

**Done when**

Two users cannot successfully assign the same available resource concurrently.

---

### Task 8.8 — Implement Idempotency

**Input**

Retryable business actions.

**Work**

Track idempotency keys by tenant/action.

**Output**

Idempotent action execution.

**Done when**

A client retry cannot duplicate a transactional business operation.

---

### Task 8.9 — Implement Workflow Audit Events

**Input**

Action execution.

**Work**

Capture:

- actor;
- action;
- before state;
- after state;
- affected records.

**Output**

Business action audit trail.

**Done when**

A workflow action can be reconstructed after execution.

---

### Task 8.10 — Validate Fleet Dispatch Scenario

**Input**

Fleet metadata.

**Work**

Test atomic mutation across:

- trip;
- vehicle;
- driver.

**Output**

Reference transactional workflow.

**Done when**

Fleet dispatch works without Fleet-specific backend implementation.

---

## Phase 8 Exit Gate

XORVA must successfully execute at least one multi-entity transactional workflow entirely from metadata.

---

# Phase 9 — Next.js / Node Core Execution Engine

## Purpose

Expose the metadata runtime as a safe application API.

---

### Task 9.1 — Define Runtime API Surface

**Input**

Generic data runtime.

**Work**

Define generic route patterns for:

- query;
- create;
- update;
- archive;
- action execution;
- contract retrieval.

**Output**

Runtime API specification.

**Done when**

Module-specific API routes are unnecessary.

---

### Task 9.2 — Implement Authenticated Supabase Server Client

**Input**

User session.

**Work**

Ensure requests execute as the end user.

**Output**

RLS-preserving server data client.

**Done when**

Next.js does not bypass database tenancy protections.

---

### Task 9.3 — Implement Tenant Context Middleware

**Input**

Request and user membership.

**Work**

Resolve/validate current tenant.

**Output**

Trusted request tenant context.

**Done when**

Invalid tenant selection fails before data execution.

---

### Task 9.4 — Implement Generic Entity Route

**Input**

Module and entity identifiers.

**Work**

Load the published contract dynamically.

**Output**

Model-independent API routing.

**Done when**

Adding a new metadata entity requires no new route.

---

### Task 9.5 — Implement API Validation Layer

**Input**

Compiled contract and payload.

**Work**

Validate incoming API requests.

**Output**

Request-validation boundary.

**Done when**

Malformed payloads receive predictable validation errors.

---

### Task 9.6 — Implement Generic Error Model

**Input**

Database/runtime errors.

**Work**

Standardize errors:

- validation;
- forbidden;
- not found;
- conflict;
- workflow error;
- system error.

**Output**

XORVA runtime error format.

**Done when**

Web and mobile clients can handle failures generically.

---

### Task 9.7 — Implement Request Correlation IDs

**Input**

Incoming requests.

**Work**

Assign traceable request IDs through:

- API;
- database;
- audit;
- logs.

**Output**

End-to-end request correlation.

**Done when**

A failed operation can be traced across the stack.

---

### Task 9.8 — Add Runtime Contract Cache

**Input**

Published immutable contracts.

**Work**

Cache safely by:

- tenant;
- module;
- version/hash.

**Output**

Efficient metadata retrieval.

**Done when**

Repeated UI/API operations do not repeatedly parse identical contracts unnecessarily.

---

## Phase 9 Exit Gate

A new metadata module can be queried and mutated through Next.js without creating a new controller.

---

# Phase 10 — Headless Web UI Runtime

## Purpose

Turn metadata contracts into usable web applications.

---

### Task 10.1 — Define Web Component Registry

**Input**

UI contract.

**Work**

Create approved component identifiers.

Examples:

- DataGrid;
- MetricsCard;
- DynamicForm;
- KanbanBoard;
- Timeline.

**Output**

Web component registry specification.

**Done when**

Metadata can only request known components.

---

### Task 10.2 — Define Form Control Registry

**Input**

Metadata field types.

**Work**

Map field types/components to trusted form controls.

**Output**

Form registry.

**Done when**

All Phase 1 field types have renderable form controls.

---

### Task 10.3 — Build Dynamic Page Renderer

**Input**

Page metadata.

**Work**

Interpret:

- route;
- block list;
- grid coordinates;
- component references.

**Output**

Generic page runtime.

**Done when**

A page appears without a hand-written module page component.

---

### Task 10.4 — Build Dynamic Form Renderer

**Input**

Entity field metadata.

**Work**

Render:

- labels;
- inputs;
- required states;
- read-only fields;
- enums;
- relationships.

**Output**

Metadata-driven form.

**Done when**

Fleet and Audit forms use one renderer.

---

### Task 10.5 — Build Dynamic Data Grid

**Input**

Entity/data-grid metadata.

**Work**

Support:

- columns;
- sorting;
- filtering;
- pagination;
- row actions;
- toolbar actions.

**Output**

Generic data grid.

**Done when**

New entity lists require metadata only.

---

### Task 10.6 — Build Metrics Card Renderer

**Input**

Aggregate metadata.

**Work**

Map data source to metrics display.

**Output**

Generic metric component.

**Done when**

Dashboard KPIs require no custom API/controller.

---

### Task 10.7 — Build Kanban Renderer

**Input**

Workflow metadata.

**Work**

Render records grouped by state.

**Output**

Generic Kanban component.

**Done when**

Fleet dispatch and Audit workflows can share it.

---

### Task 10.8 — Implement Action Hook Dispatcher

**Input**

UI action metadata.

**Work**

Bind trusted action identifiers to API execution.

**Output**

Metadata-driven buttons/actions.

**Done when**

Buttons do not contain domain-specific business logic.

---

### Task 10.9 — Implement Permission-Aware UI

**Input**

User permissions.

**Work**

Control visibility/enabled state of:

- pages;
- fields;
- actions.

**Output**

Authorization-aware presentation.

**Done when**

Unauthorized actions are not presented as available.

---

### Task 10.10 — Implement Responsive Grid Engine

**Input**

Grid metadata.

**Work**

Support responsive page layouts.

**Output**

Metadata-driven responsive rendering.

**Done when**

Layouts remain usable across normal desktop/tablet breakpoints.

---

### Task 10.11 — Implement Runtime Error States

**Input**

Generic API error model.

**Work**

Render:

- permission failures;
- validation errors;
- conflicts;
- loading failures;
- unsupported components.

**Output**

Generic error UX.

**Done when**

Module code does not implement its own error behavior.

---

### Task 10.12 — Prove Hot Metadata Change

**Input**

Fleet v1.

**Work**

Add a new field/page element through Fleet v2.

**Output**

Visible UI change without module-specific code.

**Done when**

Founder demo demonstrates contract-driven change.

---

## Phase 10 Exit Gate

Fleet and Audit render through identical UI runtime code.

---

# Phase 11 — React Native / Expo Runtime

## Purpose

Prove the metadata model is presentation-platform independent.

---

### Task 11.1 — Define Mobile Component Registry

**Input**

Web registry and contract UI semantics.

**Work**

Map contract component IDs to mobile equivalents.

**Output**

Mobile component registry.

**Done when**

Contracts do not contain React Native-specific business metadata.

---

### Task 11.2 — Implement Mobile Dynamic Form

**Input**

Field metadata.

**Output**

Mobile form runtime.

**Done when**

The same Fleet form contract renders on mobile.

---

### Task 11.3 — Implement Mobile Entity List

**Input**

DataGrid metadata.

**Output**

Responsive mobile record-list representation.

**Done when**

DataGrid metadata can degrade appropriately for mobile.

---

### Task 11.4 — Implement Mobile Action Dispatcher

**Input**

Action hooks.

**Output**

Mobile business-action execution.

**Done when**

Mobile uses the same server capabilities as web.

---

### Task 11.5 — Define Mobile Offline Policy

**Input**

ERP mobile requirements.

**Work**

Decide Phase 1 policy for:

- cached metadata;
- cached records;
- deferred writes;
- no-offline-write if chosen initially.

**Output**

Offline semantics specification.

**Done when**

Disconnected behavior is predictable.

---

## Phase 11 Exit Gate

At least one complete Fleet workflow uses the same contract on web and mobile.

---

# Phase 12 — Audit, Observability, and Operational Integrity

## Purpose

Make the platform supportable and enterprise-auditable.

---

### Task 12.1 — Define Audit Event Schema

**Input**

Compliance requirements.

**Work**

Capture:

- tenant;
- actor;
- action;
- resource;
- old value;
- new value;
- timestamp;
- request ID.

**Output**

Audit event specification.

**Done when**

Business mutations can be independently reconstructed.

---

### Task 12.2 — Define Technical Log Schema

**Input**

Operations requirements.

**Work**

Capture:

- request ID;
- tenant ID;
- module;
- entity;
- action;
- latency;
- result.

**Output**

Structured logging standard.

**Done when**

Technical diagnostics are separate from business audits.

---

### Task 12.3 — Define Sensitive Data Redaction

**Input**

Field classifications.

**Work**

Determine which values must never appear in logs.

**Output**

Logging/redaction policy.

**Done when**

Confidential values are protected by default.

---

### Task 12.4 — Implement Runtime Metrics

**Input**

Execution engine.

**Work**

Measure:

- API latency;
- database latency;
- action duration;
- error rates;
- query counts.

**Output**

Operational metrics.

**Done when**

Runtime performance is observable.

---

### Task 12.5 — Implement Health and Readiness Model

**Input**

Platform dependencies.

**Output**

Health-check specification.

**Done when**

Orchestration can distinguish healthy, degraded, and unavailable services.

---

### Task 12.6 — Define Backup Requirements

**Input**

Database/data architecture.

**Work**

Specify:

- backup frequency;
- retention;
- restoration;
- encryption;
- air-gap handling.

**Output**

Backup policy.

**Done when**

Recovery expectations are explicit.

---

### Task 12.7 — Perform Restore Test

**Input**

Backup.

**Output**

Restored XORVA environment.

**Done when**

Recovery has been demonstrated rather than assumed.

---

## Phase 12 Exit Gate

The platform is diagnosable, auditable, and recoverable before AI automation begins.

---

# Phase 13 — Performance and Projection Indexing

## Purpose

Ensure dynamic JSONB storage remains practical as data volume grows.

---

### Task 13.1 — Define Representative Data Loads

**Input**

Fleet and Audit use cases.

**Work**

Create expected dataset sizes.

**Output**

Performance workload specification.

**Done when**

Performance requirements are measurable.

---

### Task 13.2 — Benchmark JSONB Query Patterns

**Input**

Representative data.

**Work**

Measure:

- equality filters;
- pagination;
- workflow-state filtering;
- relationship access;
- aggregates.

**Output**

Baseline performance report.

**Done when**

Known bottlenecks are quantified.

---

### Task 13.3 — Define Projection Index Model

**Input**

JSONB benchmark results.

**Work**

Design typed projection values for frequently queried dynamic fields.

**Output**

Projection-index architecture.

**Done when**

Metadata can request efficient indexing without business-table migrations.

---

### Task 13.4 — Add Compiler Index Directives

**Input**

Contract field metadata.

**Output**

Validated metadata-driven index requests.

**Done when**

Contracts can specify approved index strategies.

---

### Task 13.5 — Implement Projection Lifecycle

**Input**

Record mutations.

**Work**

Ensure projections stay synchronized.

**Output**

Projection update mechanism.

**Done when**

Indexed values always correspond to business payloads.

---

### Task 13.6 — Re-run Benchmarks

**Input**

Projection indexing.

**Output**

Before/after performance report.

**Done when**

Target query workloads meet POC performance thresholds.

---

# Phase 14 — AI Command Plane Foundation

## Purpose

Only now automate production of contracts.

---

### Task 14.1 — Define AI Command Plane Security Boundary

**Input**

Compiler/publishing architecture.

**Work**

Ensure AI cannot directly:

- mutate production data;
- publish without validation;
- execute SQL;
- access privileged database credentials.

**Output**

AI trust-boundary architecture.

**Done when**

AI compromise does not equal runtime compromise.

---

### Task 14.2 — Define Requirement Intake Format

**Input**

Client discovery process.

**Work**

Standardize representation of:

- business objects;
- fields;
- roles;
- workflows;
- dashboards;
- integrations;
- compliance requirements.

**Output**

Structured requirement model.

**Done when**

Raw client conversations can be normalized into deterministic inputs.

---

### Task 14.3 — Define Agent Responsibilities

**Input**

Command-plane pipeline.

**Work**

Separate responsibilities such as:

- requirements analysis;
- domain modeling;
- UI planning;
- workflow planning;
- security planning;
- test planning.

**Output**

Agent responsibility matrix.

**Done when**

No agent has an undefined or unrestricted role.

---

### Task 14.4 — Build Domain Modeling Agent

**Input**

Normalized requirements.

**Output**

Candidate entities, fields, and relationships.

**Done when**

The output is contract-shaped but not publishable directly.

---

### Task 14.5 — Build Workflow Planning Agent

**Input**

Business processes.

**Output**

Candidate workflow definitions/actions.

**Done when**

Proposed workflows use only XORVA DSL concepts.

---

### Task 14.6 — Build UI Planning Agent

**Input**

Requirements and domain model.

**Output**

Candidate pages, grids, forms, dashboards.

**Done when**

Output references only approved UI primitives.

---

### Task 14.7 — Build Permission Planning Agent

**Input**

Roles and capabilities.

**Output**

Candidate permission model.

**Done when**

Every proposed action has explicit authorization requirements.

---

### Task 14.8 — Build Contract Assembly Stage

**Input**

Agent outputs.

**Output**

Candidate XORVA contract.

**Done when**

Multiple planning outputs produce one structured artifact.

---

### Task 14.9 — Integrate Deterministic Compiler

**Input**

Candidate AI contract.

**Output**

Pass/fail compiler result.

**Done when**

AI cannot bypass any compiler validation rule.

---

### Task 14.10 — Implement AI Repair Loop

**Input**

Compiler errors.

**Work**

Return structured validation failures to agents.

**Output**

Corrected candidate contract.

**Done when**

Agents repair metadata rather than asking runtime to tolerate invalid metadata.

---

### Task 14.11 — Generate Contract Test Scenarios

**Input**

Validated contract.

**Output**

Automated behavioral test plan.

**Done when**

Generated modules include expected success/failure cases.

---

### Task 14.12 — Add Human Approval Gate

**Input**

Compiled contract and generated preview.

**Output**

Explicit publish approval.

**Done when**

AI cannot independently promote production contracts.

---

### Task 14.13 — Implement Narrow Publishing Service

**Input**

Approved compiled contract.

**Output**

Published immutable contract version.

**Done when**

Command Plane only has access to a constrained publication API.

---

## Phase 14 Exit Gate

A natural-language requirement can produce a valid module contract, but only the deterministic compiler and explicit approval process can publish it.

---

# Phase 15 — Metadata Studio and Human Builder

## Purpose

Ensure XORVA remains usable without AI, especially in government deployments.

---

### Task 15.1 — Build Contract Viewer

**Input**

Published/draft contracts.

**Output**

Human-readable metadata inspection UI.

**Done when**

Engineers/admins can inspect a contract without reading raw JSON.

---

### Task 15.2 — Build Schema Editor

**Input**

Draft contract.

**Output**

Manual entity/field editor.

**Done when**

A module can be created without AI.

---

### Task 15.3 — Build UI Layout Editor

**Input**

UI metadata.

**Output**

Visual page-layout editor.

**Done when**

Users can rearrange approved components without editing JSON.

---

### Task 15.4 — Build Workflow Editor

**Input**

Workflow metadata.

**Output**

State/action editor.

**Done when**

Workflow design does not require hand-editing JSON.

---

### Task 15.5 — Integrate Live Contract Validation

**Input**

Draft metadata.

**Output**

Immediate compiler feedback.

**Done when**

Invalid changes are visible before publication.

---

### Task 15.6 — Build Contract Diff Viewer

**Input**

Two contract versions.

**Output**

Human-readable schema/UI/workflow changes.

**Done when**

Reviewers can understand precisely what a new contract changes.

---

### Task 15.7 — Build Publish Approval Screen

**Input**

Validated contract.

**Output**

Human-controlled contract release process.

**Done when**

Human-only deployment is fully viable.

---

# Phase 16 — Security Hardening and Government Readiness

## Purpose

Prepare XORVA for serious enterprise and government security review.

---

### Task 16.1 — Create Formal Threat Model

**Input**

Complete runtime architecture.

**Work**

Threat-model:

- tenant boundaries;
- metadata injection;
- AI command plane;
- supply chain;
- authentication;
- database;
- container deployment;
- secrets.

**Output**

Formal threat model.

**Done when**

Major assets, attack vectors, mitigations, and residual risks are documented.

---

### Task 16.2 — Perform Metadata Injection Testing

**Input**

Compiler/runtime.

**Work**

Attempt malicious:

- SQL;
- JS;
- URLs;
- component identifiers;
- expressions;
- capabilities.

**Output**

Metadata security test report.

**Done when**

Execution boundaries withstand adversarial contracts.

---

### Task 16.3 — Perform RLS Adversarial Testing

**Input**

Tenant security model.

**Output**

Security test report.

**Done when**

Known RLS bypass attempts through application interfaces fail.

---

### Task 16.4 — Define Secrets Architecture

**Input**

Integration requirements.

**Work**

Separate secret references from metadata.

**Output**

Secrets management architecture.

**Done when**

Raw credentials/private keys are not stored inside normal contracts or business records.

---

### Task 16.5 — Define Encryption Requirements

**Input**

Security classification.

**Work**

Specify:

- TLS;
- database storage encryption;
- backup encryption;
- secret encryption;
- offline-bundle integrity.

**Output**

Encryption standard.

**Done when**

Encryption expectations are explicit across deployment models.

---

### Task 16.6 — Harden Database Roles

**Input**

Production database.

**Output**

Least-privilege role model.

**Done when**

No application role has unnecessary superuser/BYPASSRLS capabilities.

---

### Task 16.7 — Harden Container Runtime

**Input**

Application containers.

**Work**

Define:

- non-root execution;
- read-only filesystems where practical;
- resource limits;
- dropped capabilities;
- health checks.

**Output**

Container security baseline.

**Done when**

Containers conform to the agreed hardening profile.

---

### Task 16.8 — Produce Software Bill of Materials

**Input**

Built artifacts.

**Output**

SBOM.

**Done when**

All distributed software dependencies can be enumerated.

---

### Task 16.9 — Implement Artifact Signing

**Input**

Containers/contracts/release bundles.

**Output**

Verifiable signatures.

**Done when**

Customers can verify artifact authenticity offline.

---

### Task 16.10 — Define Security Patch Process

**Input**

Dependencies and deployments.

**Output**

Vulnerability-response policy.

**Done when**

Cloud and air-gapped customers have an update mechanism.

---

## Phase 16 Exit Gate

Security review can evaluate XORVA as a defined product rather than an evolving prototype.

---

# Phase 17 — SaaS Docker and Cloud Deployment

## Purpose

Package the platform into production-grade deployable services.

---

### Task 17.1 — Define Runtime Container Boundaries

**Input**

Complete platform.

**Work**

Separate containers/services such as:

- web/API;
- workers where needed;
- Supabase components for self-hosting.

**Output**

Container architecture.

**Done when**

Each container has a clearly defined responsibility.

---

### Task 17.2 — Build Reproducible Application Images

**Input**

Applications.

**Output**

Versioned OCI images.

**Done when**

Identical source/dependencies produce controlled release artifacts.

---

### Task 17.3 — Define Container Configuration Contract

**Input**

Environment matrix.

**Output**

Documented environment variables/secrets/configuration.

**Done when**

Deployments require no hidden manual configuration.

---

### Task 17.4 — Define AWS SaaS Network Architecture

**Input**

Fargate/ALB requirements.

**Output**

Cloud network architecture.

**Done when**

Ingress, private networks, database access, and outbound access are explicit.

---

### Task 17.5 — Deploy Web/API to ECS Fargate

**Input**

Container images.

**Output**

Running SaaS runtime.

**Done when**

XORVA runs behind the designated load balancer.

---

### Task 17.6 — Configure Production Database Topology

**Input**

SaaS database requirements.

**Output**

Persistent production PostgreSQL architecture.

**Done when**

Application containers remain stateless while database persistence/backup is independently managed.

---

### Task 17.7 — Add Cloud Observability

**Input**

Structured logs and metrics.

**Output**

Production operational dashboards/alerts.

**Done when**

Failures and performance degradation are detectable.

---

### Task 17.8 — Validate Deployment Rollback

**Input**

Previous/current releases.

**Output**

Tested rollback procedure.

**Done when**

A faulty application release can be reverted safely.

---

## Phase 17 Exit Gate

XORVA operates as a production-like SaaS system using packaged artifacts.

---

# Phase 18 — Self-Hosted and Air-Gapped Deployment

## Purpose

Make the same XORVA runtime operable with no mandatory external connectivity.

---

### Task 18.1 — Inventory All External Dependencies

**Input**

Complete runtime.

**Work**

Identify every dependency on:

- public APIs;
- fonts;
- CDNs;
- telemetry;
- authentication;
- package repositories;
- AI APIs;
- map tiles;
- license servers.

**Output**

External dependency inventory.

**Done when**

Every outbound requirement is known.

---

### Task 18.2 — Eliminate Mandatory Runtime Internet Dependencies

**Input**

Dependency inventory.

**Output**

Offline-capable runtime.

**Done when**

Core XORVA operation requires no internet connection.

---

### Task 18.3 — Define Self-Hosted Supabase Topology

**Input**

Supabase/PostgreSQL requirements.

**Output**

On-prem database/service topology.

**Done when**

Required services can run entirely inside the customer's network.

---

### Task 18.4 — Package Local Static Assets

**Input**

Web/mobile asset requirements.

**Output**

Offline fonts/icons/static resources.

**Done when**

UI rendering does not contact external CDNs.

---

### Task 18.5 — Define Air-Gapped Identity Options

**Input**

Government IAM requirements.

**Work**

Support appropriate local identity integration patterns.

**Output**

Offline authentication architecture.

**Done when**

XORVA does not require a public identity provider.

---

### Task 18.6 — Build Offline Release Bundle

**Input**

Signed application artifacts.

**Package**

- images;
- migration bundle;
- configuration templates;
- contract schemas;
- SBOM;
- signatures;
- operational scripts;
- documentation.

**Output**

Air-gap installation bundle.

**Done when**

A disconnected customer receives everything required for installation.

---

### Task 18.7 — Build Offline Installer Procedure

**Input**

Release bundle.

**Output**

Repeatable installation workflow.

**Done when**

A clean isolated server environment can install XORVA without network access.

---

### Task 18.8 — Build Offline Upgrade Procedure

**Input**

Existing installation + new signed bundle.

**Output**

Versioned upgrade workflow.

**Done when**

A disconnected system can be safely upgraded.

---

### Task 18.9 — Build Offline Rollback Procedure

**Input**

Failed upgrade.

**Output**

Rollback workflow.

**Done when**

Previous supported runtime can be restored.

---

### Task 18.10 — Define On-Prem Backup Strategy

**Input**

Customer-owned PostgreSQL.

**Output**

Local backup/restore procedures.

**Done when**

No cloud backup service is required.

---

### Task 18.11 — Validate Air-Gap Network Isolation

**Input**

Installed deployment.

**Work**

Disable all outbound network access.

**Output**

Network-isolation test report.

**Done when**

Core XORVA continues operating normally.

---

### Task 18.12 — Validate Offline AI Strategy

**Input**

AI Command Plane requirements.

**Options**

- AI disabled;
- local customer-hosted model;
- human Metadata Studio.

**Output**

Air-gap builder strategy.

**Done when**

The data plane never depends on cloud AI.

---

## Phase 18 Exit Gate

A clean disconnected environment can install, boot, operate, back up, upgrade, and restore XORVA without accessing the public internet.

---

# Phase 19 — End-to-End Platform Validation

## Purpose

Prove that XORVA satisfies the original architectural proposition.

---

### Task 19.1 — Fleet End-to-End Test

**Input**

Fleet contract.

**Validate**

- schema;
- forms;
- lists;
- workflows;
- dashboard;
- audit;
- RLS.

**Output**

Fleet acceptance report.

**Done when**

Fleet operates without vertical-specific backend models/controllers/pages.

---

### Task 19.2 — Audit Module End-to-End Test

**Input**

Audit contract.

**Output**

Second-domain acceptance report.

**Done when**

The same execution engine supports a materially different vertical.

---

### Task 19.3 — Zero-Code Vertical Test

**Input**

Third lightweight business domain.

**Work**

Attempt implementation through metadata only.

**Output**

Architecture generalization report.

**Done when**

No runtime modification is necessary for standard schema/UI/workflow requirements.

---

### Task 19.4 — Contract Upgrade Test

**Input**

Module v1 and v2.

**Output**

Version-upgrade acceptance report.

**Done when**

Historical records remain valid while new metadata becomes active.

---

### Task 19.5 — Tenant Isolation Regression

**Input**

Full stack.

**Output**

Final multi-tenant security report.

**Done when**

UI, API, RPC, and database layers all preserve tenant isolation.

---

### Task 19.6 — Failure Recovery Test

**Input**

Simulated interrupted transactions/services.

**Output**

Recovery report.

**Done when**

Business state remains consistent after controlled failures.

---

### Task 19.7 — AI-Generated Module Test

**Input**

Natural-language requirements.

**Output**

AI-generated validated contract.

**Done when**

AI can create a module without bypassing compiler controls.

---

### Task 19.8 — Air-Gapped Acceptance Test

**Input**

Signed offline package.

**Output**

Final disconnected-deployment report.

**Done when**

Entire core platform functions without internet access.

---

# Phase 20 — Production Readiness and Launch Governance

## Purpose

Establish the operating discipline required to treat XORVA as an enterprise platform.

---

### Task 20.1 — Establish Contract Governance

**Input**

Contract lifecycle.

**Output**

Approval/ownership policies.

**Done when**

Production metadata changes have accountable owners and reviewers.

---

### Task 20.2 — Establish Capability Governance

**Input**

Capability registry.

**Output**

Process for introducing/upgrading certified capabilities.

**Done when**

Sensitive runtime operations cannot appear informally.

---

### Task 20.3 — Establish Database Migration Governance

**Input**

Core schema.

**Output**

Migration/review/rollback policy.

**Done when**

Core database evolution is controlled.

---

### Task 20.4 — Establish Release Versioning

**Input**

Application, compiler, contract, capability versions.

**Output**

XORVA release-version policy.

**Done when**

Compatibility can be reasoned about across all components.

---

### Task 20.5 — Establish Support Diagnostics

**Input**

Observability architecture.

**Output**

Support/runbook procedures.

**Done when**

Operational failures have documented investigation paths.

---

### Task 20.6 — Establish Incident Response

**Input**

Threat model and operations.

**Output**

Incident-response process.

**Done when**

Security/availability incidents have clear escalation procedures.

---

### Task 20.7 — Establish Upgrade Compatibility Matrix

**Input**

All versioned subsystems.

**Output**

Compatibility matrix covering:

- runtime;
- compiler;
- contract format;
- capabilities;
- database version.

**Done when**

Cloud and on-prem upgrade paths are predictable.

---

### Task 20.8 — Production Launch Gate

**Input**

All previous phase exit reports.

**Output**

Formal production-readiness decision.

**Done when**

All mandatory architecture, security, deployment, recovery, and isolation criteria have passed.

---

# Master Dependency Sequence

The practical implementation order is:

```text
Phase 0
Architecture Foundation
        ↓
Phase 1
PostgreSQL / Supabase Foundation
        ↓
Phase 2
Authentication / RLS / Tenant Isolation
        ↓
Phase 3
Metadata Contract Specification
        ↓
Phase 4
Contract Registry / Versioning
        ↓
Phase 5
Deterministic Contract Compiler
        ↓
Phase 6
Capability Registry
        ↓
Phase 7
Generic Data Runtime
        ↓
Phase 8
Workflow / Transaction Engine
        ↓
Phase 9
Next.js Execution API
        ↓
Phase 10
Dynamic Web UI
        ↓
Phase 11
Mobile Runtime
        ↓
Phase 12
Audit / Observability / Recovery
        ↓
Phase 13
Performance / Projection Indexing
        ↓
Phase 14
AI Command Plane
        ↓
Phase 15
Human Metadata Studio
        ↓
Phase 16
Security / Government Hardening
        ↓
Phase 17
SaaS Docker / Cloud Deployment
        ↓
Phase 18
Self-Hosted / Air-Gapped Deployment
        ↓
Phase 19
End-to-End Validation
        ↓
Phase 20
Production Governance
```

# Critical Milestones

## Milestone A — Secure Data Plane

Reached after **Phase 2**.

XORVA has:

- tenant storage;
- JSONB business records;
- memberships;
- strict RLS;
- tested tenant isolation.

No dynamic runtime should proceed before this milestone.

---

## Milestone B — XORVA Language Exists

Reached after **Phase 5**.

XORVA now has:

- a formal contract specification;
- versioned contracts;
- a deterministic compiler;
- security validation.

At this stage, XORVA has effectively defined its own declarative application language.

---

## Milestone C — XORVA Execution Engine Exists

Reached after **Phase 9**.

XORVA can:

- create arbitrary entities;
- query arbitrary entities;
- update them;
- relate them;
- execute workflows;
- enforce permissions;
- expose generic APIs.

No vertical-specific controllers are required.

This is the first major platform milestone.

---

## Milestone D — XORVA Is Visibly Self-Building

Reached after **Phase 10**.

A metadata contract produces:

- pages;
- forms;
- tables;
- dashboards;
- workflow boards;
- actions.

At this point the founder can visibly see the core thesis working.

---

## Milestone E — XORVA Is Platform-Independent

Reached after **Phase 11**.

The same business contract powers:

- Next.js web;
- React Native mobile.

This validates the separation between business intent and presentation implementation.

---

## Milestone F — AI Becomes Safe to Add

Reached after **Phase 13**.

Only here should the AI Command Plane begin.

The AI is now generating input for an already constrained machine instead of participating in the machine's security model.

---

## Milestone G — XORVA Builds Applications from Intent

Reached after **Phase 14**.

The lifecycle becomes:

```text
Human requirements
        ↓
AI planning
        ↓
Candidate XORVA contract
        ↓
Deterministic compiler
        ↓
Human approval
        ↓
Published contract
        ↓
Existing runtime
        ↓
Working application
```

---

## Milestone H — Government-Ready Deployment Model

Reached after **Phase 18**.

XORVA can run:

- cloud SaaS;
- dedicated enterprise;
- fully disconnected on-premises.

The business contract and execution engine remain the same across all three.

---

# Recommended Coding Start Point

When implementation begins, **Phase 1 should remain deliberately narrow**.

The first engineering objective should not be Fleet, Next.js, React, CrewAI, or Docker.

The first executable milestone should be:

```text
PostgreSQL
    ↓
Tenant
    ↓
Membership
    ↓
Generic JSONB Entity Record
    ↓
Generic Entity Relationship
    ↓
Record Versioning
    ↓
Foundation Indexes
```

Then Phase 2 immediately proves:

```text
Tenant A
    ≠
Tenant B
```

at the PostgreSQL/RLS boundary.

Only after that security foundation passes should XORVA be allowed to become dynamic.