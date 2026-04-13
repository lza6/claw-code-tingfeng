package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type ReportEvidenceManifest struct {
	Version           int      `json:"version"`
	ReportPath        string   `json:"report_path"`
	Covers            []string `json:"covers"`
	RepoEvidencePaths []string `json:"repo_evidence_paths,omitempty"`
	ExternalRefs      []string `json:"external_refs,omitempty"`
}

func ReportEvidenceManifestPath(reportPath string) string {
	reportPath = strings.TrimSpace(reportPath)
	if reportPath == "" {
		return ""
	}
	ext := filepath.Ext(reportPath)
	if ext == "" {
		return reportPath + ".evidence.json"
	}
	return strings.TrimSuffix(reportPath, ext) + ".evidence.json"
}

func LoadReportEvidenceManifest(reportPath string) (*ReportEvidenceManifest, error) {
	manifestPath := ReportEvidenceManifestPath(reportPath)
	data, err := os.ReadFile(manifestPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("read report evidence manifest %s: %w", manifestPath, err)
	}
	manifest, err := parseReportEvidenceManifest(data, reportPath)
	if err != nil {
		return nil, fmt.Errorf("parse report evidence manifest %s: %w", manifestPath, err)
	}
	return manifest, nil
}

func SaveReportEvidenceManifest(reportPath string, manifest *ReportEvidenceManifest) error {
	if manifest == nil {
		return fmt.Errorf("report evidence manifest is nil")
	}
	normalized := *manifest
	normalized.ReportPath = strings.TrimSpace(reportPath)
	if err := validateReportEvidenceManifest(reportPath, &normalized); err != nil {
		return err
	}
	data, err := json.MarshalIndent(&normalized, "", "  ")
	if err != nil {
		return err
	}
	return writeFileAtomic(ReportEvidenceManifestPath(reportPath), data, 0o644)
}

func parseReportEvidenceManifest(data []byte, reportPath string) (*ReportEvidenceManifest, error) {
	var manifest ReportEvidenceManifest
	if err := decodeStrictJSON(data, &manifest); err != nil {
		return nil, err
	}
	if err := validateReportEvidenceManifest(reportPath, &manifest); err != nil {
		return nil, err
	}
	return &manifest, nil
}

func validateReportEvidenceManifest(reportPath string, manifest *ReportEvidenceManifest) error {
	if manifest == nil {
		return fmt.Errorf("report evidence manifest is nil")
	}
	if manifest.Version <= 0 {
		return fmt.Errorf("report evidence manifest version must be positive")
	}
	reportPath = strings.TrimSpace(reportPath)
	if reportPath == "" {
		return fmt.Errorf("report evidence manifest report path is required")
	}
	manifest.ReportPath = strings.TrimSpace(manifest.ReportPath)
	if manifest.ReportPath == "" {
		return fmt.Errorf("report evidence manifest report_path is required")
	}
	if filepath.Clean(manifest.ReportPath) != filepath.Clean(reportPath) {
		return fmt.Errorf("report evidence manifest report_path %q does not match report %q", manifest.ReportPath, reportPath)
	}
	if !fileExists(reportPath) {
		return fmt.Errorf("report evidence manifest report %q does not exist", reportPath)
	}
	covers := trimmedGoalCovers(manifest.Covers)
	if len(covers) == 0 {
		return fmt.Errorf("report evidence manifest covers is required")
	}
	if len(covers) != len(manifest.Covers) {
		return fmt.Errorf("report evidence manifest covers entries must be non-empty")
	}
	manifest.Covers = covers
	repoEvidencePaths := trimmedStrings(manifest.RepoEvidencePaths)
	if len(repoEvidencePaths) != len(manifest.RepoEvidencePaths) {
		return fmt.Errorf("report evidence manifest repo_evidence_paths entries must be non-empty")
	}
	manifest.RepoEvidencePaths = repoEvidencePaths
	for _, evidencePath := range manifest.RepoEvidencePaths {
		if !fileExists(evidencePath) {
			return fmt.Errorf("report evidence manifest repo evidence path %q does not exist", evidencePath)
		}
	}
	externalRefs := trimmedStrings(manifest.ExternalRefs)
	if len(externalRefs) != len(manifest.ExternalRefs) {
		return fmt.Errorf("report evidence manifest external_refs entries must be non-empty")
	}
	manifest.ExternalRefs = externalRefs
	for _, ref := range manifest.ExternalRefs {
		if ref == "" {
			return fmt.Errorf("report evidence manifest external_refs entries must be non-empty")
		}
	}
	return nil
}

func copyReportWithEvidence(srcReportPath, dstReportPath string) error {
	if err := copyFileIfExists(srcReportPath, dstReportPath); err != nil {
		return err
	}
	manifest, err := LoadReportEvidenceManifest(srcReportPath)
	if err != nil {
		return err
	}
	if manifest == nil {
		return nil
	}
	return SaveReportEvidenceManifest(dstReportPath, manifest)
}

func trimmedStrings(values []string) []string {
	if len(values) == 0 {
		return nil
	}
	out := make([]string, 0, len(values))
	for _, value := range values {
		if trimmed := strings.TrimSpace(value); trimmed != "" {
			out = append(out, trimmed)
		}
	}
	return out
}
