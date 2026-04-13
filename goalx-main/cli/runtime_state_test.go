package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	goalx "github.com/vonbai/goalx"
)

func TestSaveRunRuntimeStateDoesNotPersistRecommendationField(t *testing.T) {
	runDir := t.TempDir()
	path := RunRuntimeStatePath(runDir)
	if err := SaveRunRuntimeState(path, &RunRuntimeState{
		Version:   1,
		Run:       "demo",
		Mode:      "develop",
		Active:    true,
		Phase:     "working",
		UpdatedAt: "2026-03-26T00:00:00Z",
	}); err != nil {
		t.Fatalf("SaveRunRuntimeState: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read run runtime state: %v", err)
	}
	text := string(data)
	if strings.Contains(text, `"recommendation"`) {
		t.Fatalf("run runtime state should not persist recommendation:\n%s", text)
	}
}

func TestSnapshotSessionRuntimeDoesNotProjectAckInboxAsLifecycleState(t *testing.T) {
	runDir := t.TempDir()
	worktreePath := t.TempDir()
	if err := os.MkdirAll(filepath.Dir(JournalPath(runDir, "session-1")), 0o755); err != nil {
		t.Fatalf("mkdir journals dir: %v", err)
	}
	if err := os.WriteFile(JournalPath(runDir, "session-1"), []byte("{\"round\":2,\"status\":\"ack-inbox\",\"desc\":\"read inbox\",\"owner_scope\":\"fix queue drift\"}\n"), 0o644); err != nil {
		t.Fatalf("write journal: %v", err)
	}

	snapshot, err := SnapshotSessionRuntime(runDir, "session-1", worktreePath)
	if err != nil {
		t.Fatalf("SnapshotSessionRuntime: %v", err)
	}
	if snapshot.State != "" {
		t.Fatalf("snapshot state = %q, want empty for control-only ack status", snapshot.State)
	}
	if snapshot.LastJournalState != "ack-inbox" {
		t.Fatalf("last journal state = %q, want ack-inbox", snapshot.LastJournalState)
	}
	if snapshot.OwnerScope != "fix queue drift" {
		t.Fatalf("owner scope = %q, want fix queue drift", snapshot.OwnerScope)
	}
	if snapshot.LastRound != 2 {
		t.Fatalf("last round = %d, want 2", snapshot.LastRound)
	}
}

func TestRefreshSessionRuntimeProjectionPreservesParkedState(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	repo := initGitRepo(t)
	writeAndCommit(t, repo, "README.md", "base", "base commit")

	runName, runDir := writeLifecycleRunFixture(t, repo)
	if err := UpsertSessionRuntimeState(runDir, SessionRuntimeState{
		Name:  "session-1",
		State: "parked",
		Mode:  string(goalx.ModeWorker),
	}); err != nil {
		t.Fatalf("UpsertSessionRuntimeState: %v", err)
	}
	if err := os.WriteFile(JournalPath(runDir, "session-1"), []byte("{\"round\":3,\"status\":\"progress\",\"desc\":\"still working\",\"owner_scope\":\"ui slice\"}\n"), 0o644); err != nil {
		t.Fatalf("write journal: %v", err)
	}

	if err := RefreshSessionRuntimeProjection(runDir, runName); err != nil {
		t.Fatalf("RefreshSessionRuntimeProjection: %v", err)
	}

	state, err := LoadSessionsRuntimeState(SessionsRuntimeStatePath(runDir))
	if err != nil {
		t.Fatalf("LoadSessionsRuntimeState: %v", err)
	}
	if got := state.Sessions["session-1"].State; got != "parked" {
		t.Fatalf("session-1 state = %q, want parked", got)
	}
}

func TestRefreshSessionRuntimeProjectionPreservesActiveStateWhenJournalHasNotAdvanced(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	repo := initGitRepo(t)
	writeAndCommit(t, repo, "README.md", "base", "base commit")

	runName, runDir := writeLifecycleRunFixture(t, repo)
	if err := UpsertSessionRuntimeState(runDir, SessionRuntimeState{
		Name:             "session-1",
		State:            "active",
		Mode:             string(goalx.ModeWorker),
		LastRound:        3,
		LastJournalState: "idle",
	}); err != nil {
		t.Fatalf("UpsertSessionRuntimeState: %v", err)
	}
	if err := os.WriteFile(JournalPath(runDir, "session-1"), []byte("{\"round\":3,\"status\":\"idle\",\"desc\":\"awaiting master\",\"owner_scope\":\"ui slice\"}\n"), 0o644); err != nil {
		t.Fatalf("write journal: %v", err)
	}

	if err := RefreshSessionRuntimeProjection(runDir, runName); err != nil {
		t.Fatalf("RefreshSessionRuntimeProjection: %v", err)
	}

	state, err := LoadSessionsRuntimeState(SessionsRuntimeStatePath(runDir))
	if err != nil {
		t.Fatalf("LoadSessionsRuntimeState: %v", err)
	}
	sess := state.Sessions["session-1"]
	if got := sess.State; got != "active" {
		t.Fatalf("session-1 state = %q, want active", got)
	}
	if got := sess.LastJournalState; got != "idle" {
		t.Fatalf("session-1 last_journal_state = %q, want idle", got)
	}
	if got := sess.OwnerScope; got != "ui slice" {
		t.Fatalf("session-1 owner_scope = %q, want ui slice", got)
	}
}

