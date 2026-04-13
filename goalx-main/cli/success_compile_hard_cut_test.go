package cli

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	goalx "github.com/vonbai/goalx"
)

func TestEnsureSuccessCompilationOmitsCloseoutRequirements(t *testing.T) {
	repo, runDir, cfg, meta := writeGuidanceRunFixture(t)

	if err := EnsureSuccessCompilation(repo, runDir, cfg, meta); err != nil {
		t.Fatalf("EnsureSuccessCompilation: %v", err)
	}

	data, err := os.ReadFile(SuccessModelPath(runDir))
	if err != nil {
		t.Fatalf("ReadFile(success-model): %v", err)
	}
	if strings.Contains(string(data), "closeout_requirements") {
		t.Fatalf("success-model should not persist closeout_requirements after hard cut:\n%s", string(data))
	}
}

func TestEnsureSuccessCompilationOmitsDomainPackDomain(t *testing.T) {
	repo, runDir, cfg, meta := writeGuidanceRunFixture(t)

	if err := EnsureSuccessCompilation(repo, runDir, cfg, meta); err != nil {
		t.Fatalf("EnsureSuccessCompilation: %v", err)
	}

	data, err := os.ReadFile(DomainPackPath(runDir))
	if err != nil {
		t.Fatalf("ReadFile(domain-pack): %v", err)
	}
	if strings.Contains(string(data), `"domain"`) {
		t.Fatalf("domain-pack should not persist framework-authored domain labels after hard cut:\n%s", string(data))
	}
}

func TestEnsureSuccessCompilationCompilesWorkflowPlanFromIntentAndObligations(t *testing.T) {
	repo, runDir, cfg, meta := writeGuidanceRunFixture(t)
	meta.Intent = runIntentExplore
	if err := SaveRunMetadata(RunMetadataPath(runDir), meta); err != nil {
		t.Fatalf("SaveRunMetadata: %v", err)
	}

	if _, err := EnsureObjectiveContract(runDir, cfg.Objective); err != nil {
		t.Fatalf("EnsureObjectiveContract: %v", err)
	}
	objectiveHash, err := hashFileSHA256(ObjectiveContractPath(runDir))
	if err != nil {
		t.Fatalf("hashFileSHA256(objective): %v", err)
	}
	if err := SaveObligationModel(ObligationModelPath(runDir), &ObligationModel{
		Version:               1,
		ObjectiveContractHash: objectiveHash,
		Required: []ObligationItem{
			{
				ID:                "obl-proof-only",
				Text:              "Investigate and prove the current failure mode.",
				Source:            goalItemSourceMaster,
				Kind:              "proof",
				State:             goalItemStateOpen,
				CoversClauses:     []string{"legacy-goal:obl-proof-only"},
				AssuranceRequired: true,
			},
		},
		Optional:   []ObligationItem{},
		Guardrails: []ObligationItem{},
	}); err != nil {
		t.Fatalf("SaveObligationModel: %v", err)
	}

	if err := EnsureSuccessCompilation(repo, runDir, cfg, meta); err != nil {
		t.Fatalf("EnsureSuccessCompilation: %v", err)
	}

	plan, err := LoadWorkflowPlan(WorkflowPlanPath(runDir))
	if err != nil {
		t.Fatalf("LoadWorkflowPlan: %v", err)
	}
	if plan == nil {
		t.Fatal("workflow plan missing")
	}
	if workflowPlanRequiresRole(plan, "builder") {
		t.Fatalf("workflow plan should not require builder for explore + proof-only run: %+v", plan.RequiredRoles)
	}
	if workflowPlanRequiresRole(plan, "finisher") {
		t.Fatalf("workflow plan should not require finisher for explore + proof-only run: %+v", plan.RequiredRoles)
	}
	if !workflowPlanRequiresRole(plan, "critic") {
		t.Fatalf("workflow plan should require critic for explore + proof-only run: %+v", plan.RequiredRoles)
	}
}

