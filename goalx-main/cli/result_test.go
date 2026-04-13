package cli

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	goalx "github.com/vonbai/goalx"
	"gopkg.in/yaml.v3"
)

func TestResultPrintsLatestSavedSummary(t *testing.T) {
	projectRoot := t.TempDir()

	olderDir := writeSavedResultRun(t, projectRoot, "older-run", goalx.Config{
		Name: "older-run",
		Mode: goalx.ModeWorker,
		Target: goalx.TargetConfig{
			Files: []string{"report.md"},
		},
	}, map[string]string{
		"summary.md": "# older summary\n",
	})
	newerDir := writeSavedResultRun(t, projectRoot, "newer-run", goalx.Config{
		Name: "newer-run",
		Mode: goalx.ModeWorker,
		Target: goalx.TargetConfig{
			Files: []string{"report.md"},
		},
	}, map[string]string{
		"summary.md": "# newer summary\n",
	})

	oldTime := time.Now().Add(-time.Hour)
	newTime := time.Now()
	if err := os.Chtimes(olderDir, oldTime, oldTime); err != nil {
		t.Fatalf("chtimes older run: %v", err)
	}
	if err := os.Chtimes(newerDir, newTime, newTime); err != nil {
		t.Fatalf("chtimes newer run: %v", err)
	}

	err := Result(projectRoot, nil)
	if err == nil {
		t.Fatalf("Result should require an explicit run when multiple saved runs exist")
	}
	if !strings.Contains(err.Error(), "multiple saved runs") {
		t.Fatalf("Result error = %v, want multiple saved runs", err)
	}
}

func TestResultFailsWhenSummaryMissingEvenIfIntegrationExists(t *testing.T) {
	projectRoot := initGitRepo(t)
	writeAndCommit(t, projectRoot, "README.md", "base\n", "base commit")

	headBranch := currentBranchName(t, projectRoot)
	branch := "goalx/dev-run/1"
	runGit(t, projectRoot, "checkout", "-b", branch)
	writeAndCommit(t, projectRoot, "README.md", "base\nupdated\n", "feat: update readme")
	runGit(t, projectRoot, "checkout", headBranch)

	runDir := writeSavedResultRun(t, projectRoot, "dev-run", goalx.Config{
		Name: "dev-run",
		Mode: goalx.ModeWorker,
		Target: goalx.TargetConfig{
			Files: []string{"README.md"},
		},
	}, nil)

	if err := SaveIntegrationState(IntegrationStatePath(runDir), &IntegrationState{
		Version:                 1,
		CurrentExperimentID:     "exp-1",
		CurrentBranch:           branch,
		CurrentCommit:           strings.TrimSpace(gitOutput(t, projectRoot, "rev-parse", branch)),
		LastIntegrationID:       "int-1",
		LastMethod:              "keep",
		LastSourceExperimentIDs: []string{"exp-1"},
	}); err != nil {
		t.Fatalf("SaveIntegrationState: %v", err)
	}

	err := Result(projectRoot, []string{"dev-run"})
	if err == nil {
		t.Fatal("expected result to fail without summary.md even when integration exists")
	}
	if !strings.Contains(err.Error(), "summary.md") {
		t.Fatalf("Result error = %v, want summary.md failure", err)
	}
}

func TestResultPrefersSummarySurfaceWhenAvailable(t *testing.T) {
	projectRoot := initGitRepo(t)
	writeAndCommit(t, projectRoot, "README.md", "base\n", "base commit")

	headBranch := currentBranchName(t, projectRoot)
	branch := "goalx/dev-run/1"
	runGit(t, projectRoot, "checkout", "-b", branch)
	writeAndCommit(t, projectRoot, "README.md", "base\nupdated\n", "feat: update readme")
	runGit(t, projectRoot, "checkout", headBranch)

	runDir := writeSavedResultRun(t, projectRoot, "dev-run", goalx.Config{
		Name: "dev-run",
		Mode: goalx.ModeWorker,
		Target: goalx.TargetConfig{
			Files: []string{"README.md"},
		},
	}, map[string]string{
		"summary.md": "# Final Result\n\nship it\n",
	})

	if err := SaveIntegrationState(IntegrationStatePath(runDir), &IntegrationState{
		Version:                 1,
		CurrentExperimentID:     "exp-1",
		CurrentBranch:           branch,
		CurrentCommit:           strings.TrimSpace(gitOutput(t, projectRoot, "rev-parse", branch)),
		LastIntegrationID:       "int-1",
		LastMethod:              "keep",
		LastSourceExperimentIDs: []string{"exp-1"},
	}); err != nil {
		t.Fatalf("SaveIntegrationState: %v", err)
	}

	out := captureStdout(t, func() {
		if err := Result(projectRoot, []string{"dev-run"}); err != nil {
			t.Fatalf("Result: %v", err)
		}
	})

	if !strings.Contains(out, "ship it") {
		t.Fatalf("result output missing final summary:\n%s", out)
	}
	if strings.Contains(out, "feat: update readme") {
		t.Fatalf("result output should prefer summary surface over branch summary:\n%s", out)
	}
}

