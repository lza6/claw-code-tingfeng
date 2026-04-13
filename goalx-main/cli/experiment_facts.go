package cli

import (
	"fmt"
	"strings"
)

type ExperimentSurfaceFacts struct {
	CurrentExperimentID     string
	CurrentBranch           string
	CurrentCommit           string
	LastIntegrationID       string
	LastMethod              string
	LastSourceExperimentIDs []string
	UpdatedAt               string
	Entries                 int
	LastRecordAt            string
}

func loadExperimentSurfaceFacts(runDir string) (ExperimentSurfaceFacts, error) {
	facts := ExperimentSurfaceFacts{}
	state, err := LoadIntegrationState(IntegrationStatePath(runDir))
	if err != nil {
		return facts, err
	}
	if state != nil {
		facts.CurrentExperimentID = state.CurrentExperimentID
		facts.CurrentBranch = state.CurrentBranch
		facts.CurrentCommit = state.CurrentCommit
		facts.LastIntegrationID = state.LastIntegrationID
		facts.LastMethod = state.LastMethod
		facts.LastSourceExperimentIDs = append([]string(nil), state.LastSourceExperimentIDs...)
		facts.UpdatedAt = state.UpdatedAt
	}
	entries, lastRecordAt, err := experimentsLogFacts(ExperimentsLogPath(runDir))
	if err != nil {
		return facts, err
	}
	facts.Entries = entries
	facts.LastRecordAt = lastRecordAt
	return facts, nil
}

func (facts ExperimentSurfaceFacts) present() bool {
	return strings.TrimSpace(facts.CurrentExperimentID) != "" ||
		strings.TrimSpace(facts.CurrentBranch) != "" ||
		strings.TrimSpace(facts.LastMethod) != "" ||
		facts.Entries > 0 ||
		strings.TrimSpace(facts.LastRecordAt) != ""
}

func formatExperimentSurfaceSummary(runDir string) string {
	facts, err := loadExperimentSurfaceFacts(runDir)
	if err != nil || !facts.present() {
		return ""
	}
	parts := make([]string, 0, 5)
	if facts.CurrentExperimentID != "" {
		parts = append(parts, "current="+facts.CurrentExperimentID)
	}
	if facts.Entries > 0 {
		parts = append(parts, fmt.Sprintf("entries=%d", facts.Entries))
	}
	if facts.LastRecordAt != "" {
		parts = append(parts, "last_record_at="+facts.LastRecordAt)
	}
	if facts.LastMethod != "" {
		parts = append(parts, "last_method="+facts.LastMethod)
	}
	if len(facts.LastSourceExperimentIDs) > 0 {
		parts = append(parts, "sources="+strings.Join(facts.LastSourceExperimentIDs, ","))
	}
	return strings.Join(parts, " ")
}

func experimentAffordanceFacts(runDir string) ([]string, error) {
	facts, err := loadExperimentSurfaceFacts(runDir)
	if err != nil || !facts.present() {
		return nil, err
	}
	lines := make([]string, 0, 6)
	if facts.CurrentExperimentID != "" {
		lines = append(lines, fmt.Sprintf("Current integrated experiment: `%s`.", facts.CurrentExperimentID))
	}
	if facts.CurrentBranch != "" {
		lines = append(lines, fmt.Sprintf("Current integrated branch: `%s`.", facts.CurrentBranch))
	}
	if facts.Entries > 0 {
		lines = append(lines, fmt.Sprintf("Experiment entries: `%d`.", facts.Entries))
	}
	if facts.LastRecordAt != "" {
		lines = append(lines, fmt.Sprintf("Last experiment record: `%s`.", facts.LastRecordAt))
	}
	if facts.LastMethod != "" {
		lines = append(lines, fmt.Sprintf("Last integration method: `%s`.", facts.LastMethod))
	}
	if len(facts.LastSourceExperimentIDs) > 0 {
		lines = append(lines, fmt.Sprintf("Last integration sources: `%s`.", strings.Join(facts.LastSourceExperimentIDs, ",")))
	}
	return lines, nil
}
