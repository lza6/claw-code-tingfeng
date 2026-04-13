package cli

import (
	"os"
	"testing"

	goalx "github.com/vonbai/goalx"
)

func TestHasUnsavedRunArtifactsTreatsIntegrationStateAsUnsaved(t *testing.T) {
	projectRoot := t.TempDir()
	runName := "demo"
	cfg := &goalx.Config{
		Name:      runName,
		Mode:      goalx.ModeWorker,
		Objective: "ship feature",
		Target:    goalx.TargetConfig{Files: []string{"README.md"}},
	}
	runDir := writeRunSpecFixture(t, projectRoot, cfg)
	seedSaveRunProvenance(t, projectRoot, runDir, runName, cfg.Objective)

	if err := SaveIntegrationState(IntegrationStatePath(runDir), &IntegrationState{
		Version:                 1,
		CurrentExperimentID:     "exp-1",
		CurrentBranch:           "goalx/demo/1",
		CurrentCommit:           "abc123",
		LastIntegrationID:       "int-1",
		LastMethod:              "keep",
		LastSourceExperimentIDs: []string{"exp-1"},
	}); err != nil {
		t.Fatalf("SaveIntegrationState: %v", err)
	}

	rc, err := ResolveRun(projectRoot, runName)
	if err != nil {
		t.Fatalf("ResolveRun: %v", err)
	}
	unsaved, err := hasUnsavedRunArtifacts(projectRoot, rc)
	if err != nil {
		t.Fatalf("hasUnsavedRunArtifacts: %v", err)
	}
	if !unsaved {
		t.Fatal("expected integration.json to count as unsaved artifact")
	}

	if err := os.Remove(IntegrationStatePath(runDir)); err != nil {
		t.Fatalf("remove integration.json: %v", err)
	}
	unsaved, err = hasUnsavedRunArtifacts(projectRoot, rc)
	if err != nil {
		t.Fatalf("hasUnsavedRunArtifacts after remove: %v", err)
	}
	if unsaved {
		t.Fatal("expected unsaved artifacts to clear after integration.json removal")
	}
}
