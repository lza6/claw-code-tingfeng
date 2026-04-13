package cli

import (
	"os"
	"reflect"
	"testing"

	goalx "github.com/vonbai/goalx"
)

func TestBuildControlGapFactsDetectsStatusDriftAndSerializedFrontier(t *testing.T) {
	_, runDir, _, _ := writeGuidanceRunFixture(t)
	if err := writeBoundaryFixture(t, runDir, &GoalState{
		Required: []GoalItem{
			{ID: "req-1", Text: "ship cockpit", Source: goalItemSourceUser, Role: goalItemRoleOutcome, State: goalItemStateOpen},
			{ID: "req-2", Text: "ship research spine", Source: goalItemSourceUser, Role: goalItemRoleOutcome, State: goalItemStateOpen},
		},
	}); err != nil {
		t.Fatalf("SaveGoalState: %v", err)
	}
	if err := os.WriteFile(RunStatusPath(runDir), []byte(`{"version":1,"phase":"working","required_remaining":2,"open_required_ids":["req-1"],"active_sessions":["session-9"],"updated_at":"2026-03-30T19:12:54Z"}`), 0o644); err != nil {
		t.Fatalf("write status: %v", err)
	}
	if err := SaveCoordinationState(CoordinationPath(runDir), &CoordinationState{
		Version: 1,
		Required: map[string]CoordinationRequiredItem{
			"req-1": {
				ExecutionState: coordinationRequiredExecutionStateProbing,
				Surfaces: CoordinationRequiredSurfaces{
					Repo:           coordinationRequiredSurfaceActive,
					Runtime:        coordinationRequiredSurfaceActive,
					RunArtifacts:   coordinationRequiredSurfaceActive,
					WebResearch:    coordinationRequiredSurfaceActive,
					ExternalSystem: coordinationRequiredSurfacePending,
				},
			},
			"req-2": {
				ExecutionState: coordinationRequiredExecutionStateProbing,
				Surfaces: CoordinationRequiredSurfaces{
					Repo:           coordinationRequiredSurfaceActive,
					Runtime:        coordinationRequiredSurfaceActive,
					RunArtifacts:   coordinationRequiredSurfaceActive,
					WebResearch:    coordinationRequiredSurfaceActive,
					ExternalSystem: coordinationRequiredSurfacePending,
				},
			},
		},
		Sessions: map[string]CoordinationSession{
			"session-5": {State: "active", CoversRequired: []string{"req-1", "req-2"}},
		},
	}); err != nil {
		t.Fatalf("SaveCoordinationState: %v", err)
	}
	for _, session := range []SessionRuntimeState{
		{Name: "session-5", State: "idle", Mode: string(goalx.ModeWorker)},
		{Name: "session-1", State: "parked", Mode: string(goalx.ModeWorker)},
		{Name: "session-2", State: "idle", Mode: string(goalx.ModeWorker)},
	} {
		if err := UpsertSessionRuntimeState(runDir, session); err != nil {
			t.Fatalf("UpsertSessionRuntimeState %s: %v", session.Name, err)
		}
	}

	facts, err := BuildControlGapFacts(runDir)
	if err != nil {
		t.Fatalf("BuildControlGapFacts: %v", err)
	}
	if facts == nil {
		t.Fatal("BuildControlGapFacts returned nil")
	}
	if !facts.StatusDrift {
		t.Fatalf("StatusDrift = false, want true: %+v", facts)
	}
	if !facts.SerializedRequiredFrontier {
		t.Fatalf("SerializedRequiredFrontier = false, want true: %+v", facts)
	}
	if !facts.ReusableCapacityPresent {
		t.Fatalf("ReusableCapacityPresent = false, want true: %+v", facts)
	}
	if got, want := facts.OpenRequiredCount, 2; got != want {
		t.Fatalf("OpenRequiredCount = %d, want %d", got, want)
	}
	if got, want := facts.ActiveRequiredOwnerCount, 1; got != want {
		t.Fatalf("ActiveRequiredOwnerCount = %d, want %d", got, want)
	}
	if got, want := facts.ActiveRequiredOwners, []string{"session-5"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("ActiveRequiredOwners = %v, want %v", got, want)
	}
	if got, want := facts.ReusableSessions, []string{"session-1", "session-2"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("ReusableSessions = %v, want %v", got, want)
	}
}