func TestEnsureSuccessCompilationCompilesProofItemsFromAssuranceRequirement(t *testing.T) {
	repo, runDir, cfg, meta := writeGuidanceRunFixture(t)

	if _, err := EnsureObjectiveContract(runDir, cfg.Objective); err != nil {
		t.Fatalf("EnsureObjectiveContract: %v", err)
	}
	objectiveHash, err := hashFileSHA256(ObjectiveContractPath(runDir))
	if err != nil {
		t.Fatalf("hashFileSHA256(objective): %v", err)
	}
	if err := SaveObligationModel(ObligationModelPath(runDir), &ObligationModel{
		Version:               1,
		ObjectiveContractHash: objectiveHash,
		Required: []ObligationItem{
			{
				ID:                "obl-assured-outcome",
				Text:              "The operator workflow works with real assurance coverage.",
				Source:            goalItemSourceMaster,
				Kind:              "outcome",
				State:             goalItemStateOpen,
				CoversClauses:     []string{"legacy-goal:obl-assured-outcome"},
				AssuranceRequired: true,
			},
		},
		Optional:   []ObligationItem{},
		Guardrails: []ObligationItem{},
	}); err != nil {
		t.Fatalf("SaveObligationModel: %v", err)
	}
	if err := SaveAssurancePlan(AssurancePlanPath(runDir), &AssurancePlan{
		Version:        1,
		ObligationRefs: []string{"obl-assured-outcome"},
		Scenarios: []AssuranceScenario{
			{
				ID:                "scenario-assured-outcome",
				CoversObligations: []string{"obl-assured-outcome"},
				Harness: AssuranceHarness{
					Kind:    "cli",
					Command: "echo ok",
				},
				Oracle: AssuranceOracle{
					Kind: "compound",
					CheckDefinitions: []AssuranceOracleCheck{
						{Kind: "exit_code", Equals: "0"},
					},
				},
				Evidence: []AssuranceEvidenceRequirement{{Kind: "stdout"}},
				GatePolicy: AssuranceGatePolicy{
					Closeout: "required",
					Merge:    "required",
				},
			},
		},
	}); err != nil {
		t.Fatalf("SaveAssurancePlan: %v", err)
	}

	if err := EnsureSuccessCompilation(repo, runDir, cfg, meta); err != nil {
		t.Fatalf("EnsureSuccessCompilation: %v", err)
	}

	plan, err := LoadProofPlan(ProofPlanPath(runDir))
	if err != nil {
		t.Fatalf("LoadProofPlan: %v", err)
	}
	if plan == nil {
		t.Fatal("proof plan missing")
	}
	item := findProofPlanItem(plan, "proof-obligation-obl-assured-outcome")
	if item == nil {
		t.Fatalf("proof plan missing obligation proof item: %+v", plan.Items)
	}
	if item.Kind != "assurance_check" {
		t.Fatalf("proof item kind = %q, want assurance_check when obligation has assurance_required", item.Kind)
	}
	if item.SourceSurface != "assurance" {
		t.Fatalf("proof item source_surface = %q, want assurance", item.SourceSurface)
	}
}

func TestEnsureSuccessCompilationWritesProtocolCompositionSurface(t *testing.T) {
	repo, runDir, cfg, meta := writeGuidanceRunFixture(t)

	if err := EnsureSuccessCompilation(repo, runDir, cfg, meta); err != nil {
		t.Fatalf("EnsureSuccessCompilation: %v", err)
	}

	path := filepath.Join(runDir, "protocol-composition.json")
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("protocol composition surface missing at %s: %v", path, err)
	}
}

func TestRefreshRunSuccessContextRecompilesSemanticOutputs(t *testing.T) {
	repo, runDir, cfg, meta := writeGuidanceRunFixture(t)

	if err := EnsureSuccessCompilation(repo, runDir, cfg, meta); err != nil {
		t.Fatalf("EnsureSuccessCompilation: %v", err)
	}
	before, err := LoadSuccessModel(SuccessModelPath(runDir))
	if err != nil {
		t.Fatalf("LoadSuccessModel(before): %v", err)
	}
	if before == nil {
		t.Fatal("success model missing before refresh")
	}

	if err := EnsureMemoryStore(); err != nil {
		t.Fatalf("EnsureMemoryStore: %v", err)
	}
	writeCanonicalMemoryEntries(t, map[MemoryKind][]MemoryEntry{
		MemoryKindSuccessPrior: {
			{
				ID:                "prior-refresh-hard-cut",
				Kind:              MemoryKindSuccessPrior,
				Statement:         "selected prior should force semantic recompilation",
				Selectors:         map[string]string{"project_id": goalx.ProjectID(repo)},
				VerificationState: "repeated",
				Confidence:        "grounded",
				CreatedAt:         "2026-04-01T00:00:00Z",
				UpdatedAt:         "2026-04-01T00:00:00Z",
			},
		},
	})

	time.Sleep(time.Second)
	changed, err := RefreshRunSuccessContext(repo, runDir, cfg, meta)
	if err != nil {
		t.Fatalf("RefreshRunSuccessContext: %v", err)
	}
	if !changed {
		t.Fatal("RefreshRunSuccessContext should report semantic input change")
	}
	after, err := LoadSuccessModel(SuccessModelPath(runDir))
	if err != nil {
		t.Fatalf("LoadSuccessModel(after): %v", err)
	}
	if after == nil {
		t.Fatal("success model missing after refresh")
	}
	if after.CompiledAt == before.CompiledAt {
		t.Fatalf("success-model compiled_at did not change after semantic input refresh: before=%q after=%q", before.CompiledAt, after.CompiledAt)
	}
}

func workflowPlanRequiresRole(plan *WorkflowPlan, want string) bool {
	if plan == nil {
		return false
	}
	for _, role := range plan.RequiredRoles {
		if role.Required && role.ID == want {
			return true
		}
	}
	return false
}

func findProofPlanItem(plan *ProofPlan, id string) *ProofPlanItem {
	if plan == nil {
		return nil
	}
	for i := range plan.Items {
		if plan.Items[i].ID == id {
			return &plan.Items[i]
		}
	}
	return nil
}
