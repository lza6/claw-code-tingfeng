package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	goalx "github.com/vonbai/goalx"
)

type CoordinationState struct {
	Version       int                                 `json:"version"`
	PlanSummary   []string                            `json:"plan_summary,omitempty"`
	Required      map[string]CoordinationRequiredItem `json:"required,omitempty"`
	Sessions      map[string]CoordinationSession      `json:"sessions,omitempty"`
	Decision      *CoordinationDecision               `json:"decision,omitempty"`
	OpenQuestions []string                            `json:"open_questions,omitempty"`
	UpdatedAt     string                              `json:"updated_at,omitempty"`
}

type CoordinationRequiredItem struct {
	ExecutionState string                       `json:"execution_state,omitempty"`
	BlockedBy      string                       `json:"blocked_by,omitempty"`
	Surfaces       CoordinationRequiredSurfaces `json:"surfaces"`
	UpdatedAt      string                       `json:"updated_at,omitempty"`
}

type legacyCoordinationState struct {
	Version       int                                       `json:"version"`
	PlanSummary   []string                                  `json:"plan_summary,omitempty"`
	Required      map[string]legacyCoordinationRequiredItem `json:"required,omitempty"`
	Sessions      map[string]CoordinationSession            `json:"sessions,omitempty"`
	Decision      *CoordinationDecision                     `json:"decision,omitempty"`
	OpenQuestions []string                                  `json:"open_questions,omitempty"`
	UpdatedAt     string                                    `json:"updated_at,omitempty"`
}

type legacyCoordinationRequiredItem struct {
	Owner          string                       `json:"owner,omitempty"`
	ExecutionState string                       `json:"execution_state,omitempty"`
	BlockedBy      string                       `json:"blocked_by,omitempty"`
	Surfaces       CoordinationRequiredSurfaces `json:"surfaces"`
	UpdatedAt      string                       `json:"updated_at,omitempty"`
}

type CoordinationRequiredSurfaces struct {
	Repo           string `json:"repo,omitempty"`
	Runtime        string `json:"runtime,omitempty"`
	RunArtifacts   string `json:"run_artifacts,omitempty"`
	WebResearch    string `json:"web_research,omitempty"`
	ExternalSystem string `json:"external_system,omitempty"`
}

type CoordinationSession struct {
	State              string                    `json:"state,omitempty"`
	Scope              string                    `json:"scope,omitempty"`
	CoversRequired     []string                  `json:"covers_required,omitempty"`
	DispatchableSlices []goalx.DispatchableSlice `json:"dispatchable_slices,omitempty"`
	LastRound          int                       `json:"last_round,omitempty"`
	UpdatedAt          string                    `json:"updated_at,omitempty"`
}

type CoordinationDecision struct {
	RootCause        string `json:"root_cause,omitempty"`
	LocalPath        string `json:"local_path,omitempty"`
	CompatiblePath   string `json:"compatible_path,omitempty"`
	ArchitecturePath string `json:"architecture_path,omitempty"`
	ChosenPath       string `json:"chosen_path,omitempty"`
	ChosenPathReason string `json:"chosen_path_reason,omitempty"`
}

const (
	coordinationRequiredExecutionStateActive  = "active"
	coordinationRequiredExecutionStateProbing = "probing"
	coordinationRequiredExecutionStateWaiting = "waiting"
	coordinationRequiredExecutionStateBlocked = "blocked"

	coordinationRequiredSurfacePending       = "pending"
	coordinationRequiredSurfaceActive        = "active"
	coordinationRequiredSurfaceAvailable     = "available"
	coordinationRequiredSurfaceExhausted     = "exhausted"
	coordinationRequiredSurfaceUnreachable   = "unreachable"
	coordinationRequiredSurfaceNotApplicable = "not_applicable"
)

func CoordinationPath(runDir string) string {
	return filepath.Join(runDir, "coordination.json")
}

func LoadCoordinationState(path string) (*CoordinationState, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	state, err := parseCoordinationState(data)
	if err != nil {
		return nil, fmt.Errorf("parse %s: %w", path, err)
	}
	return state, nil
}

func SaveCoordinationState(path string, state *CoordinationState) error {
	if err := validateCoordinationState(state); err != nil {
		return err
	}
	if state.UpdatedAt == "" {
		state.UpdatedAt = time.Now().UTC().Format(time.RFC3339)
	}
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}
	return writeFileAtomic(path, data, 0o644)
}

func EnsureCoordinationState(runDir, objective string) (*CoordinationState, error) {
	path := CoordinationPath(runDir)
	state, err := LoadCoordinationState(path)
	if err != nil {
		return nil, err
	}
	if state == nil {
		state = &CoordinationState{
			Version:   1,
			Required:  map[string]CoordinationRequiredItem{},
			Sessions:  map[string]CoordinationSession{},
			UpdatedAt: time.Now().UTC().Format(time.RFC3339),
		}
		if err := SaveCoordinationState(path, state); err != nil {
			return nil, err
		}
		return state, nil
	}
	return state, nil
}

func parseCoordinationState(data []byte) (*CoordinationState, error) {
	var legacy legacyCoordinationState
	if err := decodeStrictJSON(data, &legacy); err != nil {
		return nil, durableSchemaHintError(DurableSurfaceCoordination, err)
	}
	state := CoordinationState{
		Version:       legacy.Version,
		PlanSummary:   legacy.PlanSummary,
		Required:      map[string]CoordinationRequiredItem{},
		Sessions:      legacy.Sessions,
		Decision:      legacy.Decision,
		OpenQuestions: legacy.OpenQuestions,
		UpdatedAt:     legacy.UpdatedAt,
	}
	for reqID, item := range legacy.Required {
		state.Required[reqID] = CoordinationRequiredItem{
			ExecutionState: item.ExecutionState,
			BlockedBy:      item.BlockedBy,
			Surfaces:       item.Surfaces,
			UpdatedAt:      item.UpdatedAt,
		}
	}
	if err := validateCoordinationState(&state); err != nil {
		return nil, durableSchemaHintError(DurableSurfaceCoordination, err)
	}
	return &state, nil
}

