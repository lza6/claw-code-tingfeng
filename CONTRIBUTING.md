# Contributing to Clawd Code

Thanks for your interest in contributing! This project is a comprehensive AI-powered coding agent framework with production-grade engineering skills.

## Adding a New Skill

1. Create a directory under `skills/` with a kebab-case name
2. Add a `SKILL.md` following the format in [docs/skill-anatomy.md](docs/skill-anatomy.md)
3. Include YAML frontmatter with `name` and `description` fields
4. Ensure the `description` starts with what the skill does (third person), followed by trigger conditions ("Use when...")

### Skill Quality Bar

Skills should be:

- **Specific** — Actionable steps, not vague advice
- **Verifiable** — Clear exit criteria with evidence requirements
- **Battle-tested** — Based on real engineering workflows, not theoretical ideals
- **Minimal** — Only the content needed to guide the agent correctly

### Structure

Every skill should include these sections:

- **Overview** — What this skill does and why it matters
- **When to Use** — Triggering conditions
- **Process** — Step-by-step workflow
- **Common Rationalizations** — Excuses agents use to skip steps, with rebuttals
- **Red Flags** — Warning signs that the skill is being applied incorrectly
- **Verification** — How to confirm the skill was applied correctly

### What Not to Do

- Don't duplicate content between skills — reference other skills instead
- Don't add skills that are vague advice instead of actionable processes
- Don't create supporting files unless content exceeds 100 lines
- Don't put reference material inside skill directories — use `references/` instead

## Modifying Existing Skills

- Keep changes focused and minimal
- Preserve the existing structure and tone
- Test that YAML frontmatter remains valid after edits

## Contributing to the Python Framework

Clawd Code is a Python 3.10+ application. When contributing to the core framework:

### Code Style
- Follow PEP 8 with ruff enforcement
- Run `ruff check src/` and `ruff format src/` before committing

### Testing
- Test files mirror source structure: `tests/<module>/`
- Run tests with: `python -m pytest tests/ -v --tb=short`
- Maintain or improve test coverage

### Architecture
- Settings use 6-layer priority: defaults → .env → runtime → CLI → file → API
- Use the patch engine (`src/core/`) for declarative code modifications
- Follow existing patterns for error handling using `src/core/exceptions.py`

## Reporting Issues

Open an issue if you find:

- A skill that gives incorrect or outdated guidance
- Missing coverage for a common engineering workflow
- Inconsistencies between skills
- Bugs in the Python framework
- Security vulnerabilities

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