func TestRefreshSessionRuntimeProjectionClearsStaleParkedDirtyFacts(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	repo := initGitRepo(t)
	writeAndCommit(t, repo, "README.md", "base", "base commit")

	runName, runDir := writeLifecycleRunFixture(t, repo)
	if err := UpsertSessionRuntimeState(runDir, SessionRuntimeState{
		Name:       "session-1",
		State:      "parked",
		Mode:       string(goalx.ModeWorker),
		DirtyFiles: 42,
		DiffStat:   "old stale diff",
	}); err != nil {
		t.Fatalf("UpsertSessionRuntimeState: %v", err)
	}

	if err := RefreshSessionRuntimeProjection(runDir, runName); err != nil {
		t.Fatalf("RefreshSessionRuntimeProjection: %v", err)
	}

	state, err := LoadSessionsRuntimeState(SessionsRuntimeStatePath(runDir))
	if err != nil {
		t.Fatalf("LoadSessionsRuntimeState: %v", err)
	}
	sess := state.Sessions["session-1"]
	if sess.DirtyFiles != 0 || sess.DiffStat != "" {
		t.Fatalf("session-1 dirty snapshot = %+v, want cleared dirty facts", sess)
	}
	if sess.State != "parked" {
		t.Fatalf("session-1 state = %q, want parked", sess.State)
	}
}

func TestRefreshSessionRuntimeProjectionFallsBackWhenSessionWorktreePathEmpty(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	repo := initGitRepo(t)
	writeAndCommit(t, repo, "README.md", "base", "base commit")

	runName, runDir := writeLifecycleRunFixture(t, repo)
	legacyWorktree := WorktreePath(runDir, runName, 1)
	if err := os.WriteFile(filepath.Join(legacyWorktree, "tracked.txt"), []byte("dirty\n"), 0o644); err != nil {
		t.Fatalf("write tracked file: %v", err)
	}
	if err := UpsertSessionRuntimeState(runDir, SessionRuntimeState{
		Name:         "session-1",
		State:        "parked",
		Mode:         string(goalx.ModeWorker),
		WorktreePath: "",
	}); err != nil {
		t.Fatalf("UpsertSessionRuntimeState: %v", err)
	}

	if err := RefreshSessionRuntimeProjection(runDir, runName); err != nil {
		t.Fatalf("RefreshSessionRuntimeProjection: %v", err)
	}

	state, err := LoadSessionsRuntimeState(SessionsRuntimeStatePath(runDir))
	if err != nil {
		t.Fatalf("LoadSessionsRuntimeState: %v", err)
	}
	sess := state.Sessions["session-1"]
	if sess.WorktreePath != legacyWorktree {
		t.Fatalf("session-1 worktree_path = %q, want fallback %q", sess.WorktreePath, legacyWorktree)
	}
}

func TestUpsertSessionRuntimeStatePreservesConcurrentEntries(t *testing.T) {
	runDir := t.TempDir()

	start := make(chan struct{})
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		name := fmt.Sprintf("session-%d", i+1)
		wg.Add(1)
		go func(sessionName string) {
			defer wg.Done()
			<-start
			if err := UpsertSessionRuntimeState(runDir, SessionRuntimeState{
				Name:       sessionName,
				State:      "active",
				Mode:       string(goalx.ModeWorker),
				OwnerScope: "concurrent slice",
			}); err != nil {
				t.Errorf("UpsertSessionRuntimeState(%s): %v", sessionName, err)
			}
		}(name)
	}
	close(start)
	wg.Wait()

	state, err := LoadSessionsRuntimeState(SessionsRuntimeStatePath(runDir))
	if err != nil {
		t.Fatalf("LoadSessionsRuntimeState: %v", err)
	}
	if state == nil {
		t.Fatal("sessions runtime state missing")
	}
	for i := 0; i < 8; i++ {
		name := fmt.Sprintf("session-%d", i+1)
		if _, ok := state.Sessions[name]; !ok {
			t.Fatalf("missing %s in %#v", name, state.Sessions)
		}
	}
}
