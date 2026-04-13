package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestReportEvidenceManifestPath(t *testing.T) {
	got := ReportEvidenceManifestPath(filepath.Join("/tmp", "run", "reports", "architecture-options-comparison.md"))
	want := filepath.Join("/tmp", "run", "reports", "architecture-options-comparison.evidence.json")
	if got != want {
		t.Fatalf("ReportEvidenceManifestPath() = %q, want %q", got, want)
	}
}

func TestLoadReportEvidenceManifestRejectsUnknownField(t *testing.T) {
	dir := t.TempDir()
	reportPath := filepath.Join(dir, "research-report.md")
	if err := os.WriteFile(reportPath, []byte("report body\n"), 0o644); err != nil {
		t.Fatalf("write report: %v", err)
	}
	if err := os.WriteFile(ReportEvidenceManifestPath(reportPath), []byte(`{
  "version": 1,
  "report_path": "`+reportPath+`",
  "covers": ["ucl-1"],
  "repo_evidence_paths": [],
  "external_refs": [],
  "unexpected": true
}`), 0o644); err != nil {
		t.Fatalf("write manifest: %v", err)
	}

	_, err := LoadReportEvidenceManifest(reportPath)
	if err == nil {
		t.Fatal("LoadReportEvidenceManifest should reject unknown fields")
	}
	if !strings.Contains(err.Error(), "unexpected") && !strings.Contains(err.Error(), "unknown field") {
		t.Fatalf("LoadReportEvidenceManifest error = %v, want unknown-field failure", err)
	}
}

func TestLoadReportEvidenceManifestRejectsReportPathMismatch(t *testing.T) {
	dir := t.TempDir()
	reportPath := filepath.Join(dir, "research-report.md")
	if err := os.WriteFile(reportPath, []byte("report body\n"), 0o644); err != nil {
		t.Fatalf("write report: %v", err)
	}
	mismatchPath := filepath.Join(dir, "other-report.md")
	if err := os.WriteFile(ReportEvidenceManifestPath(reportPath), []byte(fmt.Sprintf(`{
  "version": 1,
  "report_path": %q,
  "covers": ["ucl-1"],
  "repo_evidence_paths": [],
  "external_refs": []
}`, mismatchPath)), 0o644); err != nil {
		t.Fatalf("write manifest: %v", err)
	}

	_, err := LoadReportEvidenceManifest(reportPath)
	if err == nil {
		t.Fatal("LoadReportEvidenceManifest should reject report_path mismatch")
	}
	if !strings.Contains(err.Error(), "report_path") {
		t.Fatalf("LoadReportEvidenceManifest error = %v, want report_path failure", err)
	}
}

func TestLoadReportEvidenceManifestRejectsEmptyCovers(t *testing.T) {
	dir := t.TempDir()
	reportPath := filepath.Join(dir, "research-report.md")
	if err := os.WriteFile(reportPath, []byte("report body\n"), 0o644); err != nil {
		t.Fatalf("write report: %v", err)
	}
	if err := os.WriteFile(ReportEvidenceManifestPath(reportPath), []byte(fmt.Sprintf(`{
  "version": 1,
  "report_path": %q,
  "covers": [],
  "repo_evidence_paths": [],
  "external_refs": []
}`, reportPath)), 0o644); err != nil {
		t.Fatalf("write manifest: %v", err)
	}

	_, err := LoadReportEvidenceManifest(reportPath)
	if err == nil {
		t.Fatal("LoadReportEvidenceManifest should reject empty covers")
	}
	if !strings.Contains(err.Error(), "covers") {
		t.Fatalf("LoadReportEvidenceManifest error = %v, want covers failure", err)
	}
}

func TestLoadReportEvidenceManifestRejectsMissingRepoEvidencePath(t *testing.T) {
	dir := t.TempDir()
	reportPath := filepath.Join(dir, "research-report.md")
	if err := os.WriteFile(reportPath, []byte("report body\n"), 0o644); err != nil {
		t.Fatalf("write report: %v", err)
	}
	missingPath := filepath.Join(dir, "missing.txt")
	if err := os.WriteFile(ReportEvidenceManifestPath(reportPath), []byte(fmt.Sprintf(`{
  "version": 1,
  "report_path": %q,
  "covers": ["ucl-1"],
  "repo_evidence_paths": [%q],
  "external_refs": []
}`, reportPath, missingPath)), 0o644); err != nil {
		t.Fatalf("write manifest: %v", err)
	}

	_, err := LoadReportEvidenceManifest(reportPath)
	if err == nil {
		t.Fatal("LoadReportEvidenceManifest should reject missing repo evidence paths")
	}
	if !strings.Contains(err.Error(), "repo evidence") && !strings.Contains(err.Error(), "does not exist") {
		t.Fatalf("LoadReportEvidenceManifest error = %v, want repo evidence path failure", err)
	}
}

func TestLoadReportEvidenceManifestAcceptsValidStructure(t *testing.T) {
	tempDir := t.TempDir()
	reportPath := filepath.Join(tempDir, "research-report.md")
	evidencePath := filepath.Join(tempDir, "source.txt")
	if err := os.WriteFile(reportPath, []byte("research report\n"), 0o644); err != nil {
		t.Fatalf("write report: %v", err)
	}
	if err := os.WriteFile(evidencePath, []byte("source evidence\n"), 0o644); err != nil {
		t.Fatalf("write evidence: %v", err)
	}
	manifestPath := ReportEvidenceManifestPath(reportPath)
	if err := os.WriteFile(manifestPath, []byte(fmt.Sprintf(`{
  "version": 1,
  "report_path": %q,
  "covers": ["ucl-1"],
  "repo_evidence_paths": [%q],
  "external_refs": ["https://example.com"]
}`, reportPath, evidencePath)), 0o644); err != nil {
		t.Fatalf("write manifest: %v", err)
	}

	manifest, err := LoadReportEvidenceManifest(reportPath)
	if err != nil {
		t.Fatalf("LoadReportEvidenceManifest: %v", err)
	}
	if manifest.ReportPath != reportPath {
		t.Fatalf("ReportPath = %q, want %q", manifest.ReportPath, reportPath)
	}
	if len(manifest.Covers) != 1 || manifest.Covers[0] != "ucl-1" {
		t.Fatalf("Covers = %#v, want [ucl-1]", manifest.Covers)
	}
}
