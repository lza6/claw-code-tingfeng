package cli

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCopyGitignoredFilesMirrorsIgnoredContent(t *testing.T) {
	repo := initGitRepo(t)
	writeAndCommit(t, repo, "tracked.txt", "base\n", "base commit")
	writeAndCommit(t, repo, ".gitignore", "CLAUDE.md\n", "add ignore rules")
	writeTestFile(t, repo, "CLAUDE.md", "local instructions\n")

	worktree := filepath.Join(t.TempDir(), "wt")
	if err := CreateWorktree(repo, worktree, "goalx/demo/root"); err != nil {
		t.Fatalf("CreateWorktree: %v", err)
	}

	if err := CopyGitignoredFiles(repo, worktree); err != nil {
		t.Fatalf("CopyGitignoredFiles: %v", err)
	}

	data, err := os.ReadFile(filepath.Join(worktree, "CLAUDE.md"))
	if err != nil {
		t.Fatalf("read mirrored file: %v", err)
	}
	if string(data) != "local instructions\n" {
		t.Fatalf("mirrored file = %q, want local instructions", string(data))
	}

	status := strings.TrimSpace(gitOutput(t, worktree, "status", "--short"))
	if status != "" {
		t.Fatalf("worktree should stay clean, got:\n%s", status)
	}
}

func TestCopyGitignoredFilesPreservesDirectoryStructure(t *testing.T) {
	repo := initGitRepo(t)
	writeAndCommit(t, repo, "tracked.txt", "base\n", "base commit")
	writeAndCommit(t, repo, ".gitignore", "docs/\n", "add ignore rules")
	writeTestFile(t, repo, "docs/nested/plan.md", "mirror me\n")

	worktree := filepath.Join(t.TempDir(), "wt")
	if err := CreateWorktree(repo, worktree, "goalx/demo/root"); err != nil {
		t.Fatalf("CreateWorktree: %v", err)
	}

	if err := CopyGitignoredFiles(repo, worktree); err != nil {
		t.Fatalf("CopyGitignoredFiles: %v", err)
	}

	data, err := os.ReadFile(filepath.Join(worktree, "docs", "nested", "plan.md"))
	if err != nil {
		t.Fatalf("read mirrored nested file: %v", err)
	}
	if string(data) != "mirror me\n" {
		t.Fatalf("mirrored nested file = %q, want %q", string(data), "mirror me\n")
	}
}

func TestCopyGitignoredFilesSkipsNonexistent(t *testing.T) {
	repo := initGitRepo(t)
	writeAndCommit(t, repo, "tracked.txt", "base\n", "base commit")
	writeAndCommit(t, repo, ".gitignore", "missing*.txt\n", "add ignore rules")

	worktree := filepath.Join(t.TempDir(), "wt")
	if err := CreateWorktree(repo, worktree, "goalx/demo/root"); err != nil {
		t.Fatalf("CreateWorktree: %v", err)
	}

	if err := CopyGitignoredFiles(repo, worktree); err != nil {
		t.Fatalf("CopyGitignoredFiles: %v", err)
	}
}

func writeTestFile(t *testing.T, root, name, content string) {
	t.Helper()

	path := filepath.Join(root, name)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("mkdir %s: %v", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("write %s: %v", name, err)
	}
}
