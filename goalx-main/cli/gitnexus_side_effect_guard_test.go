package cli

import (
	"os"
	"path/filepath"
	"testing"
)

func TestWithGitNexusSideEffectGuardRestoresGitIgnoreMutation(t *testing.T) {
	scopePath := t.TempDir()
	original := "node_modules/\n"
	if err := os.WriteFile(filepath.Join(scopePath, ".gitignore"), []byte(original), 0o644); err != nil {
		t.Fatalf("write .gitignore: %v", err)
	}

	err := withGitNexusSideEffectGuard(scopePath, func() error {
		return os.WriteFile(filepath.Join(scopePath, ".gitignore"), []byte(original+".gitnexus\n"), 0o644)
	})
	if err != nil {
		t.Fatalf("withGitNexusSideEffectGuard: %v", err)
	}

	data, err := os.ReadFile(filepath.Join(scopePath, ".gitignore"))
	if err != nil {
		t.Fatalf("read .gitignore: %v", err)
	}
	if string(data) != original {
		t.Fatalf(".gitignore = %q, want restored %q", string(data), original)
	}
}
