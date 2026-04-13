package cli

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	goalx "github.com/vonbai/goalx"
)

func TestFocusSetsFocusedRun(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	projectRoot := filepath.Join(t.TempDir(), "repo")
	if err := os.MkdirAll(projectRoot, 0o755); err != nil {
		t.Fatalf("mkdir project root: %v", err)
	}

	runName := "beta"
	runDir := goalx.RunDir(projectRoot, runName)
	if err := os.MkdirAll(runDir, 0o755); err != nil {
		t.Fatalf("mkdir run dir: %v", err)
	}
	if err := os.WriteFile(RunSpecPath(runDir), []byte("name: beta\nmode: worker\nobjective: keep moving\n"), 0o644); err != nil {
		t.Fatalf("write run spec: %v", err)
	}

	reg := &ProjectRegistry{
		Version: 1,
		ActiveRuns: map[string]ProjectRunRef{
			"alpha": {Name: "alpha", State: "active"},
			"beta":  {Name: "beta", State: "active"},
		},
	}
	if err := SaveProjectRegistry(projectRoot, reg); err != nil {
		t.Fatalf("save registry: %v", err)
	}

	out := captureStdout(t, func() {
		if err := Focus(projectRoot, []string{"--run", runName}); err != nil {
			t.Fatalf("Focus: %v", err)
		}
	})
	if !strings.Contains(out, "Focused run set to beta") {
		t.Fatalf("focus output = %q", out)
	}

	reg2, err := LoadProjectRegistry(projectRoot)
	if err != nil {
		t.Fatalf("load registry: %v", err)
	}
	if reg2.FocusedRun != runName {
		t.Fatalf("focused run = %q, want %q", reg2.FocusedRun, runName)
	}

	got, err := ResolveDefaultRunName(projectRoot)
	if err != nil {
		t.Fatalf("ResolveDefaultRunName: %v", err)
	}
	if got != runName {
		t.Fatalf("ResolveDefaultRunName = %q, want %q", got, runName)
	}
	if _, err := os.Stat(filepath.Join(projectRoot, ".goalx", "runs.json")); !os.IsNotExist(err) {
		t.Fatalf("project scoped runs.json should not exist, stat err = %v", err)
	}
}

func TestFocusHelpPrintsUsageWithoutMutatingRegistry(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	projectRoot := filepath.Join(t.TempDir(), "repo")
	if err := os.MkdirAll(projectRoot, 0o755); err != nil {
		t.Fatalf("mkdir project root: %v", err)
	}
	if err := SaveProjectRegistry(projectRoot, &ProjectRegistry{
		Version:    1,
		FocusedRun: "alpha",
		ActiveRuns: map[string]ProjectRunRef{
			"alpha": {Name: "alpha", State: "active"},
		},
	}); err != nil {
		t.Fatalf("save registry: %v", err)
	}

	out := captureStdout(t, func() {
		if err := Focus(projectRoot, []string{"--help"}); err != nil {
			t.Fatalf("Focus --help: %v", err)
		}
	})
	if !strings.Contains(out, "usage: goalx focus --run NAME") {
		t.Fatalf("focus help output = %q", out)
	}

	reg, err := LoadProjectRegistry(projectRoot)
	if err != nil {
		t.Fatalf("load registry: %v", err)
	}
	if reg.FocusedRun != "alpha" {
		t.Fatalf("focused run changed unexpectedly: %#v", reg)
	}
}

func TestFocusRejectsCrossProjectSelector(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	projectA := initNamedGitRepo(t, "project-a")
	projectB := initNamedGitRepo(t, "project-b")
	writeAndCommit(t, projectA, "README.md", "base", "base commit")
	writeAndCommit(t, projectB, "README.md", "base", "base commit")

	cfg := &goalx.Config{
		Name:      "beta",
		Mode:      goalx.ModeWorker,
		Objective: "ship feature",
		Master:    goalx.MasterConfig{Engine: "codex", Model: "codex"},
	}
	runDir := writeRunSpecFixture(t, projectA, cfg)
	if _, err := EnsureRunMetadata(runDir, projectA, cfg.Objective); err != nil {
		t.Fatalf("EnsureRunMetadata: %v", err)
	}
	if err := RegisterActiveRun(projectA, cfg); err != nil {
		t.Fatalf("RegisterActiveRun: %v", err)
	}

	if err := SaveProjectRegistry(projectB, &ProjectRegistry{
		Version:    1,
		ActiveRuns: map[string]ProjectRunRef{},
	}); err != nil {
		t.Fatalf("SaveProjectRegistry: %v", err)
	}

	err := Focus(projectB, []string{"--run", goalx.ProjectID(projectA) + "/" + cfg.Name})
	if err == nil {
		t.Fatal("Focus succeeded, want error")
	}
	if !strings.Contains(err.Error(), "current project") {
		t.Fatalf("Focus error = %v, want current project message", err)
	}
}

func TestFocusAllowsLocalRunNameThatLooksLikeRunID(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	projectRoot := initNamedGitRepo(t, "project-a")
	writeAndCommit(t, projectRoot, "README.md", "base", "base commit")

	runName := "run_demo"
	runDir := goalx.RunDir(projectRoot, runName)
	if err := os.MkdirAll(runDir, 0o755); err != nil {
		t.Fatalf("mkdir run dir: %v", err)
	}
	if err := os.WriteFile(RunSpecPath(runDir), []byte("name: run_demo\nmode: worker\nobjective: keep moving\n"), 0o644); err != nil {
		t.Fatalf("write run spec: %v", err)
	}
	if err := SaveProjectRegistry(projectRoot, &ProjectRegistry{
		Version: 1,
		ActiveRuns: map[string]ProjectRunRef{
			runName: {Name: runName, State: "active"},
		},
	}); err != nil {
		t.Fatalf("save registry: %v", err)
	}

	if err := Focus(projectRoot, []string{"--run", runName}); err != nil {
		t.Fatalf("Focus: %v", err)
	}
}