func TestBuildControlGapFactsDetectsCoordinationStaleFromIntegrationUpdate(t *testing.T) {
	_, runDir, _, _ := writeGuidanceRunFixture(t)
	if err := writeBoundaryFixture(t, runDir, &GoalState{
		Required: []GoalItem{
			{ID: "req-1", Text: "ship cockpit", Source: goalItemSourceUser, Role: goalItemRoleOutcome, State: goalItemStateOpen},
		},
	}); err != nil {
		t.Fatalf("SaveGoalState: %v", err)
	}
	if err := SaveRunStatusRecord(RunStatusPath(runDir), &RunStatusRecord{
		Version:           1,
		Phase:             runStatusPhaseWorking,
		RequiredRemaining: intPtr(1),
		OpenRequiredIDs:   []string{"req-1"},
		ActiveSessions:    []string{"session-5"},
		UpdatedAt:         "2026-03-30T19:12:54Z",
	}); err != nil {
		t.Fatalf("SaveRunStatusRecord: %v", err)
	}
	if err := SaveCoordinationState(CoordinationPath(runDir), &CoordinationState{
		Version:   1,
		UpdatedAt: "2026-03-30T19:12:54Z",
		Required: map[string]CoordinationRequiredItem{
			"req-1": {
				ExecutionState: coordinationRequiredExecutionStateProbing,
				Surfaces: CoordinationRequiredSurfaces{
					Repo:           coordinationRequiredSurfaceActive,
					Runtime:        coordinationRequiredSurfaceActive,
					RunArtifacts:   coordinationRequiredSurfaceActive,
					WebResearch:    coordinationRequiredSurfacePending,
					ExternalSystem: coordinationRequiredSurfaceNotApplicable,
				},
			},
		},
		Sessions: map[string]CoordinationSession{
			"session-5": {State: "active", CoversRequired: []string{"req-1"}},
		},
	}); err != nil {
		t.Fatalf("SaveCoordinationState: %v", err)
	}
	if err := SaveIntegrationState(IntegrationStatePath(runDir), &IntegrationState{
		Version:             1,
		CurrentExperimentID: "exp-2",
		CurrentBranch:       "goalx/guidance-run/root",
		CurrentCommit:       "abc123",
		UpdatedAt:           "2026-03-31T01:05:35Z",
	}); err != nil {
		t.Fatalf("SaveIntegrationState: %v", err)
	}
	if err := UpsertSessionRuntimeState(runDir, SessionRuntimeState{Name: "session-5", State: "idle", Mode: string(goalx.ModeWorker)}); err != nil {
		t.Fatalf("UpsertSessionRuntimeState: %v", err)
	}

	facts, err := BuildControlGapFacts(runDir)
	if err != nil {
		t.Fatalf("BuildControlGapFacts: %v", err)
	}
	if facts == nil {
		t.Fatal("BuildControlGapFacts returned nil")
	}
	if !facts.CoordinationStale {
		t.Fatalf("CoordinationStale = false, want true: %+v", facts)
	}
	if got, want := facts.CoordinationUpdatedAt, "2026-03-30T19:12:54Z"; got != want {
		t.Fatalf("CoordinationUpdatedAt = %q, want %q", got, want)
	}
	if got, want := facts.LatestControlChangeAt, "2026-03-31T01:05:35Z"; got != want {
		t.Fatalf("LatestControlChangeAt = %q, want %q", got, want)
	}
}

func TestBuildControlGapFactsDoesNotFlagSerializedFrontierWhenMultipleOwnersActive(t *testing.T) {
	_, runDir, _, _ := writeGuidanceRunFixture(t)
	if err := writeBoundaryFixture(t, runDir, &GoalState{
		Required: []GoalItem{
			{ID: "req-1", Text: "ship cockpit", Source: goalItemSourceUser, Role: goalItemRoleOutcome, State: goalItemStateOpen},
			{ID: "req-2", Text: "ship research spine", Source: goalItemSourceUser, Role: goalItemRoleOutcome, State: goalItemStateOpen},
		},
	}); err != nil {
		t.Fatalf("SaveGoalState: %v", err)
	}
	if err := SaveRunStatusRecord(RunStatusPath(runDir), &RunStatusRecord{
		Version:           1,
		Phase:             runStatusPhaseWorking,
		RequiredRemaining: intPtr(2),
		OpenRequiredIDs:   []string{"req-1", "req-2"},
		ActiveSessions:    []string{"session-1", "session-2"},
		UpdatedAt:         "2026-03-30T19:12:54Z",
	}); err != nil {
		t.Fatalf("SaveRunStatusRecord: %v", err)
	}
	if err := SaveCoordinationState(CoordinationPath(runDir), &CoordinationState{
		Version: 1,
		Required: map[string]CoordinationRequiredItem{
			"req-1": {
				ExecutionState: coordinationRequiredExecutionStateProbing,
				Surfaces: CoordinationRequiredSurfaces{
					Repo:           coordinationRequiredSurfaceActive,
					Runtime:        coordinationRequiredSurfaceActive,
					RunArtifacts:   coordinationRequiredSurfaceActive,
					WebResearch:    coordinationRequiredSurfacePending,
					ExternalSystem: coordinationRequiredSurfaceNotApplicable,
				},
			},
			"req-2": {
				ExecutionState: coordinationRequiredExecutionStateProbing,
				Surfaces: CoordinationRequiredSurfaces{
					Repo:           coordinationRequiredSurfaceActive,
					Runtime:        coordinationRequiredSurfaceActive,
					RunArtifacts:   coordinationRequiredSurfaceActive,
					WebResearch:    coordinationRequiredSurfacePending,
					ExternalSystem: coordinationRequiredSurfaceNotApplicable,
				},
			},
		},
		Sessions: map[string]CoordinationSession{
			"session-1": {State: "active", CoversRequired: []string{"req-1"}},
			"session-2": {State: "idle", CoversRequired: []string{"req-2"}},
		},
	}); err != nil {
		t.Fatalf("SaveCoordinationState: %v", err)
	}
	for _, session := range []SessionRuntimeState{
		{Name: "session-1", State: "active", Mode: string(goalx.ModeWorker)},
		{Name: "session-2", State: "idle", Mode: string(goalx.ModeWorker)},
		{Name: "session-3", State: "parked", Mode: string(goalx.ModeWorker)},
	} {
		if err := UpsertSessionRuntimeState(runDir, session); err != nil {
			t.Fatalf("UpsertSessionRuntimeState %s: %v", session.Name, err)
		}
	}

	facts, err := BuildControlGapFacts(runDir)
	if err != nil {
		t.Fatalf("BuildControlGapFacts: %v", err)
	}
	if facts == nil {
		t.Fatal("BuildControlGapFacts returned nil")
	}
	if facts.SerializedRequiredFrontier {
		t.Fatalf("SerializedRequiredFrontier = true, want false: %+v", facts)
	}
	if got, want := facts.ActiveRequiredOwnerCount, 2; got != want {
		t.Fatalf("ActiveRequiredOwnerCount = %d, want %d", got, want)
	}
	if got, want := facts.ActiveRequiredOwners, []string{"session-1", "session-2"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("ActiveRequiredOwners = %v, want %v", got, want)
	}
}

