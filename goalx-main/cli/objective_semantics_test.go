package cli

import (
	"strings"
	"testing"

	goalx "github.com/vonbai/goalx"
)

func TestEnsureRuntimeStateCreatesValidState(t *testing.T) {
	runDir := t.TempDir()
	cfg := &goalx.Config{
		Name:      "demo",
		Mode:      goalx.ModeWorker,
		Objective: "stale runtime objective",
	}

	state, err := EnsureRuntimeState(runDir, cfg)
	if err != nil {
		t.Fatalf("EnsureRuntimeState: %v", err)
	}
	if state.Run != "demo" {
		t.Fatalf("state.Run = %q, want demo", state.Run)
	}
	if !state.Active {
		t.Fatal("state.Active should be true")
	}
}

func TestRegisterRunRegistriesDoNotPersistObjective(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	projectRoot := t.TempDir()
	cfg := &goalx.Config{
		Name:      "demo",
		Mode:      goalx.ModeWorker,
		Objective: "stale registry objective",
	}

	if err := RegisterActiveRun(projectRoot, cfg); err != nil {
		t.Fatalf("RegisterActiveRun: %v", err)
	}

	projectReg, err := LoadProjectRegistry(projectRoot)
	if err != nil {
		t.Fatalf("LoadProjectRegistry: %v", err)
	}
	if got := projectReg.ActiveRuns[cfg.Name].Objective; got != "" {
		t.Fatalf("project registry objective = %q, want empty", got)
	}

	globalReg, err := LoadGlobalRunRegistry()
	if err != nil {
		t.Fatalf("LoadGlobalRunRegistry: %v", err)
	}
	key := globalRunKey(projectRoot, cfg.Name)
	if got := globalReg.Runs[key].Objective; got != "" {
		t.Fatalf("global registry objective = %q, want empty", got)
	}
}

func TestLoadDerivedRunStatePrefersCharterObjective(t *testing.T) {
	repo := initGitRepo(t)
	writeAndCommit(t, repo, "README.md", "base", "base commit")

	cfg := &goalx.Config{
		Name:      "demo",
		Mode:      goalx.ModeWorker,
		Objective: "charter objective",
	}
	runDir := writeRunSpecFixture(t, repo, cfg)
	if err := SaveRunMetadata(RunMetadataPath(runDir), &RunMetadata{
		Version:      1,
		BaseRevision: strings.TrimSpace(gitOutput(t, repo, "rev-parse", "HEAD")),
	}); err != nil {
		t.Fatalf("SaveRunMetadata: %v", err)
	}
	seedRunCharterForTests(t, runDir, cfg.Name, repo)
	if err := EnsureControlState(runDir); err != nil {
		t.Fatalf("EnsureControlState: %v", err)
	}

	state, err := loadDerivedRunState(repo, runDir)
	if err != nil {
		t.Fatalf("loadDerivedRunState: %v", err)
	}
	if state.Objective != "charter objective" {
		t.Fatalf("state.Objective = %q, want charter objective", state.Objective)
	}
}

func TestReportUsesCharterObjectiveDisplay(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	repo := initGitRepo(t)
	writeAndCommit(t, repo, "README.md", "base", "base commit")

	cfg := &goalx.Config{
		Name:      "demo",
		Mode:      goalx.ModeWorker,
		Objective: "charter objective",
	}
	runDir := writeRunSpecFixture(t, repo, cfg)
	if err := SaveRunMetadata(RunMetadataPath(runDir), &RunMetadata{
		Version:      1,
		BaseRevision: strings.TrimSpace(gitOutput(t, repo, "rev-parse", "HEAD")),
	}); err != nil {
		t.Fatalf("SaveRunMetadata: %v", err)
	}
	seedRunCharterForTests(t, runDir, cfg.Name, repo)

	out := captureStdout(t, func() {
		if err := Report(repo, []string{"--run", cfg.Name}); err != nil {
			t.Fatalf("Report: %v", err)
		}
	})
	if !strings.Contains(out, "Objective: charter objective") {
		t.Fatalf("report output missing charter objective:\n%s", out)
	}
}
