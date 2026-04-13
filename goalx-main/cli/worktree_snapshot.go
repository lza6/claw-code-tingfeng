package cli

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"hash"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

type WorktreeSnapshot struct {
	CheckedAt      string                      `json:"checked_at"`
	Root           WorktreeDiffStat            `json:"root"`
	RootLineage    *WorktreeLineage            `json:"root_lineage,omitempty"`
	Sessions       map[string]WorktreeDiffStat `json:"sessions,omitempty"`
	SessionLineage map[string]WorktreeLineage  `json:"session_lineage,omitempty"`
}

type WorktreeDiffStat struct {
	DirtyFiles      int    `json:"dirty_files"`
	Insertions      int    `json:"insertions"`
	Deletions       int    `json:"deletions"`
	DiffFingerprint string `json:"diff_fingerprint,omitempty"`
}

type WorktreeLineage struct {
	Branch         string `json:"branch,omitempty"`
	ParentSelector string `json:"parent_selector,omitempty"`
	ParentRef      string `json:"parent_ref,omitempty"`
	HeadRevision   string `json:"head_revision,omitempty"`
	ParentRevision string `json:"parent_revision,omitempty"`
	AheadCommits   int    `json:"ahead_commits,omitempty"`
	BehindCommits  int    `json:"behind_commits,omitempty"`
}

var (
	shortstatInsertionsRE = regexp.MustCompile(`(\d+)\s+insertions?\(\+\)`)
	shortstatDeletionsRE  = regexp.MustCompile(`(\d+)\s+deletions?\(-\)`)
)

func WorktreeSnapshotPath(runDir string) string {
	return filepath.Join(ControlDir(runDir), "worktree-snapshot.json")
}

func SnapshotWorktrees(runDir string) (*WorktreeSnapshot, error) {
	cfg, err := LoadRunSpec(runDir)
	if err != nil {
		return nil, err
	}
	meta, err := LoadRunMetadata(RunMetadataPath(runDir))
	if err != nil {
		return nil, err
	}
	sessionsState, err := EnsureSessionsRuntimeState(runDir)
	if err != nil {
		return nil, fmt.Errorf("load session runtime state: %w", err)
	}

	snapshot := &WorktreeSnapshot{
		CheckedAt: time.Now().UTC().Format(time.RFC3339),
	}
	rootWorktreePath := RunWorktreePath(runDir)
	if worktreePathAvailable(rootWorktreePath) {
		root, err := snapshotWorktreeDiffStat(rootWorktreePath)
		if err != nil {
			return nil, err
		}
		snapshot.Root = root
		if meta != nil {
			if lineage, err := snapshotRootWorktreeLineage(meta, rootWorktreePath); err != nil {
				return nil, err
			} else {
				snapshot.RootLineage = lineage
			}
		}
	}

	indexes, err := existingSessionIndexes(runDir)
	if err != nil {
		return nil, err
	}
	for _, idx := range indexes {
		sessionName := SessionName(idx)
		worktreePath := resolvedSessionWorktreePath(runDir, cfg.Name, sessionName, sessionsState)
		if !worktreePathAvailable(worktreePath) {
			continue
		}
		diffStat, err := snapshotWorktreeDiffStat(worktreePath)
		if err != nil {
			return nil, err
		}
		if snapshot.Sessions == nil {
			snapshot.Sessions = make(map[string]WorktreeDiffStat)
		}
		snapshot.Sessions[sessionName] = diffStat
		lineage, err := snapshotSessionWorktreeLineage(runDir, cfg.Name, sessionName, worktreePath, sessionsState)
		if err != nil {
			return nil, err
		}
		if lineage != nil {
			if snapshot.SessionLineage == nil {
				snapshot.SessionLineage = make(map[string]WorktreeLineage)
			}
			snapshot.SessionLineage[sessionName] = *lineage
		}
	}
	return snapshot, nil
}

func LoadWorktreeSnapshot(path string) (*WorktreeSnapshot, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	snapshot := &WorktreeSnapshot{}
	if len(data) == 0 {
		return snapshot, nil
	}
	if err := json.Unmarshal(data, snapshot); err != nil {
		return nil, fmt.Errorf("parse worktree snapshot: %w", err)
	}
	return snapshot, nil
}

func SaveWorktreeSnapshot(runDir string, snap *WorktreeSnapshot) error {
	if snap == nil {
		return fmt.Errorf("worktree snapshot is nil")
	}
	if snap.CheckedAt == "" {
		snap.CheckedAt = time.Now().UTC().Format(time.RFC3339)
	}
	return writeJSONFile(WorktreeSnapshotPath(runDir), snap)
}

