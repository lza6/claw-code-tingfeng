package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	goalx "github.com/vonbai/goalx"
)

func TestIntegrateRecordsManualRunRootIntegration(t *testing.T) {
	repo := initGitRepo(t)
	writeAndCommit(t, repo, "README.md", "base\n", "base commit")
	if err := EnsureProjectGoalxIgnored(repo); err != nil {
		t.Fatalf("EnsureProjectGoalxIgnored: %v", err)
	}

	runName := "integrate-run"
	runDir := writeKeepRunFixture(t, repo, runName)
	runWT := RunWorktreePath(runDir)
	runBranch := fmt.Sprintf("goalx/%s/root", runName)
	if err := CreateWorktree(repo, runWT, runBranch); err != nil {
		t.Fatalf("CreateWorktree run root: %v", err)
	}
	if err := initializeRootExperimentLineage(runDir, runWT, runName, string(goalx.ModeWorker)); err != nil {
		t.Fatalf("initializeRootExperimentLineage: %v", err)
	}

	rootState, err := LoadIntegrationState(IntegrationStatePath(runDir))
	if err != nil {
		t.Fatalf("LoadIntegrationState(root): %v", err)
	}
	if rootState == nil {
		t.Fatal("root integration state missing")
	}

	session1Branch := seedIntegrateSessionFixture(t, runDir, runName, runWT, 1, "alpha.txt", "alpha\n")
	session2Branch := seedIntegrateSessionFixture(t, runDir, runName, runWT, 2, "beta.txt", "beta\n")

	runGit(t, runWT, "merge", "--no-ff", "-m", "merge session-1", session1Branch)
	runGit(t, runWT, "cherry-pick", session2Branch)

	head := strings.TrimSpace(gitOutput(t, runWT, "rev-parse", "HEAD"))
	out := captureStdout(t, func() {
		if err := Integrate(repo, []string{"--run", runName, "--method", "consolidate", "--from", "session-1,session-2"}); err != nil {
			t.Fatalf("Integrate: %v", err)
		}
	})
	if !strings.Contains(out, "Integration recorded:") {
		t.Fatalf("integrate output missing record message:\n%s", out)
	}

	state, err := LoadIntegrationState(IntegrationStatePath(runDir))
	if err != nil {
		t.Fatalf("LoadIntegrationState: %v", err)
	}
	if state == nil {
		t.Fatal("integration state missing after integrate")
	}
	if state.CurrentCommit != head {
		t.Fatalf("CurrentCommit = %q, want %q", state.CurrentCommit, head)
	}
	if state.CurrentBranch != runBranch {
		t.Fatalf("CurrentBranch = %q, want %q", state.CurrentBranch, runBranch)
	}
	if state.CurrentExperimentID == rootState.CurrentExperimentID {
		t.Fatalf("CurrentExperimentID should advance past root experiment %q", state.CurrentExperimentID)
	}
	if state.LastMethod != "consolidate" {
		t.Fatalf("LastMethod = %q, want consolidate", state.LastMethod)
	}

	wantSources := []string{
		identityExperimentID(t, runDir, "session-1"),
		identityExperimentID(t, runDir, "session-2"),
	}
	if got := strings.Join(state.LastSourceExperimentIDs, ","); got != strings.Join(wantSources, ",") {
		t.Fatalf("LastSourceExperimentIDs = %v, want %v", state.LastSourceExperimentIDs, wantSources)
	}

	events, err := LoadDurableLog(ExperimentsLogPath(runDir), DurableSurfaceExperiments)
	if err != nil {
		t.Fatalf("LoadDurableLog: %v", err)
	}
	if len(events) < 5 {
		t.Fatalf("unexpected experiment event count %d", len(events))
	}
	if events[len(events)-2].Kind != "experiment.created" {
		t.Fatalf("second-to-last event kind = %q, want experiment.created", events[len(events)-2].Kind)
	}
	if events[len(events)-1].Kind != "experiment.integrated" {
		t.Fatalf("last event kind = %q, want experiment.integrated", events[len(events)-1].Kind)
	}

	var created ExperimentCreatedBody
	if err := json.Unmarshal(events[len(events)-2].Body, &created); err != nil {
		t.Fatalf("unmarshal created body: %v", err)
	}
	if created.Session != "master" {
		t.Fatalf("created.Session = %q, want master", created.Session)
	}
	if created.Branch != runBranch {
		t.Fatalf("created.Branch = %q, want %q", created.Branch, runBranch)
	}
	if created.Worktree != runWT {
		t.Fatalf("created.Worktree = %q, want %q", created.Worktree, runWT)
	}
	if created.BaseExperimentID != rootState.CurrentExperimentID {
		t.Fatalf("created.BaseExperimentID = %q, want %q", created.BaseExperimentID, rootState.CurrentExperimentID)
	}
	if created.ExperimentID != state.CurrentExperimentID {
		t.Fatalf("created.ExperimentID = %q, want current experiment %q", created.ExperimentID, state.CurrentExperimentID)
	}

	var integrated ExperimentIntegratedBody
	if err := json.Unmarshal(events[len(events)-1].Body, &integrated); err != nil {
		t.Fatalf("unmarshal integrated body: %v", err)
	}
	if integrated.ResultExperimentID != state.CurrentExperimentID {
		t.Fatalf("ResultExperimentID = %q, want %q", integrated.ResultExperimentID, state.CurrentExperimentID)
	}
	if integrated.Method != "consolidate" {
		t.Fatalf("Method = %q, want consolidate", integrated.Method)
	}
	if got := strings.Join(integrated.SourceExperimentIDs, ","); got != strings.Join(wantSources, ",") {
		t.Fatalf("SourceExperimentIDs = %v, want %v", integrated.SourceExperimentIDs, wantSources)
	}
	if integrated.ResultBranch != runBranch {
		t.Fatalf("ResultBranch = %q, want %q", integrated.ResultBranch, runBranch)
	}
	if integrated.ResultCommit != head {
		t.Fatalf("ResultCommit = %q, want %q", integrated.ResultCommit, head)
	}
}

