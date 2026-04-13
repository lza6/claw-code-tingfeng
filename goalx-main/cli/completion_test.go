package cli

import (
	"path/filepath"
	"testing"
)

func TestCompletionStatePathUsesProofNamespace(t *testing.T) {
	runDir := t.TempDir()
	want := filepath.Join(runDir, "proof", "completion.json")
	if got := CompletionStatePath(runDir); got != want {
		t.Fatalf("CompletionStatePath = %q, want %q", got, want)
	}
}