func RefreshWorktreeSnapshot(runDir string) error {
	snapshot, err := SnapshotWorktrees(runDir)
	if err != nil {
		return err
	}
	return SaveWorktreeSnapshot(runDir, snapshot)
}

func snapshotWorktreeDiffStat(worktreePath string) (WorktreeDiffStat, error) {
	if !worktreePathAvailable(worktreePath) {
		return WorktreeDiffStat{}, nil
	}
	dirtyFiles, _, err := snapshotWorktreeState(worktreePath)
	if err != nil {
		return WorktreeDiffStat{}, err
	}
	fingerprint, err := snapshotWorktreeDiffFingerprint(worktreePath, dirtyFiles)
	if err != nil {
		return WorktreeDiffStat{}, err
	}
	out, err := exec.Command("git", "-C", worktreePath, "diff", "--shortstat").CombinedOutput()
	if err != nil {
		if os.IsNotExist(err) || bytes.Contains(bytes.ToLower(out), []byte("not a git repository")) {
			return WorktreeDiffStat{DirtyFiles: dirtyFiles, DiffFingerprint: fingerprint}, nil
		}
		return WorktreeDiffStat{}, fmt.Errorf("git diff --shortstat in %s: %w: %s", worktreePath, err, out)
	}
	text := string(out)
	return WorktreeDiffStat{
		DirtyFiles:      dirtyFiles,
		Insertions:      parseShortstatCount(shortstatInsertionsRE, text),
		Deletions:       parseShortstatCount(shortstatDeletionsRE, text),
		DiffFingerprint: fingerprint,
	}, nil
}

func snapshotWorktreeDiffFingerprint(worktreePath string, dirtyFiles int) (string, error) {
	if !worktreePathAvailable(worktreePath) || dirtyFiles == 0 {
		return "", nil
	}
	statusOut, err := exec.Command("git", "-C", worktreePath, "status", "--porcelain=v1", "-uall").CombinedOutput()
	if err != nil {
		if os.IsNotExist(err) || bytes.Contains(bytes.ToLower(statusOut), []byte("not a git repository")) {
			return "", nil
		}
		return "", fmt.Errorf("git status --porcelain=v1 -uall in %s: %w: %s", worktreePath, err, statusOut)
	}
	stagedOut, err := exec.Command("git", "-C", worktreePath, "diff", "--binary", "--cached", "--no-color", "--no-ext-diff").CombinedOutput()
	if err != nil {
		if os.IsNotExist(err) || bytes.Contains(bytes.ToLower(stagedOut), []byte("not a git repository")) {
			return "", nil
		}
		return "", fmt.Errorf("git diff --binary --cached in %s: %w: %s", worktreePath, err, stagedOut)
	}
	unstagedOut, err := exec.Command("git", "-C", worktreePath, "diff", "--binary", "--no-color", "--no-ext-diff").CombinedOutput()
	if err != nil {
		if os.IsNotExist(err) || bytes.Contains(bytes.ToLower(unstagedOut), []byte("not a git repository")) {
			return "", nil
		}
		return "", fmt.Errorf("git diff --binary in %s: %w: %s", worktreePath, err, unstagedOut)
	}
	untrackedFiles, err := gitUntrackedFiles(worktreePath)
	if err != nil {
		return "", err
	}

	hasher := sha256.New()
	hasher.Write([]byte(strings.TrimSpace(string(statusOut))))
	hasher.Write([]byte("\n--staged--\n"))
	hasher.Write(stagedOut)
	hasher.Write([]byte("\n--unstaged--\n"))
	hasher.Write(unstagedOut)
	for _, relPath := range untrackedFiles {
		if err := hashUntrackedPath(hasher, worktreePath, relPath); err != nil {
			return "", err
		}
	}
	return "sha256:" + hex.EncodeToString(hasher.Sum(nil)), nil
}

func hashUntrackedPath(hasher hash.Hash, worktreePath, relPath string) error {
	fullPath := filepath.Join(worktreePath, relPath)
	info, err := os.Lstat(fullPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("stat untracked path %s in %s: %w", relPath, worktreePath, err)
	}
	hasher.Write([]byte("\n--untracked--\n"))
	hasher.Write([]byte(relPath))
	hasher.Write([]byte{'\n'})
	switch {
	case info.IsDir():
		hasher.Write([]byte("node=dir\n"))
		return nil
	case info.Mode()&os.ModeSymlink != 0:
		target, err := os.Readlink(fullPath)
		if err != nil {
			return fmt.Errorf("read untracked symlink %s in %s: %w", relPath, worktreePath, err)
		}
		hasher.Write([]byte("node=symlink\n"))
		hasher.Write([]byte(target))
		return nil
	case !info.Mode().IsRegular():
		hasher.Write([]byte("node=" + info.Mode().String() + "\n"))
		return nil
	default:
		data, err := os.ReadFile(fullPath)
		if err != nil {
			if os.IsNotExist(err) {
				return nil
			}
			return fmt.Errorf("read untracked file %s in %s: %w", relPath, worktreePath, err)
		}
		hasher.Write(data)
		return nil
	}
}