func TestIntegrateRejectsUnchangedRunRootHead(t *testing.T) {
	repo := initGitRepo(t)
	writeAndCommit(t, repo, "README.md", "base\n", "base commit")
	if err := EnsureProjectGoalxIgnored(repo); err != nil {
		t.Fatalf("EnsureProjectGoalxIgnored: %v", err)
	}

	runName := "integrate-run"
	runDir := writeKeepRunFixture(t, repo, runName)
	runWT := RunWorktreePath(runDir)
	runBranch := fmt.Sprintf("goalx/%s/root", runName)
	if err := CreateWorktree(repo, runWT, runBranch); err != nil {
		t.Fatalf("CreateWorktree run root: %v", err)
	}
	if err := initializeRootExperimentLineage(runDir, runWT, runName, string(goalx.ModeWorker)); err != nil {
		t.Fatalf("initializeRootExperimentLineage: %v", err)
	}

	err := Integrate(repo, []string{"--run", runName, "--method", "manual_merge", "--from", "run-root"})
	if err == nil {
		t.Fatal("expected Integrate to reject unchanged run-root HEAD")
	}
	for _, want := range []string{"run-root HEAD", "unchanged"} {
		if !strings.Contains(err.Error(), want) {
			t.Fatalf("Integrate error = %v, want substring %q", err, want)
		}
	}
}

func TestIntegrateRejectsDirtyRunRootWorktree(t *testing.T) {
	repo := initGitRepo(t)
	writeAndCommit(t, repo, "README.md", "base\n", "base commit")
	if err := EnsureProjectGoalxIgnored(repo); err != nil {
		t.Fatalf("EnsureProjectGoalxIgnored: %v", err)
	}

	runName := "integrate-run"
	runDir := writeKeepRunFixture(t, repo, runName)
	runWT := RunWorktreePath(runDir)
	runBranch := fmt.Sprintf("goalx/%s/root", runName)
	if err := CreateWorktree(repo, runWT, runBranch); err != nil {
		t.Fatalf("CreateWorktree run root: %v", err)
	}
	if err := initializeRootExperimentLineage(runDir, runWT, runName, string(goalx.ModeWorker)); err != nil {
		t.Fatalf("initializeRootExperimentLineage: %v", err)
	}
	if err := os.WriteFile(filepath.Join(runWT, "dirty.txt"), []byte("dirty\n"), 0o644); err != nil {
		t.Fatalf("write dirty file: %v", err)
	}

	err := Integrate(repo, []string{"--run", runName, "--method", "partial_adopt", "--from", "run-root"})
	if err == nil {
		t.Fatal("expected Integrate to reject dirty run-root worktree")
	}
	for _, want := range []string{"run-root worktree", "dirty.txt"} {
		if !strings.Contains(err.Error(), want) {
			t.Fatalf("Integrate error = %v, want substring %q", err, want)
		}
	}
}

func TestIntegrateHelpExplainsManualIntegrationBoundary(t *testing.T) {
	out := captureStdout(t, func() {
		if err := Integrate(t.TempDir(), []string{"--help"}); err != nil {
			t.Fatalf("Integrate --help: %v", err)
		}
	})
	for _, want := range []string{
		"usage: goalx integrate [--run NAME] --method METHOD --from SOURCE[,SOURCE...]",
		"record a master-owned integration experiment for the current run-root HEAD",
		"requires the run-root worktree to be clean",
		"does not merge branches for you",
		"session-N",
		"run-root",
	} {
		if !strings.Contains(out, want) {
			t.Fatalf("integrate help missing %q:\n%s", want, out)
		}
	}
}

func seedIntegrateSessionFixture(t *testing.T, runDir, runName, runWT string, idx int, fileName, contents string) string {
	t.Helper()

	sessionName := SessionName(idx)
	sessionWT := WorktreePath(runDir, runName, idx)
	sessionBranch := fmt.Sprintf("goalx/%s/%d", runName, idx)
	if err := CreateWorktree(runWT, sessionWT, sessionBranch, fmt.Sprintf("goalx/%s/root", runName)); err != nil {
		t.Fatalf("CreateWorktree %s: %v", sessionName, err)
	}
	identity := makeKeepSessionIdentity(t, runDir, sessionName, runName, "run-root", fmt.Sprintf("goalx/%s/root", runName))
	if err := SaveSessionIdentity(SessionIdentityPath(runDir, sessionName), identity); err != nil {
		t.Fatalf("SaveSessionIdentity(%s): %v", sessionName, err)
	}
	writeAndCommit(t, sessionWT, fileName, contents, sessionName+" change")
	if err := appendExperimentCreated(runDir, ExperimentCreatedBody{
		ExperimentID:     identity.ExperimentID,
		Session:          sessionName,
		Branch:           sessionBranch,
		Worktree:         sessionWT,
		Intent:           identity.Mode,
		BaseRef:          identity.BaseBranch,
		BaseExperimentID: identity.BaseExperimentID,
		CreatedAt:        identity.CreatedAt,
	}); err != nil {
		t.Fatalf("appendExperimentCreated(%s): %v", sessionName, err)
	}
	return sessionBranch
}
