package cli

import (
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestGenerateAdapterBlocksOnUnreadSessionInbox(t *testing.T) {
	worktree := filepath.Join(t.TempDir(), "worktree")
	if err := os.MkdirAll(worktree, 0o755); err != nil {
		t.Fatalf("mkdir worktree: %v", err)
	}

	controlDir := filepath.Join(t.TempDir(), "control with 'quote'")
	if err := os.MkdirAll(filepath.Join(controlDir, "inbox"), 0o755); err != nil {
		t.Fatalf("mkdir control dir: %v", err)
	}
	inboxPath := filepath.Join(controlDir, "inbox", "session 1.jsonl")
	cursorPath := filepath.Join(controlDir, "session 1-cursor.json")
	if err := os.WriteFile(inboxPath, []byte(`{"id":1,"type":"tell","source":"user","body":"pending","created_at":"2026-03-24T00:00:00Z"}`+"\n"), 0o644); err != nil {
		t.Fatalf("write inbox file: %v", err)
	}

	if err := GenerateAdapter("claude-code", worktree, inboxPath, cursorPath); err != nil {
		t.Fatalf("GenerateAdapter: %v", err)
	}

	data, err := os.ReadFile(filepath.Join(worktree, ".claude", "hooks.json"))
	if err != nil {
		t.Fatalf("read hooks.json: %v", err)
	}

	var doc struct {
		Hooks []struct {
			Event   string `json:"event"`
			Command string `json:"command"`
		} `json:"hooks"`
	}
	if err := json.Unmarshal(data, &doc); err != nil {
		t.Fatalf("unmarshal hooks.json: %v", err)
	}
	if len(doc.Hooks) != 1 {
		t.Fatalf("len(Hooks) = %d, want 1", len(doc.Hooks))
	}

	out, err := exec.Command("bash", "-lc", doc.Hooks[0].Command).CombinedOutput()
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		t.Fatalf("run hook command: %v\n%s", err, string(out))
	}
	if exitErr.ExitCode() != 2 {
		t.Fatalf("exit code = %d, want 2", exitErr.ExitCode())
	}
	if !strings.Contains(string(out), "INBOX PENDING") {
		t.Fatalf("hook output = %q, want inbox warning", string(out))
	}
	if !strings.Contains(string(out), inboxPath) {
		t.Fatalf("hook output = %q, want path %q", string(out), inboxPath)
	}
}

