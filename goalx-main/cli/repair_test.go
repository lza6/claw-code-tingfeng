package cli

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	goalx "github.com/vonbai/goalx"
)

func writeRepairableStoppedRunFixture(t *testing.T, repo, runName string, intent string) string {
	t.Helper()

	cfg := &goalx.Config{
		Name:      runName,
		Mode:      goalx.ModeWorker,
		Objective: "ship feature",
		Master:    goalx.MasterConfig{Engine: "codex", Model: "gpt-5.4"},
	}
	runDir := writeRunSpecFixture(t, repo, cfg)
	meta, err := EnsureRunMetadata(runDir, repo, cfg.Objective)
	if err != nil {
		t.Fatalf("EnsureRunMetadata: %v", err)
	}
	meta.Intent = intent
	if err := SaveRunMetadata(RunMetadataPath(runDir), meta); err != nil {
		t.Fatalf("SaveRunMetadata: %v", err)
	}
	if _, err := EnsureRuntimeState(runDir, cfg); err != nil {
		t.Fatalf("EnsureRuntimeState: %v", err)
	}
	if _, err := EnsureSessionsRuntimeState(runDir); err != nil {
		t.Fatalf("EnsureSessionsRuntimeState: %v", err)
	}
	if err := EnsureControlState(runDir); err != nil {
		t.Fatalf("EnsureControlState: %v", err)
	}
	if err := writeBoundaryFixture(t, runDir, &GoalState{
		Required: []GoalItem{
			{ID: "req-1", Text: "ship feature", Source: goalItemSourceUser, Role: goalItemRoleOutcome, State: goalItemStateOpen},
		},
	}); err != nil {
		t.Fatalf("writeBoundaryFixture: %v", err)
	}
	requiredRemaining := 1
	if err := SaveRunStatusRecord(RunStatusPath(runDir), &RunStatusRecord{
		Version:           1,
		Phase:             runStatusPhaseReview,
		RequiredRemaining: &requiredRemaining,
		OpenRequiredIDs:   []string{"req-1"},
		ActiveSessions:    []string{"session-1"},
		UpdatedAt:         "2026-03-28T10:10:00Z",
	}); err != nil {
		t.Fatalf("SaveRunStatusRecord: %v", err)
	}
	if err := SaveCoordinationState(CoordinationPath(runDir), &CoordinationState{
		Version: 1,
		Sessions: map[string]CoordinationSession{
			"session-1": {State: "active", Scope: "legacy active lane"},
		},
	}); err != nil {
		t.Fatalf("SaveCoordinationState: %v", err)
	}
	now := time.Now().UTC().Truncate(time.Second)
	if err := SaveControlRunState(ControlRunStatePath(runDir), &ControlRunState{
		Version:         1,
		GoalState:       "open",
		ContinuityState: "stopped",
		UpdatedAt:       now.Format(time.RFC3339),
	}); err != nil {
		t.Fatalf("SaveControlRunState: %v", err)
	}
	if err := SaveRunRuntimeState(RunRuntimeStatePath(runDir), &RunRuntimeState{
		Version:   1,
		Run:       runName,
		Mode:      string(goalx.ModeWorker),
		Active:    false,
		StartedAt: now.Add(-time.Minute).Format(time.RFC3339),
		StoppedAt: now.Format(time.RFC3339),
		UpdatedAt: now.Format(time.RFC3339),
	}); err != nil {
		t.Fatalf("SaveRunRuntimeState: %v", err)
	}
	if err := UpsertSessionRuntimeState(runDir, SessionRuntimeState{
		Name:  "session-1",
		State: "stopped",
		Mode:  string(goalx.ModeWorker),
	}); err != nil {
		t.Fatalf("UpsertSessionRuntimeState: %v", err)
	}
	if intent == runIntentEvolve {
		appendExperimentEventForTest(t, runDir, `{"version":1,"kind":"experiment.created","at":"2026-03-28T10:00:00Z","actor":"master","body":{"experiment_id":"exp-1","created_at":"2026-03-28T10:00:00Z"}}`)
	}
	return runDir
}

