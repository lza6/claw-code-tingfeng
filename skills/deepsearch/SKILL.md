---
name: deepsearch
description: Thorough codebase search
---

# Deep Search Mode

[DEEPSEARCH MODE ACTIVATED]

## Objective

Perform thorough search of the codebase for the specified query, pattern, or concept.

## Search Strategy

### Phase 1: Broad Search
- Search for exact matches
- Search for related terms and variations
- Check common locations (components, utils, services, hooks)
- Use glob patterns for file discovery
- Check git history for relevant changes

### Phase 2: Deep Dive
- Read files with matches
- Check imports/exports to find connections
- Follow the trail (what imports this? what does this import?)
- Trace type hierarchies and inheritance chains
- Map dependency graphs

### Phase 3: Synthesize
- Map out where the concept is used
- Identify the main implementation
- Note related functionality
- Document usage patterns and conventions
- Flag potential issues or gotchas

## Evidence Priority

When gathering evidence, prioritize:

1. **Controlled reproduction** — Run code to verify behavior
2. **Primary source artifacts** — trace events, logs, configs, git history
3. **Multiple convergent sources** — Multiple files point to same conclusion
4. **Single-source inference** — One file provides clear evidence
5. **Circumstantial clues** — Naming, timing, stack order
6. **Speculation** — Last resort, clearly labeled

## Output Format

### Primary Locations
[Main implementations with file:line references]

### Related Files
[Dependencies, consumers, downstream effects]

### Usage Patterns
[How it's used across the codebase]

### Key Insights
[Patterns, conventions, gotchas, warnings]

Task: {{ARGUMENTS}}

## Output Format

- **Primary Locations** (main implementations)
- **Related Files** (dependencies, consumers)
- **Usage Patterns** (how it's used across the codebase)
- **Key Insights** (patterns, conventions, gotchas)

Focus on being comprehensive but concise. Cite file paths and line numbers.