func TestResultFailsWhenSummaryMissing(t *testing.T) {
	projectRoot := t.TempDir()

	writeSavedResultRun(t, projectRoot, "dev-run", goalx.Config{
		Name: "dev-run",
		Mode: goalx.ModeWorker,
		Target: goalx.TargetConfig{
			Files: []string{"README.md"},
		},
	}, nil)

	err := Result(projectRoot, []string{"dev-run"})
	if err == nil {
		t.Fatal("expected result to fail without summary.md")
	}
	if !strings.Contains(err.Error(), "summary.md") {
		t.Fatalf("Result error = %v, want summary.md failure", err)
	}
}

func TestResultPrintsSmartResearchSummaryByDefault(t *testing.T) {
	projectRoot := t.TempDir()

	writeSavedResultRun(t, projectRoot, "smart-run", goalx.Config{
		Name: "smart-run",
		Mode: goalx.ModeWorker,
		Target: goalx.TargetConfig{
			Files: []string{"report.md"},
		},
	}, map[string]string{
		"summary.md": strings.TrimSpace(`
# Summary

## Key Findings
- finding 1
- finding 2
- finding 3
- finding 4
- finding 5
- finding 6

## Priority Fix List
- P0: config.go
- P1: cli/result.go

## Recommendation
implement

## Appendix
hidden details
`) + "\n",
	})

	out := captureStdout(t, func() {
		if err := Result(projectRoot, []string{"smart-run"}); err != nil {
			t.Fatalf("Result: %v", err)
		}
	})

	for _, want := range []string{
		"=== Result ===",
		"Recommendation: implement",
		"- finding 1",
		"... (1 more lines)",
		"- P0: config.go",
		"Full report: goalx result --full",
	} {
		if !strings.Contains(out, want) {
			t.Fatalf("result output missing %q:\n%s", want, out)
		}
	}
	if strings.Contains(out, "hidden details") {
		t.Fatalf("smart result output should omit appendix details:\n%s", out)
	}
}

func TestResultPrintsFullResearchSummaryWithFullFlag(t *testing.T) {
	projectRoot := t.TempDir()

	summary := strings.TrimSpace(`
# Summary

## Key Findings
- finding 1

## Recommendation
done

## Appendix
hidden details
`) + "\n"
	writeSavedResultRun(t, projectRoot, "smart-run", goalx.Config{
		Name: "smart-run",
		Mode: goalx.ModeWorker,
		Target: goalx.TargetConfig{
			Files: []string{"report.md"},
		},
	}, map[string]string{
		"summary.md": summary,
	})

	out := captureStdout(t, func() {
		if err := Result(projectRoot, []string{"smart-run", "--full"}); err != nil {
			t.Fatalf("Result: %v", err)
		}
	})

	if out != summary {
		t.Fatalf("full result output mismatch:\nwant:\n%s\ngot:\n%s", summary, out)
	}
}

func TestResultFailsWhenOnlySavedManifestReportExists(t *testing.T) {
	projectRoot := t.TempDir()

	runDir := writeSavedResultRun(t, projectRoot, "report-only-run", goalx.Config{
		Name: "report-only-run",
		Mode: goalx.ModeWorker,
		Target: goalx.TargetConfig{
			Files: []string{"report.md"},
		},
	}, nil)
	reportPath := filepath.Join(runDir, "custom-findings.txt")
	if err := os.WriteFile(reportPath, []byte("# report only\n\nuse this\n"), 0o644); err != nil {
		t.Fatalf("write custom report: %v", err)
	}
	if err := SaveArtifacts(filepath.Join(runDir, "artifacts.json"), &ArtifactsManifest{
		Run:     "report-only-run",
		Version: 1,
		Sessions: []SessionArtifacts{
			{
				Name: "session-1",
				Mode: string(goalx.ModeWorker),
				Artifacts: []ArtifactMeta{
					{Kind: "report", Path: reportPath, RelPath: "custom-findings.txt", DurableName: "session-1-report.md"},
				},
			},
		},
	}); err != nil {
		t.Fatalf("SaveArtifacts: %v", err)
	}

	err := Result(projectRoot, []string{"report-only-run"})
	if err == nil {
		t.Fatal("expected result to fail without summary.md")
	}
	if !strings.Contains(err.Error(), "summary.md") {
		t.Fatalf("Result error = %v, want summary.md failure", err)
	}
}