func gitUntrackedFiles(worktreePath string) ([]string, error) {
	out, err := exec.Command("git", "-C", worktreePath, "ls-files", "--others", "--exclude-standard", "-z").CombinedOutput()
	if err != nil {
		if os.IsNotExist(err) || bytes.Contains(bytes.ToLower(out), []byte("not a git repository")) {
			return nil, nil
		}
		return nil, fmt.Errorf("git ls-files --others --exclude-standard in %s: %w: %s", worktreePath, err, out)
	}
	raw := strings.Split(string(out), "\x00")
	files := make([]string, 0, len(raw))
	for _, file := range raw {
		file = strings.TrimSpace(file)
		if file == "" {
			continue
		}
		if isAllowedLocalConfigPath(file) {
			continue
		}
		files = append(files, file)
	}
	sort.Strings(files)
	return files, nil
}

func parseShortstatCount(pattern *regexp.Regexp, text string) int {
	match := pattern.FindStringSubmatch(text)
	if len(match) < 2 {
		return 0
	}
	var count int
	fmt.Sscanf(match[1], "%d", &count)
	return count
}

func snapshotRootWorktreeLineage(meta *RunMetadata, worktreePath string) (*WorktreeLineage, error) {
	if meta == nil || strings.TrimSpace(meta.ProjectRoot) == "" {
		return nil, nil
	}
	parentRevision, err := gitRevision(meta.ProjectRoot, "HEAD")
	if err != nil {
		return nil, err
	}
	return snapshotWorktreeLineage(worktreePath, "source-root", "HEAD", parentRevision)
}

func snapshotSessionWorktreeLineage(runDir, runName, sessionName, worktreePath string, state *SessionsRuntimeState) (*WorktreeLineage, error) {
	identity, err := LoadSessionIdentity(SessionIdentityPath(runDir, sessionName))
	if err != nil {
		return nil, err
	}
	if identity == nil || strings.TrimSpace(identity.BaseBranch) == "" {
		return nil, nil
	}
	parentSelector := strings.TrimSpace(identity.BaseBranchSelector)
	if parentSelector == "" {
		parentSelector = "recorded-base"
	}
	lineage, err := snapshotWorktreeLineage(worktreePath, parentSelector, identity.BaseBranch, "")
	if err != nil {
		return nil, err
	}
	if lineage != nil && strings.TrimSpace(lineage.Branch) == "" {
		lineage.Branch = resolvedSessionBranch(runDir, runName, sessionName, state)
	}
	return lineage, nil
}

func snapshotWorktreeLineage(worktreePath, parentSelector, parentRef, parentRevision string) (*WorktreeLineage, error) {
	if !worktreePathAvailable(worktreePath) || strings.TrimSpace(parentRef) == "" {
		return nil, nil
	}
	branch, err := gitCurrentBranch(worktreePath)
	if err != nil {
		return nil, err
	}
	headRevision, err := gitRevision(worktreePath, "HEAD")
	if err != nil {
		return nil, err
	}
	if strings.TrimSpace(parentRevision) == "" {
		parentRevision, err = gitRevision(worktreePath, parentRef)
		if err != nil {
			return nil, err
		}
	}
	ahead, behind, err := gitAheadBehindCounts(worktreePath, parentRevision, headRevision)
	if err != nil {
		return nil, err
	}
	return &WorktreeLineage{
		Branch:         branch,
		ParentSelector: strings.TrimSpace(parentSelector),
		ParentRef:      strings.TrimSpace(parentRef),
		HeadRevision:   headRevision,
		ParentRevision: parentRevision,
		AheadCommits:   ahead,
		BehindCommits:  behind,
	}, nil
}

func worktreePathAvailable(worktreePath string) bool {
	worktreePath = strings.TrimSpace(worktreePath)
	if worktreePath == "" {
		return false
	}
	info, err := os.Stat(worktreePath)
	if err != nil {
		return false
	}
	return info.IsDir()
}

