package cli

import (
	"os"
	"path/filepath"
	"testing"

	goalx "github.com/vonbai/goalx"
)

func TestDimensionSetAppliesToAllSessions(t *testing.T) {
	projectRoot := t.TempDir()
	cfg := &goalx.Config{
		Name: "dimension-run",
		Mode: goalx.ModeWorker,
	}
	runDir := writeRunSpecFixture(t, projectRoot, cfg)
	for _, sessionName := range []string{"session-1", "session-2"} {
		if err := os.WriteFile(JournalPath(runDir, sessionName), nil, 0o644); err != nil {
			t.Fatalf("seed %s journal: %v", sessionName, err)
		}
	}

	if err := Dimension(projectRoot, []string{"--run", cfg.Name, "all", "--set", "depth, adversarial"}); err != nil {
		t.Fatalf("Dimension set all: %v", err)
	}

	state, err := LoadDimensionsState(ControlDimensionsPath(runDir))
	if err != nil {
		t.Fatalf("LoadDimensionsState: %v", err)
	}
	if state == nil {
		t.Fatal("dimensions state missing")
	}
	for _, sessionName := range []string{"session-1", "session-2"} {
		got := state.Sessions[sessionName]
		if len(got) != 2 || got[0].Name != "depth" || got[1].Name != "adversarial" {
			t.Fatalf("%s dimensions = %#v, want depth+adversarial", sessionName, got)
		}
	}
	if state.UpdatedAt == "" {
		t.Fatal("UpdatedAt empty")
	}
}

func TestDimensionAddAndRemoveUpdateNamedSession(t *testing.T) {
	projectRoot := t.TempDir()
	cfg := &goalx.Config{
		Name: "dimension-run",
		Mode: goalx.ModeWorker,
	}
	runDir := writeRunSpecFixture(t, projectRoot, cfg)
	if err := os.WriteFile(JournalPath(runDir, "session-1"), nil, 0o644); err != nil {
		t.Fatalf("seed session-1 journal: %v", err)
	}
	if err := SaveDimensionsState(ControlDimensionsPath(runDir), &DimensionsState{
		Version: 1,
		Sessions: map[string][]goalx.ResolvedDimension{
			"session-1": {
				{Name: "depth", Guidance: goalx.BuiltinDimensions["depth"], Source: goalx.DimensionSourceBuiltin},
				{Name: "evidence", Guidance: goalx.BuiltinDimensions["evidence"], Source: goalx.DimensionSourceBuiltin},
			},
			"session-2": {
				{Name: "comparative", Guidance: goalx.BuiltinDimensions["comparative"], Source: goalx.DimensionSourceBuiltin},
			},
		},
	}); err != nil {
		t.Fatalf("SaveDimensionsState: %v", err)
	}

	if err := Dimension(projectRoot, []string{"--run", cfg.Name, "session-1", "--add", "creative"}); err != nil {
		t.Fatalf("Dimension add: %v", err)
	}
	if err := Dimension(projectRoot, []string{"--run", cfg.Name, "session-1", "--add", "creative"}); err != nil {
		t.Fatalf("Dimension add duplicate: %v", err)
	}
	if err := Dimension(projectRoot, []string{"--run", cfg.Name, "session-1", "--remove", "depth"}); err != nil {
		t.Fatalf("Dimension remove: %v", err)
	}

	state, err := LoadDimensionsState(ControlDimensionsPath(runDir))
	if err != nil {
		t.Fatalf("LoadDimensionsState: %v", err)
	}
	if got := state.Sessions["session-1"]; len(got) != 2 || got[0].Name != "evidence" || got[1].Name != "creative" {
		t.Fatalf("session-1 dimensions = %#v, want evidence+creative", got)
	}
	if got := state.Sessions["session-2"]; len(got) != 1 || got[0].Name != "comparative" {
		t.Fatalf("session-2 dimensions = %#v, want comparative", got)
	}
}

func TestDimensionRejectsUnsupportedTargetMutationCombination(t *testing.T) {
	projectRoot := t.TempDir()
	cfg := &goalx.Config{
		Name: "dimension-run",
		Mode: goalx.ModeWorker,
	}
	runDir := writeRunSpecFixture(t, projectRoot, cfg)
	if err := os.WriteFile(filepath.Join(runDir, "journals", "session-1.jsonl"), nil, 0o644); err != nil {
		t.Fatalf("seed session-1 journal: %v", err)
	}

	err := Dimension(projectRoot, []string{"--run", cfg.Name, "all", "--add", "creative"})
	if err == nil {
		t.Fatal("Dimension(all --add) succeeded, want error")
	}
	if got, want := err.Error(), "usage: goalx dimension"; len(got) < len(want) || got[:len(want)] != want {
		t.Fatalf("Dimension(all --add) error = %q, want usage prefix %q", got, want)
	}
}