func TestRepairRepairsStoppedRunStatusAndEvolveFrontier(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	repo := initGitRepo(t)
	writeAndCommit(t, repo, "base.txt", "base", "base commit")
	runName, runDir := writeLifecycleRunFixture(t, repo)

	cfg, err := LoadRunSpec(runDir)
	if err != nil {
		t.Fatalf("LoadRunSpec: %v", err)
	}
	if err := RegisterActiveRun(repo, cfg); err != nil {
		t.Fatalf("RegisterActiveRun: %v", err)
	}
	meta, err := LoadRunMetadata(RunMetadataPath(runDir))
	if err != nil {
		t.Fatalf("LoadRunMetadata: %v", err)
	}
	meta.Intent = runIntentEvolve
	if err := SaveRunMetadata(RunMetadataPath(runDir), meta); err != nil {
		t.Fatalf("SaveRunMetadata: %v", err)
	}
	if err := writeBoundaryFixture(t, runDir, &GoalState{
		Required: []GoalItem{
			{ID: "req-1", Text: "ship feature", Source: goalItemSourceUser, Role: goalItemRoleOutcome, State: goalItemStateOpen},
		},
	}); err != nil {
		t.Fatalf("writeBoundaryFixture: %v", err)
	}
	requiredRemaining := 1
	if err := SaveRunStatusRecord(RunStatusPath(runDir), &RunStatusRecord{
		Version:           1,
		Phase:             runStatusPhaseReview,
		RequiredRemaining: &requiredRemaining,
		OpenRequiredIDs:   []string{"req-1"},
		ActiveSessions:    []string{"session-1"},
		UpdatedAt:         "2026-03-28T10:10:00Z",
	}); err != nil {
		t.Fatalf("SaveRunStatusRecord: %v", err)
	}
	if err := SaveCoordinationState(CoordinationPath(runDir), &CoordinationState{
		Version: 1,
		Sessions: map[string]CoordinationSession{
			"session-1": {State: "active", Scope: "legacy active lane"},
		},
	}); err != nil {
		t.Fatalf("SaveCoordinationState: %v", err)
	}
	appendExperimentEventForTest(t, runDir, `{"version":1,"kind":"experiment.created","at":"2026-03-28T10:00:00Z","actor":"master","body":{"experiment_id":"exp-1","created_at":"2026-03-28T10:00:00Z"}}`)
	now := time.Now().UTC().Truncate(time.Second)
	if err := SaveControlRunState(ControlRunStatePath(runDir), &ControlRunState{
		Version:         1,
		GoalState:       "open",
		ContinuityState: "stopped",
		UpdatedAt:       now.Format(time.RFC3339),
	}); err != nil {
		t.Fatalf("SaveControlRunState: %v", err)
	}
	if err := SaveRunRuntimeState(RunRuntimeStatePath(runDir), &RunRuntimeState{
		Version:   1,
		Run:       runName,
		Mode:      string(goalx.ModeWorker),
		Active:    false,
		StartedAt: now.Add(-time.Minute).Format(time.RFC3339),
		StoppedAt: now.Format(time.RFC3339),
		UpdatedAt: now.Format(time.RFC3339),
	}); err != nil {
		t.Fatalf("SaveRunRuntimeState: %v", err)
	}
	if err := UpsertSessionRuntimeState(runDir, SessionRuntimeState{
		Name:  "session-1",
		State: "stopped",
		Mode:  string(goalx.ModeWorker),
	}); err != nil {
		t.Fatalf("UpsertSessionRuntimeState: %v", err)
	}

	if err := Repair(repo, []string{"--run", runName}); err != nil {
		t.Fatalf("Repair: %v", err)
	}

	status, err := LoadRunStatusRecord(RunStatusPath(runDir))
	if err != nil {
		t.Fatalf("LoadRunStatusRecord: %v", err)
	}
	if status.Phase != runStatusPhaseStopped {
		t.Fatalf("status phase = %q, want %q", status.Phase, runStatusPhaseStopped)
	}
	if len(status.ActiveSessions) != 0 {
		t.Fatalf("status active_sessions = %v, want empty", status.ActiveSessions)
	}
	coord, err := LoadCoordinationState(CoordinationPath(runDir))
	if err != nil {
		t.Fatalf("LoadCoordinationState: %v", err)
	}
	if coord.Sessions["session-1"].State != "stopped" {
		t.Fatalf("coordination session-1 state = %q, want stopped", coord.Sessions["session-1"].State)
	}

	facts, err := BuildEvolveFacts(runDir)
	if err != nil {
		t.Fatalf("BuildEvolveFacts: %v", err)
	}
	if facts.FrontierState != EvolveFrontierStopped {
		t.Fatalf("frontier_state = %q, want %q", facts.FrontierState, EvolveFrontierStopped)
	}
	if facts.LastStopReasonCode != "user_redirected" {
		t.Fatalf("last_stop_reason_code = %q, want user_redirected", facts.LastStopReasonCode)
	}
	if facts.LastStopAt != now.Format(time.RFC3339) {
		t.Fatalf("last_stop_at = %q, want %q", facts.LastStopAt, now.Format(time.RFC3339))
	}
}

