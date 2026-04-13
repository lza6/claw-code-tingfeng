package cli

import "path/filepath"

// CompletionStatePath points to the agent-owned proof/closeout surface.
// GoalX exposes the durable path but does not impose proof semantics on it.
func CompletionStatePath(runDir string) string {
	return filepath.Join(runDir, "proof", "completion.json")
}
