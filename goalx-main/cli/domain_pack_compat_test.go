package cli

import (
	"os"
	"testing"

	goalx "github.com/vonbai/goalx"
)

func TestRefreshDisplayFactsAcceptsLegacyDomainPackDomainField(t *testing.T) {
	repo, runDir, cfg, meta := writeGuidanceRunFixture(t)

	if err := EnsureSuccessCompilation(repo, runDir, cfg, meta); err != nil {
		t.Fatalf("EnsureSuccessCompilation: %v", err)
	}
	legacyPack := `{
  "version": 1,
  "compiled_at": "2026-04-02T04:02:09Z",
  "domain": "evolve",
  "signals": ["auto"],
  "slots": {
    "run_context": {
      "source": "control/memory-context.json",
      "refs": ["control/memory-context.json"]
    }
  }
}`
	if err := os.WriteFile(DomainPackPath(runDir), []byte(legacyPack), 0o644); err != nil {
		t.Fatalf("write legacy domain-pack: %v", err)
	}

	rc := &RunContext{
		Name:        cfg.Name,
		RunDir:      runDir,
		TmuxSession: goalx.TmuxSessionName(repo, cfg.Name),
		ProjectRoot: repo,
		Config:      cfg,
	}
	if err := refreshDisplayFacts(rc); err != nil {
		t.Fatalf("refreshDisplayFacts should accept legacy domain-pack field: %v", err)
	}
}