func TestBuildControlGapFactsDetectsDispatchableParallelFrontier(t *testing.T) {
	_, runDir, _, _ := writeGuidanceRunFixture(t)
	if err := writeBoundaryFixture(t, runDir, &GoalState{
		Required: []GoalItem{
			{ID: "req-1", Text: "ship cockpit", Source: goalItemSourceUser, Role: goalItemRoleOutcome, State: goalItemStateOpen},
			{ID: "req-2", Text: "ship research spine", Source: goalItemSourceUser, Role: goalItemRoleOutcome, State: goalItemStateOpen},
			{ID: "req-3", Text: "ship operator trust", Source: goalItemSourceUser, Role: goalItemRoleOutcome, State: goalItemStateOpen},
		},
	}); err != nil {
		t.Fatalf("SaveGoalState: %v", err)
	}
	if err := SaveCoordinationState(CoordinationPath(runDir), &CoordinationState{
		Version: 1,
		Required: map[string]CoordinationRequiredItem{
			"req-1": {
				ExecutionState: coordinationRequiredExecutionStateProbing,
				Surfaces:       CoordinationRequiredSurfaces{Repo: coordinationRequiredSurfaceActive, Runtime: coordinationRequiredSurfaceActive, RunArtifacts: coordinationRequiredSurfacePending, WebResearch: coordinationRequiredSurfacePending, ExternalSystem: coordinationRequiredSurfaceNotApplicable},
			},
			"req-2": {
				ExecutionState: coordinationRequiredExecutionStateProbing,
				Surfaces:       CoordinationRequiredSurfaces{Repo: coordinationRequiredSurfaceActive, Runtime: coordinationRequiredSurfacePending, RunArtifacts: coordinationRequiredSurfacePending, WebResearch: coordinationRequiredSurfacePending, ExternalSystem: coordinationRequiredSurfaceNotApplicable},
			},
			"req-3": {
				ExecutionState: coordinationRequiredExecutionStateProbing,
				Surfaces:       CoordinationRequiredSurfaces{Repo: coordinationRequiredSurfaceActive, Runtime: coordinationRequiredSurfacePending, RunArtifacts: coordinationRequiredSurfacePending, WebResearch: coordinationRequiredSurfacePending, ExternalSystem: coordinationRequiredSurfaceNotApplicable},
			},
		},
		Sessions: map[string]CoordinationSession{
			"session-5": {
				State:          "active",
				CoversRequired: []string{"req-1"},
			},
			"session-4": {
				State: "parked",
				DispatchableSlices: []goalx.DispatchableSlice{
					{Title: "split req-2 lane", CoversRequired: []string{"req-2"}},
					{Title: "split req-3 lane", CoversRequired: []string{"req-3"}},
				},
			},
		},
	}); err != nil {
		t.Fatalf("SaveCoordinationState: %v", err)
	}
	for _, session := range []SessionRuntimeState{
		{Name: "session-5", State: "active", Mode: string(goalx.ModeWorker)},
		{Name: "session-4", State: "parked", Mode: string(goalx.ModeWorker)},
	} {
		if err := UpsertSessionRuntimeState(runDir, session); err != nil {
			t.Fatalf("UpsertSessionRuntimeState %s: %v", session.Name, err)
		}
	}

	facts, err := BuildControlGapFacts(runDir)
	if err != nil {
		t.Fatalf("BuildControlGapFacts: %v", err)
	}
	if !facts.DispatchableParallelFrontier {
		t.Fatalf("DispatchableParallelFrontier = false, want true: %+v", facts)
	}
	if got, want := facts.DispatchableRequiredIDs, []string{"req-2", "req-3"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("DispatchableRequiredIDs = %v, want %v", got, want)
	}
	if got, want := facts.DispatchableSources, []string{"session-4"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("DispatchableSources = %v, want %v", got, want)
	}
}