func gitCurrentBranch(worktreePath string) (string, error) {
	out, err := exec.Command("git", "-C", worktreePath, "rev-parse", "--abbrev-ref", "HEAD").CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("git rev-parse --abbrev-ref HEAD in %s: %w: %s", worktreePath, err, out)
	}
	return strings.TrimSpace(string(out)), nil
}

func gitRevision(worktreePath, rev string) (string, error) {
	out, err := exec.Command("git", "-C", worktreePath, "rev-parse", strings.TrimSpace(rev)).CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("git rev-parse %s in %s: %w: %s", rev, worktreePath, err, out)
	}
	return strings.TrimSpace(string(out)), nil
}

func gitAheadBehindCounts(worktreePath, parentRevision, headRevision string) (ahead, behind int, err error) {
	out, err := exec.Command("git", "-C", worktreePath, "rev-list", "--left-right", "--count", strings.TrimSpace(parentRevision)+"..."+strings.TrimSpace(headRevision)).CombinedOutput()
	if err != nil {
		return 0, 0, fmt.Errorf("git rev-list --left-right --count in %s: %w: %s", worktreePath, err, out)
	}
	fields := strings.Fields(strings.TrimSpace(string(out)))
	if len(fields) != 2 {
		return 0, 0, fmt.Errorf("unexpected git rev-list count output %q", strings.TrimSpace(string(out)))
	}
	if _, scanErr := fmt.Sscanf(fields[0], "%d", &behind); scanErr != nil {
		return 0, 0, fmt.Errorf("parse behind commits %q: %w", fields[0], scanErr)
	}
	if _, scanErr := fmt.Sscanf(fields[1], "%d", &ahead); scanErr != nil {
		return 0, 0, fmt.Errorf("parse ahead commits %q: %w", fields[1], scanErr)
	}
	return ahead, behind, nil
}

func loadSessionWorktreeLineage(runDir, sessionName string) (*WorktreeLineage, error) {
	snapshot, err := LoadWorktreeSnapshot(WorktreeSnapshotPath(runDir))
	if err != nil || snapshot == nil || snapshot.SessionLineage == nil {
		return nil, err
	}
	lineage, ok := snapshot.SessionLineage[sessionName]
	if !ok {
		return nil, nil
	}
	copy := lineage
	return &copy, nil
}

func loadRootWorktreeLineage(runDir string) (*WorktreeLineage, error) {
	snapshot, err := LoadWorktreeSnapshot(WorktreeSnapshotPath(runDir))
	if err != nil || snapshot == nil || snapshot.RootLineage == nil {
		return nil, err
	}
	copy := *snapshot.RootLineage
	return &copy, nil
}

func formatWorktreeLineageSummary(lineage *WorktreeLineage) string {
	if lineage == nil {
		return ""
	}
	parts := make([]string, 0, 5)
	if strings.TrimSpace(lineage.Branch) != "" {
		parts = append(parts, "branch="+lineage.Branch)
	}
	parentLabel := strings.TrimSpace(lineage.ParentSelector)
	if parentLabel == "" {
		parentLabel = strings.TrimSpace(lineage.ParentRef)
	}
	if parentLabel != "" {
		parts = append(parts, "parent="+parentLabel)
	}
	if lineage.AheadCommits > 0 {
		parts = append(parts, fmt.Sprintf("ahead=%d", lineage.AheadCommits))
	}
	if lineage.BehindCommits > 0 {
		parts = append(parts, fmt.Sprintf("behind=%d", lineage.BehindCommits))
	}
	return strings.Join(parts, " ")
}

func sessionWorktreeLineageSummary(runDir, sessionName string) string {
	lineage, err := loadSessionWorktreeLineage(runDir, sessionName)
	if err != nil {
		return ""
	}
	return formatWorktreeLineageSummary(lineage)
}

func sessionWorktreeSurfaceSummary(runDir, runName, sessionName string, state *SessionsRuntimeState) string {
	if lineage := sessionWorktreeLineageSummary(runDir, sessionName); lineage != "" {
		return lineage
	}
	worktreePath := resolvedSessionWorktreePath(runDir, runName, sessionName, state)
	if strings.TrimSpace(worktreePath) == "" || filepath.Clean(worktreePath) == filepath.Clean(RunWorktreePath(runDir)) {
		return "shared run-root worktree"
	}
	return "dedicated session worktree"
}

func rootWorktreeLineageSummary(runDir string) string {
	lineage, err := loadRootWorktreeLineage(runDir)
	if err != nil {
		return ""
	}
	return formatWorktreeLineageSummary(lineage)
}
