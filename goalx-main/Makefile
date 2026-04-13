.PHONY: build install test vet check skill-sync all

all: check install skill-sync

build:
	go build ./...

test:
	go test ./... -count=1

vet:
	go vet ./...

check: build test vet

install:
	go build -o /usr/local/bin/goalx ./cmd/goalx

skill-sync:
	@set -e; \
	for dest in "$$HOME/.claude/skills/goalx" "$$HOME/.codex/skills/goalx"; do \
		rm -rf "$$dest"; \
		mkdir -p "$$dest/references" "$$dest/agents"; \
		cp skill/SKILL.md "$$dest/SKILL.md"; \
		cp -R skill/references/. "$$dest/references/"; \
		cp -R skill/agents/. "$$dest/agents/"; \
		echo "✓ skill synced to $$dest/"; \
	done
