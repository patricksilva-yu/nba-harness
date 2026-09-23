# Capstone Project Scope

> **Supersession note (2026-09-23):** The web application's primary audience is
> now basketball fans seeking evidence-checked postgame answers, with support for
> follow-up questions about the same game. The developer remains the system
> evaluator, and the Analysis, Investigation and Evaluation views remain in scope.
> The original text below is preserved as the point-in-time scope.

## Project Title

**Reliable NBA Analysis Through MCP, Agent Harnesses, and Evaluation Loops**

## Document Purpose

This document defines what the capstone project will deliver, how success will be measured, and which ideas are intentionally outside the project. It is a scope document rather than a detailed design document. Low-level choices such as database tables, API routes, prompts, and user-interface layouts will be documented after the core workflow has been tested.

## Project Summary

The project will produce a deployed web application that answers postgame NBA questions using verified basketball data. Its main purpose is to demonstrate how an AI agent can be made more reliable through a custom execution harness and controlled reasoning loops.

The agent will use Model Context Protocol (MCP) tools to obtain game data and supporting evidence. A Python harness will manage each run, including the steps taken, tool calls, retries, resource limits, errors, and reason for stopping. Two focused loops will be implemented:

1. **Verification loop:** checks whether important claims and numerical statements are supported by the available evidence, then corrects or qualifies unsupported claims.
2. **Investigation loop:** gathers additional evidence when the first set of data is incomplete or conflicting, while respecting fixed limits on time, tool calls, iterations, and cost.

The application will make this process visible. A user will be able to read the final analysis, inspect how the agent reached it, and review evaluation results comparing simpler and more controlled versions of the agent.

This project supports the developer's career growth as an AI Developer by bringing together MCP integration, harness engineering, loop design, evaluation, web development, data storage, and cloud deployment in one complete system.

## Starting Point

A preliminary proof of concept already exists in the repository. It shows that NBA data can be accessed and used to produce an answer, which reduces feasibility risk. The proof of concept is a starting point only. The capstone work will define the controlled execution process, add verification and investigation loops, create a meaningful evaluation suite, improve the interface, and deploy the complete application and database to the cloud.

## Intended User and Main Use Case

The primary user is the developer, acting as an NBA analyst and system evaluator. The application is intended for low traffic and does not need to support a public audience at production scale.

The main use case is:

> A user selects or identifies an NBA game, asks a postgame question, receives an evidence-supported answer, and can inspect the evidence, corrections, tool activity, stopping reason, latency, and estimated token usage behind that answer.

Example questions include identifying why a team won, comparing key player contributions, explaining a statistical advantage, or checking whether a proposed explanation is supported by the game data.

## Core Scope

### 1. Evidence-based NBA analysis

- Answer bounded postgame questions using available NBA game data.
- Associate important factual and numerical claims with supporting evidence.
- Clearly identify missing, incomplete, or conflicting evidence.
- Express uncertainty or decline to make a claim when the evidence is insufficient.

### 2. Custom Python agent harness

- Use the OpenAI Agents SDK for Python as the initial agent runtime, with GPT-5.6 Terra as the planned model.
- Add a custom controller around the runtime so the project demonstrates original harness engineering rather than relying only on framework defaults.
- Maintain explicit run state, including the current question, gathered evidence, claims under review, completed steps, and unresolved issues.
- Enforce limits for iterations, tool calls, elapsed time, and estimated token cost.
- Handle tool failures and model errors with bounded retries and clear failure states.
- Save a structured record of each run for inspection and evaluation.

### 3. Verification and investigation loops

- Check the answer's main claims against the evidence before presenting the final response.
- Revise, qualify, or remove unsupported claims.
- Request targeted additional evidence when the initial evidence is insufficient.
- Stop when the answer is adequately supported, a defined limit is reached, or further investigation is unlikely to help.
- Record why the loop continued and why it eventually stopped.

### 4. MCP-based tools

- Keep MCP as the standard interface between the agent and basketball data tools.
- Define focused tools for retrieving the game information needed by the core use cases.
- Return structured evidence that the harness can store, compare, and display.
- Test tool behavior and error handling independently from the model where practical.

### 5. Web application

The application will provide three connected views:

- **Analysis:** the final answer, supporting statistics, evidence references, and stated limitations.
- **Investigation:** an expandable record of tool calls, evidence gathered, verification failures, revisions, stopping reason, latency, and token usage.
- **Evaluation:** comparison results across agent configurations, with summary metrics and expandable failure examples.

The interface will be designed for one user and will favour clarity and inspectability over advanced account, collaboration, or administrative features.

### 6. Cloud deployment

The application will be deployed on Microsoft Azure using the following planned services:

- Azure Static Web Apps for the web interface.
- Azure Container Apps for the Python API, agent harness, and MCP services.
- Azure Database for PostgreSQL Flexible Server for basketball data, evidence records, agent runs, and evaluation results.
- Azure-managed secrets and application monitoring where needed for secure configuration and troubleshooting.

The infrastructure will be sized for personal use. The current operating estimate is approximately **US$20–35 per month** without student credits, with Azure student credits expected to reduce the direct cost if available.

## Evaluation Scope

The evaluation will test whether the added loops produce a measurable benefit rather than being included only for technical complexity. Three configurations will be compared while keeping the model, questions, and underlying data as consistent as possible:

1. A basic tool-calling agent.
2. The same agent with claim verification.
3. The agent with claim verification and adaptive evidence gathering.

The planned benchmark contains 30 held-out questions drawn from approximately 10 games, plus 10 separate development questions. The target is approximately 210 runs:

- 60 development runs across two checkpoints.
- 90 final comparison runs.
- 60 additional runs on a smaller subset to examine repeatability.

The run count may be reduced if cost or schedule pressure arises, provided all three configurations are still compared on the same held-out questions and the limitation is disclosed.

Evaluation will consider:

- Factual and numerical accuracy.
- Whether important claims are supported by evidence.
- Completeness and usefulness of the answer.
- Appropriate uncertainty or refusal when evidence is insufficient.
- Successful correction of unsupported claims without introducing new errors.
- Tool-call efficiency, latency, token usage, and estimated cost.
- Consistency across repeated runs.

A manageable sample of outputs will also be reviewed manually. Results will be presented as evidence about this application and benchmark; they will not be treated as proof that one approach is universally superior.

## Stretch Goal

After the complete core system is working and evaluated, the application may compare a player's performance in one game with their previous 10 games. This feature would use descriptive statistics and clearly state the limitations of the small sample. Broader statistical experiments across games will only be attempted if the core milestones remain on schedule.

## Out of Scope

The following items are outside the planned capstone scope:

- Automatic prompt optimization or a system that changes itself based on evaluation results.
- Unrestricted autonomous research or open-ended statistical experimentation.
- A general-purpose NBA chatbot covering every type of basketball question.
- A multi-agent swarm unless evaluation results reveal a specific need that cannot be met by the single controlled agent.
- Predictions, betting advice, or causal claims about why an event occurred.
- Public-scale traffic, high availability, complex user accounts, or team collaboration features.
- A large real-time data pipeline or scheduled ingestion system beyond what the selected questions require.
- Native mobile applications.

## Major Milestones

### Major Milestone 1 — Progress Report: December 8, 2026 at 11:59 PM

By this milestone, the project should have a stable foundation and a first end-to-end version. Planned work includes:

- Finalize the requirements, evaluation questions, success measures, and project boundaries.
- Prepare the basketball data required for development and evaluation.
- Create the first working version of the website and connect it to the analysis service.
- Build the initial process that checks whether the analysis is supported by evidence.
- Record basic run information such as evidence used, errors, stopping reason, response time, and token usage.
- Complete early development evaluations and identify the main failure patterns.
- Submit a progress report covering completed work, milestone achievement, challenges and solutions, an updated plan, reflection, and AI-tool disclosure.

Minor checkpoints will be tracked through completed features, saved evaluation runs, and short notes describing decisions, failures, and changes to the plan.

### Major Milestone 2 — Final Submission: March 5, 2027 at 11:59 PM

By the final deadline, the project should include:

- A working cloud-deployed application and PostgreSQL database on Azure.
- The completed verification and follow-up investigation loops.
- A usable interface for viewing the answer, evidence, agent process, and evaluation results.
- Bounded error handling, execution limits, run logging, secrets management, and basic monitoring.
- Completed held-out comparisons, repeatability checks, and manual review of selected results.
- A demonstration showing both successful behaviour and known limitations.
- A final report covering motivation and objectives, design and implementation, functionality, evaluation findings, strengths, limitations, future directions, and lessons learned.

The previous-10-games comparison will be included only if these core items are complete.

## Definition of Done

The capstone will be considered complete when:

- A user can submit an NBA postgame question through the deployed website and receive an evidence-supported answer.
- The harness applies explicit limits, handles expected failures, and records a clear stopping reason.
- The verification loop can detect and repair at least some unsupported claims in documented test cases.
- The investigation loop can request relevant additional evidence in documented incomplete-evidence cases.
- The user can inspect the evidence and main steps behind a completed run.
- Evaluation results compare all three configurations using the same held-out question set.
- Accuracy, evidence support, uncertainty, latency, token usage, and cost are reported with clear limitations.
- The final application, demonstration, and report satisfy the course requirements.

## Constraints and Risks

- **Individual workload:** The scope is limited to two core loops, one primary use case, and a simple interface. The stretch goal will be removed first if time becomes limited.
- **Model and API cost:** Development will use small question sets and saved data before final evaluation runs. The planned model budget is approximately **US$40–60** for the full project, subject to actual pricing and prompt size.
- **Nondeterministic model behaviour:** Questions, source data, configuration, and run records will be preserved so comparisons can be reproduced and failures can be inspected.
- **Data quality or availability:** Evaluation questions will use games with complete required data, and missing information will be treated as an explicit system state.
- **Framework limitations:** A small proof of concept will validate the OpenAI Agents SDK before the detailed design is fixed. The custom harness will own the project-specific control logic and records.
- **Schedule pressure:** Core functionality and evaluation take priority over visual polish and cross-game analysis.

## Decisions Deferred to the Design Stage

The following choices will be made after small prototypes confirm what the system needs:

- Exact harness state model and database schema.
- Final MCP tool names, inputs, outputs, and service boundaries.
- Verification technique, including the balance between deterministic checks and model-based review.
- Detailed stopping rules and default resource limits.
- Exact evaluation scoring rubric and manual-review sample size.
- Final page layout and visualization choices.
- Azure resource sizes, deployment workflow, monitoring fields, and retention period for run records.

A separate design document will be useful once these decisions can be based on tested behaviour. It is not required to define the current project scope.

## AI-Tool Disclosure

AI tools were used to help consolidate research and compare suitable agent frameworks and cloud deployment services for this use case. The project scope, MCP architecture, harness and loop concepts, implementation decisions, and evaluation plan were developed by the student. Any AI assistance used later for implementation or report preparation will be disclosed in the relevant course submission.