func TestRepairRejectsActiveRun(t *testing.T) {
	repo, runDir, cfg, _ := writeGuidanceRunFixture(t)
	installFakePresenceTmux(t, true, "master", "%0\tmaster\n")
	if err := SaveControlRunState(ControlRunStatePath(runDir), &ControlRunState{
		Version:         1,
		GoalState:       "open",
		ContinuityState: "running",
		UpdatedAt:       time.Now().UTC().Format(time.RFC3339),
	}); err != nil {
		t.Fatalf("SaveControlRunState: %v", err)
	}

	err := Repair(repo, []string{"--run", cfg.Name})
	if err == nil || !strings.Contains(err.Error(), "only repairs inactive runs") {
		t.Fatalf("Repair error = %v, want inactive-run rejection", err)
	}
}

func TestRepairRepairsStrandedRunAndRetiresReminders(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	repo := initGitRepo(t)
	writeAndCommit(t, repo, "base.txt", "base", "base commit")
	runName := "repair-stranded"
	runDir := writeRepairableStoppedRunFixture(t, repo, runName, "")

	if err := SaveControlRunState(ControlRunStatePath(runDir), &ControlRunState{
		Version:         1,
		GoalState:       "open",
		ContinuityState: "stranded",
		UpdatedAt:       time.Now().UTC().Format(time.RFC3339),
	}); err != nil {
		t.Fatalf("SaveControlRunState: %v", err)
	}
	if err := os.WriteFile(RunStatusPath(runDir), []byte(`{"version":1,"phase":"complete","required_remaining":0,"updated_at":"2026-03-28T10:10:00Z"}`), 0o644); err != nil {
		t.Fatalf("write stale status: %v", err)
	}
	if _, err := QueueControlReminderWithEngine(runDir, "master-wake", "control-cycle", "gx-demo:master", "codex"); err != nil {
		t.Fatalf("QueueControlReminderWithEngine: %v", err)
	}

	if err := Repair(repo, []string{"--run", runName}); err != nil {
		t.Fatalf("Repair: %v", err)
	}

	status, err := LoadRunStatusRecord(RunStatusPath(runDir))
	if err != nil {
		t.Fatalf("LoadRunStatusRecord: %v", err)
	}
	if status.Phase != runStatusPhaseStranded {
		t.Fatalf("status phase = %q, want %q", status.Phase, runStatusPhaseStranded)
	}
	reminders, err := LoadControlReminders(ControlRemindersPath(runDir))
	if err != nil {
		t.Fatalf("LoadControlReminders: %v", err)
	}
	if len(reminders.Items) != 1 || !reminders.Items[0].Suppressed {
		t.Fatalf("reminders = %+v, want suppressed master reminder", reminders.Items)
	}
}