// normalizeCoordinationState ensures structural consistency without
// truncating or modifying master-written content.
func normalizeCoordinationState(state *CoordinationState) {
	if state == nil {
		return
	}
	if state.Required == nil {
		state.Required = map[string]CoordinationRequiredItem{}
	}
	if state.Sessions == nil {
		state.Sessions = map[string]CoordinationSession{}
	}
	for name, session := range state.Sessions {
		session.State = strings.TrimSpace(session.State)
		session.Scope = strings.TrimSpace(session.Scope)
		session.CoversRequired = compactStrings(session.CoversRequired)
		for i := range session.DispatchableSlices {
			session.DispatchableSlices[i].Title = strings.TrimSpace(session.DispatchableSlices[i].Title)
			session.DispatchableSlices[i].Why = strings.TrimSpace(session.DispatchableSlices[i].Why)
			session.DispatchableSlices[i].Mode = strings.TrimSpace(session.DispatchableSlices[i].Mode)
			session.DispatchableSlices[i].SuggestedOwner = strings.TrimSpace(session.DispatchableSlices[i].SuggestedOwner)
			session.DispatchableSlices[i].SuggestedAction = strings.TrimSpace(session.DispatchableSlices[i].SuggestedAction)
			session.DispatchableSlices[i].CoversRequired = compactStrings(session.DispatchableSlices[i].CoversRequired)
			session.DispatchableSlices[i].Evidence = compactStrings(session.DispatchableSlices[i].Evidence)
		}
		state.Sessions[name] = session
	}
}

func validateCoordinationState(state *CoordinationState) error {
	if state == nil {
		return fmt.Errorf("coordination state is nil")
	}
	if state.Version <= 0 {
		return fmt.Errorf("coordination state version must be positive")
	}
	normalizeCoordinationState(state)
	for reqID, item := range state.Required {
		if err := validateCoordinationRequiredItem(reqID, item); err != nil {
			return err
		}
	}
	for sessionName, session := range state.Sessions {
		if strings.TrimSpace(sessionName) == "" {
			return fmt.Errorf("coordination session key must be non-empty")
		}
		for _, requiredID := range session.CoversRequired {
			if _, ok := state.Required[requiredID]; !ok {
				return fmt.Errorf("coordination session %q covers unknown required id %q", sessionName, requiredID)
			}
		}
		for _, slice := range session.DispatchableSlices {
			for _, requiredID := range compactStrings(slice.CoversRequired) {
				if _, ok := state.Required[requiredID]; !ok {
					return fmt.Errorf("coordination session %q dispatchable slice %q covers unknown required id %q", sessionName, slice.Title, requiredID)
				}
			}
		}
	}
	return nil
}

func validateCoordinationRequiredItem(reqID string, item CoordinationRequiredItem) error {
	if strings.TrimSpace(reqID) == "" {
		return fmt.Errorf("coordination required item id must be non-empty")
	}
	switch item.ExecutionState {
	case coordinationRequiredExecutionStateActive, coordinationRequiredExecutionStateProbing, coordinationRequiredExecutionStateWaiting, coordinationRequiredExecutionStateBlocked:
	default:
		return fmt.Errorf("coordination required item %q has invalid execution_state %q", reqID, item.ExecutionState)
	}
	if strings.TrimSpace(item.BlockedBy) != "" && item.ExecutionState != coordinationRequiredExecutionStateWaiting && item.ExecutionState != coordinationRequiredExecutionStateBlocked {
		return fmt.Errorf("coordination required item %q blocked_by requires waiting or blocked execution_state", reqID)
	}
	if err := validateCoordinationRequiredSurface("repo", reqID, item.Surfaces.Repo); err != nil {
		return err
	}
	if err := validateCoordinationRequiredSurface("runtime", reqID, item.Surfaces.Runtime); err != nil {
		return err
	}
	if err := validateCoordinationRequiredSurface("run_artifacts", reqID, item.Surfaces.RunArtifacts); err != nil {
		return err
	}
	if err := validateCoordinationRequiredSurface("web_research", reqID, item.Surfaces.WebResearch); err != nil {
		return err
	}
	if err := validateCoordinationRequiredSurface("external_system", reqID, item.Surfaces.ExternalSystem); err != nil {
		return err
	}
	return nil
}

func validateCoordinationRequiredSurface(name, reqID, value string) error {
	switch value {
	case coordinationRequiredSurfacePending,
		coordinationRequiredSurfaceActive,
		coordinationRequiredSurfaceAvailable,
		coordinationRequiredSurfaceExhausted,
		coordinationRequiredSurfaceUnreachable,
		coordinationRequiredSurfaceNotApplicable:
		return nil
	default:
		return fmt.Errorf("coordination required item %q has invalid %s surface state %q", reqID, name, value)
	}
}

func coordinationRequiredSurfacesExhausted(surfaces CoordinationRequiredSurfaces) bool {
	values := []string{
		surfaces.Repo,
		surfaces.Runtime,
		surfaces.RunArtifacts,
		surfaces.WebResearch,
		surfaces.ExternalSystem,
	}
	for _, value := range values {
		switch value {
		case coordinationRequiredSurfaceExhausted, coordinationRequiredSurfaceUnreachable, coordinationRequiredSurfaceNotApplicable:
		default:
			return false
		}
	}
	return true
}
