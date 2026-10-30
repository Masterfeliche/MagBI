# Agentic Workflow Specification (v1.3)

This document defines a systematic, Jira-aligned workflow for AI agents and senior engineers. It ensures consistency, traceability, and high-quality contributions across any repository and OS.

## 1. Core Mandates

### 1.1 Single Source of Truth (SSOT)
Each feature must have exactly ONE state file: `docs/features/<TICKET-ID>/README.md`.

### 1.2 Jira-Style Task Management
All work must be broken down into Jira-style Tasks and Subtasks within the SSOT file.

### 1.3 Single-Sentence Commit Rule
Commits must be atomic and strictly follow these rules:
- **Format**: `type(scope): description` (Conventional Commits).
- **Sentence**: Exactly one sentence.
- **Imperative**: Start with a verb in imperative mood.
- **Length**: Maximum 72 characters.
- **Punctuation**: No periods, semicolons, or colons in the description.

### 1.4 Analysis-First Protocol
No code changes are permitted until the **Analysis** and **Plan** sections are approved.

---

## 2. The Workflow Lifecycle

### Phase 1: Analysis
Update the `Analysis` section in the SSOT README.

### Phase 2: Planning
Update the `Implementation Plan` section.

### Phase 3: Execution
Update the `Execution Log` (Code + Test + Commit + Mark complete).

### Phase 4: Finalization
Run regression, verify DoD, and generate PR description.

---

## 3. Tooling & Automation

### 3.1 State Management (`scripts/ai-feature.py`)
Tracks the current phase, ticket ID, and auto-provisions feature manifests. Uses `pathlib` for 100% Windows/Unix compatibility.

### 3.2 Cross-Platform Commit Hook (`.git/hooks/commit-msg`)
A Python-based hook that enforces the single-sentence rule. Works natively on Linux/macOS, and via Git for Windows on Windows.

---

## 4. Repository Structure
```text
/
├── .ai-workflow.yaml
├── AGENTS.md
├── docs/
│   ├── architecture/
│   ├── kb/
│   ├── features/
│   │   └── <TICKET-ID>/
│   │       └── README.md
│   └── guides/
├── server/
│   └── magbi/
├── web/
│   └── src/
├── deploy/
└── scripts/
    └── ai-feature.py
```

---

## 5. The Trigger Prompt

```
ACT AS A SENIOR ENGINEER FOLLOWING THIS EXACT PROCESS.

FEATURE REQUEST: {user story or ticket summary}
TICKET ID: {TICKET-123}

STEP 0 - LOAD RULES:
- Read `.ai-workflow.yaml` and `AGENTS.md`.
- All tasks/subtasks MUST follow Jira format.
- Every commit MUST be a single sentence (Conventional Commits).

STEP 1 - ANALYSIS:
Initialize the feature state and produce/update the Analysis section.

STEP 2 - PLAN:
Break tasks into subtasks in the SSOT README.

STEP 3 - EXECUTE:
One subtask at a time (Code + Test + Single-Sentence Commit).

STEP 4 - FINAL:
Regression, DoD verification, and PR generation.
```