func TestRepairFactsOnlyAllowsActiveRunAndRefreshesComputedFacts(t *testing.T) {
	repo, runDir, cfg, _ := writeGuidanceRunFixture(t)
	now := time.Now().UTC().Format(time.RFC3339)
	if err := SaveControlRunState(ControlRunStatePath(runDir), &ControlRunState{
		Version:         1,
		GoalState:       "open",
		ContinuityState: "running",
		UpdatedAt:       now,
	}); err != nil {
		t.Fatalf("SaveControlRunState: %v", err)
	}
	if err := SaveRunRuntimeState(RunRuntimeStatePath(runDir), &RunRuntimeState{
		Version:   1,
		Run:       cfg.Name,
		Mode:      string(cfg.Mode),
		Active:    true,
		StartedAt: now,
		UpdatedAt: now,
	}); err != nil {
		t.Fatalf("SaveRunRuntimeState: %v", err)
	}

	if err := Repair(repo, []string{"--run", cfg.Name, "--facts-only"}); err != nil {
		t.Fatalf("Repair --facts-only: %v", err)
	}

	if _, err := LoadActivitySnapshot(ActivityPath(runDir)); err != nil {
		t.Fatalf("LoadActivitySnapshot: %v", err)
	}
	if _, err := LoadResourceState(ResourceStatePath(runDir)); err != nil {
		t.Fatalf("LoadResourceState: %v", err)
	}
	if _, err := LoadWorktreeSnapshot(WorktreeSnapshotPath(runDir)); err != nil {
		t.Fatalf("LoadWorktreeSnapshot: %v", err)
	}
	if _, err := LoadTransportFacts(TransportFactsPath(runDir)); err != nil {
		t.Fatalf("LoadTransportFacts: %v", err)
	}

	status, err := LoadRunStatusRecord(RunStatusPath(runDir))
	if err != nil {
		t.Fatalf("LoadRunStatusRecord: %v", err)
	}
	if status != nil && status.Phase == runStatusPhaseStopped {
		t.Fatalf("facts-only repair should not rewrite active-run semantic surfaces: %+v", status)
	}
}

func TestRepairAllStoppedRepairsEveryStoppedRunInProject(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	repo := initGitRepo(t)
	writeAndCommit(t, repo, "base.txt", "base", "base commit")

	runDirA := writeRepairableStoppedRunFixture(t, repo, "repair-a", "")
	runDirB := writeRepairableStoppedRunFixture(t, repo, "repair-b", runIntentEvolve)

	if err := Repair(repo, []string{"--all-stopped"}); err != nil {
		t.Fatalf("Repair --all-stopped: %v", err)
	}

	for _, runDir := range []string{runDirA, runDirB} {
		status, err := LoadRunStatusRecord(RunStatusPath(runDir))
		if err != nil {
			t.Fatalf("LoadRunStatusRecord(%s): %v", runDir, err)
		}
		if status.Phase != runStatusPhaseStopped {
			t.Fatalf("%s status phase = %q, want stopped", runDir, status.Phase)
		}
	}
	facts, err := BuildEvolveFacts(runDirB)
	if err != nil {
		t.Fatalf("BuildEvolveFacts(repair-b): %v", err)
	}
	if facts.FrontierState != EvolveFrontierStopped {
		t.Fatalf("repair-b frontier_state = %q, want stopped", facts.FrontierState)
	}
}

func TestRepairWritesAuditLog(t *testing.T) {
	repo, runDir, cfg, _ := writeGuidanceRunFixture(t)
	now := time.Now().UTC().Format(time.RFC3339)
	if err := SaveControlRunState(ControlRunStatePath(runDir), &ControlRunState{
		Version:         1,
		GoalState:       "open",
		ContinuityState: "running",
		UpdatedAt:       now,
	}); err != nil {
		t.Fatalf("SaveControlRunState: %v", err)
	}
	if err := SaveRunRuntimeState(RunRuntimeStatePath(runDir), &RunRuntimeState{
		Version:   1,
		Run:       cfg.Name,
		Mode:      string(cfg.Mode),
		Active:    true,
		StartedAt: now,
		UpdatedAt: now,
	}); err != nil {
		t.Fatalf("SaveRunRuntimeState: %v", err)
	}

	if err := Repair(repo, []string{"--run", cfg.Name, "--facts-only"}); err != nil {
		t.Fatalf("Repair --facts-only: %v", err)
	}

	data, err := os.ReadFile(filepath.Join(runDir, "runtime-host.log"))
	if err != nil {
		t.Fatalf("read runtime-host.log: %v", err)
	}
	text := string(data)
	for _, want := range []string{
		"manual_repair",
		"mode=facts_only",
		"lifecycle=running",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("runtime-host.log missing %q:\n%s", want, text)
		}
	}
}