func TestResultFailsWhenActiveRunOnlyHasReport(t *testing.T) {
	projectRoot := t.TempDir()
	cfg := &goalx.Config{
		Name:      "active-run",
		Mode:      goalx.ModeWorker,
		Objective: "inspect repo",
		Target:    goalx.TargetConfig{Files: []string{"report.md"}},
	}
	runDir := writeRunSpecFixture(t, projectRoot, cfg)
	reportPath := filepath.Join(ReportsDir(runDir), "repo-summary.md")
	if err := os.MkdirAll(filepath.Dir(reportPath), 0o755); err != nil {
		t.Fatalf("mkdir reports dir: %v", err)
	}
	if err := os.WriteFile(reportPath, []byte("# active report\n\nlive data\n"), 0o644); err != nil {
		t.Fatalf("write active report: %v", err)
	}

	err := Result(projectRoot, []string{"active-run"})
	if err == nil {
		t.Fatal("expected result to fail without summary.md")
	}
	if !strings.Contains(err.Error(), "summary.md") {
		t.Fatalf("Result error = %v, want summary.md failure", err)
	}
}

func TestResultFailsWhenActiveRunOnlyHasCurrentReport(t *testing.T) {
	projectRoot := t.TempDir()
	cfg := &goalx.Config{
		Name:      "active-run",
		Mode:      goalx.ModeWorker,
		Objective: "inspect repo",
		Target:    goalx.TargetConfig{Files: []string{"report.md"}},
	}
	runDir := writeRunSpecFixture(t, projectRoot, cfg)
	reportPath := filepath.Join(ReportsDir(runDir), "repo-summary.md")
	if err := os.MkdirAll(filepath.Dir(reportPath), 0o755); err != nil {
		t.Fatalf("mkdir reports dir: %v", err)
	}
	if err := os.WriteFile(reportPath, []byte("# current report\n\nlive data\n"), 0o644); err != nil {
		t.Fatalf("write current report: %v", err)
	}

	err := Result(projectRoot, []string{"active-run"})
	if err == nil {
		t.Fatal("expected result to fail without summary.md")
	}
	if !strings.Contains(err.Error(), "summary.md") {
		t.Fatalf("Result error = %v, want summary.md failure", err)
	}
}

func TestResultReadsLegacyProjectScopedSavedRun(t *testing.T) {
	projectRoot := t.TempDir()
	runDir := LegacySavedRunDir(projectRoot, "legacy-run")
	if err := os.MkdirAll(runDir, 0o755); err != nil {
		t.Fatalf("mkdir legacy run dir: %v", err)
	}
	cfg := goalx.Config{
		Name:   "legacy-run",
		Mode:   goalx.ModeWorker,
		Target: goalx.TargetConfig{Files: []string{"report.md"}},
	}
	data, err := yaml.Marshal(&cfg)
	if err != nil {
		t.Fatalf("marshal config: %v", err)
	}
	if err := os.WriteFile(RunSpecPath(runDir), data, 0o644); err != nil {
		t.Fatalf("write run spec: %v", err)
	}
	if err := os.WriteFile(filepath.Join(runDir, "summary.md"), []byte("# legacy summary\n"), 0o644); err != nil {
		t.Fatalf("write summary: %v", err)
	}

	out := captureStdout(t, func() {
		if err := Result(projectRoot, []string{"legacy-run"}); err != nil {
			t.Fatalf("Result: %v", err)
		}
	})
	if !strings.Contains(out, "legacy summary") {
		t.Fatalf("result output missing legacy summary:\n%s", out)
	}
}

func TestResultHelpPrintsUsage(t *testing.T) {
	out := captureStdout(t, func() {
		if err := Result(t.TempDir(), []string{"--help"}); err != nil {
			t.Fatalf("Result --help: %v", err)
		}
	})
	if !strings.Contains(out, "usage: goalx result [NAME] [--full]") {
		t.Fatalf("Result --help output = %q", out)
	}
}

func writeSavedResultRun(t *testing.T, projectRoot, runName string, cfg goalx.Config, files map[string]string) string {
	t.Helper()

	runDir := SavedRunDir(projectRoot, runName)
	if err := os.MkdirAll(runDir, 0o755); err != nil {
		t.Fatalf("mkdir run dir: %v", err)
	}

	data, err := yaml.Marshal(&cfg)
	if err != nil {
		t.Fatalf("marshal config: %v", err)
	}
	if err := os.WriteFile(RunSpecPath(runDir), data, 0o644); err != nil {
		t.Fatalf("write run-spec.yaml: %v", err)
	}

	for name, content := range files {
		if err := os.WriteFile(filepath.Join(runDir, name), []byte(content), 0o644); err != nil {
			t.Fatalf("write %s: %v", name, err)
		}
	}

	return runDir
}

func currentBranchName(t *testing.T, repo string) string {
	t.Helper()

	cmd := exec.Command("git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git current branch: %v\n%s", err, string(out))
	}
	return strings.TrimSpace(string(out))
}
