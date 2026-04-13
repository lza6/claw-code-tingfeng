package cli

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	goalx "github.com/vonbai/goalx"
)

func TestBuildProtocolCompositionLoadsCompilerArtifacts(t *testing.T) {
	runDir := t.TempDir()

	if err := SaveCompiledProtocolComposition(ProtocolCompositionPath(runDir), &CompiledProtocolComposition{
		Version:         1,
		CompilerVersion: successCompilerVersion,
		Philosophy: []string{
			"durable_state_first",
			"localized_override_not_reset",
		},
		BehaviorContract: []string{
			"compact_decisive_output",
			"workflow_gates_are_real",
		},
		RequiredRoles:      []string{"builder", "critic"},
		RequiredGates:      []string{"critic_pass", "finisher_pass"},
		RequiredProofKinds: []string{"acceptance_check", "run_artifact"},
		SelectedPriorRefs:  []string{"prior/from-report"},
		SourceSlots: []ProtocolCompositionSlot{
			{Slot: CompilerInputSlotRepoPolicy, Refs: []string{"README.md"}},
			{Slot: CompilerInputSlotLearnedSuccessPriors, Refs: []string{"memory/success-priors.jsonl"}},
		},
		OutputSources: []ProtocolCompositionOutput{
			{Output: "workflow-plan", SourceSlot: CompilerInputSlotLearnedSuccessPriors, Refs: []string{"memory/success-priors.jsonl"}},
		},
	}); err != nil {
		t.Fatalf("SaveCompiledProtocolComposition: %v", err)
	}

	composition, err := buildProtocolComposition(runDir, ProtocolComposition{})
	if err != nil {
		t.Fatalf("buildProtocolComposition: %v", err)
	}
	if !composition.Enabled {
		t.Fatalf("composition.Enabled = false, want true")
	}
	for _, want := range []string{"durable_state_first", "localized_override_not_reset"} {
		if !containsString(composition.Philosophy, want) {
			t.Fatalf("composition.Philosophy = %v, want %q", composition.Philosophy, want)
		}
	}
	for _, want := range []string{"compact_decisive_output", "workflow_gates_are_real"} {
		if !containsString(composition.BehaviorContract, want) {
			t.Fatalf("composition.BehaviorContract = %v, want %q", composition.BehaviorContract, want)
		}
	}
	if !containsString(composition.RequiredRoles, "builder") || !containsString(composition.RequiredRoles, "critic") {
		t.Fatalf("composition.RequiredRoles = %v, want builder+critic", composition.RequiredRoles)
	}
	if !containsString(composition.RequiredGates, "critic_pass") || !containsString(composition.RequiredGates, "finisher_pass") {
		t.Fatalf("composition.RequiredGates = %v, want critic_pass+finisher_pass", composition.RequiredGates)
	}
	if !containsString(composition.RequiredProofKinds, "acceptance_check") || !containsString(composition.RequiredProofKinds, "run_artifact") {
		t.Fatalf("composition.RequiredProofKinds = %v, want acceptance_check+run_artifact", composition.RequiredProofKinds)
	}
	if len(composition.SourceSlots) != 2 {
		t.Fatalf("composition.SourceSlots = %+v, want 2 slots", composition.SourceSlots)
	}
	if len(composition.OutputSources) != 1 || composition.OutputSources[0].Output != "workflow-plan" {
		t.Fatalf("composition.OutputSources = %+v, want workflow-plan mapping", composition.OutputSources)
	}
	if len(composition.SelectedPriorRefs) != 1 || composition.SelectedPriorRefs[0] != "prior/from-report" {
		t.Fatalf("composition.SelectedPriorRefs = %v, want compiler-report override", composition.SelectedPriorRefs)
	}
}

func TestRenderMasterProtocolIncludesCompilerComposedDoctrine(t *testing.T) {
	runDir := t.TempDir()
	if err := SaveCompiledProtocolComposition(ProtocolCompositionPath(runDir), &CompiledProtocolComposition{
		Version:         1,
		CompilerVersion: successCompilerVersion,
		Philosophy: []string{
			"durable_state_first",
		},
		BehaviorContract: []string{
			"workflow_gates_are_real",
		},
		RequiredRoles:      []string{"builder", "critic", "finisher"},
		RequiredGates:      []string{"critic_pass", "finisher_pass"},
		SelectedPriorRefs:  []string{"prior/operator-cockpit"},
		SourceSlots:        []ProtocolCompositionSlot{{Slot: CompilerInputSlotRepoPolicy, Refs: []string{"README.md"}}},
		OutputSources:      []ProtocolCompositionOutput{{Output: "workflow-plan", SourceSlot: CompilerInputSlotRepoPolicy, Refs: []string{"README.md"}}},
		RequiredProofKinds: []string{"run_artifact"},
	}); err != nil {
		t.Fatalf("SaveCompiledProtocolComposition: %v", err)
	}

	data := ProtocolData{
		RunName:     "demo",
		Objective:   "ship it",
		Mode:        goalx.ModeWorker,
		Engine:      "codex",
		Master:      goalx.MasterConfig{Engine: "codex", Model: "gpt-5.4"},
		ProjectRoot: "/tmp/project",
	}
	if err := RenderMasterProtocol(data, runDir); err != nil {
		t.Fatalf("RenderMasterProtocol: %v", err)
	}
	out, err := os.ReadFile(filepath.Join(runDir, "master.md"))
	if err != nil {
		t.Fatalf("read rendered protocol: %v", err)
	}
	text := string(out)
	for _, want := range []string{
		"### Compiler-Composed Doctrine",
		"Prompt philosophy in force:",
		"`durable_state_first`",
		"Behavior contract in force:",
		"`workflow_gates_are_real`",
		"Required workflow roles: `builder`, `critic`, `finisher`",
		"Required workflow gates: `critic_pass`, `finisher_pass`",
		"Selected prior refs: `prior/operator-cockpit`",
		"Compiler source slots:",
		"`repo_policy` <= `README.md`",
		"Compiler output mapping:",
		"`workflow-plan` <= `repo_policy` (`README.md`)",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("rendered master protocol missing %q:\n%s", want, text)
		}
	}
}

func TestBuildProtocolCompositionSelectsOnlyActiveSuccessPriorRefs(t *testing.T) {
	repo, runDir, cfg, meta := writeGuidanceRunFixture(t)
	if err := os.WriteFile(filepath.Join(repo, "AGENTS.md"), []byte("repo policy"), 0o644); err != nil {
		t.Fatalf("write AGENTS.md: %v", err)
	}
	if err := EnsureMemoryStore(); err != nil {
		t.Fatalf("EnsureMemoryStore: %v", err)
	}
	writeCanonicalMemoryEntries(t, map[MemoryKind][]MemoryEntry{
		MemoryKindSuccessPrior: {
			{
				ID:                "prior-superseded",
				Kind:              MemoryKindSuccessPrior,
				Statement:         "old prior should not survive",
				Selectors:         map[string]string{"project_id": goalx.ProjectID(repo)},
				VerificationState: "repeated",
				Confidence:        "grounded",
				SupersededBy:      "prior-active",
				CreatedAt:         "2026-03-30T00:00:00Z",
				UpdatedAt:         "2026-03-30T00:00:00Z",
			},
			{
				ID:                "prior-contradicted",
				Kind:              MemoryKindSuccessPrior,
				Statement:         "contradicted prior should lose",
				Selectors:         map[string]string{"project_id": goalx.ProjectID(repo)},
				VerificationState: "repeated",
				Confidence:        "grounded",
				ContradictedCount: 1,
				CreatedAt:         "2026-03-30T00:00:00Z",
				UpdatedAt:         "2026-03-30T00:00:00Z",
			},
			{
				ID:                "prior-active",
				Kind:              MemoryKindSuccessPrior,
				Statement:         "active prior should shape protocol composition",
				Selectors:         map[string]string{"project_id": goalx.ProjectID(repo)},
				VerificationState: "repeated",
				Confidence:        "grounded",
				CreatedAt:         "2026-03-31T00:00:00Z",
				UpdatedAt:         "2026-03-31T00:00:00Z",
			},
		},
	})

	if err := EnsureSuccessCompilation(repo, runDir, cfg, meta); err != nil {
		t.Fatalf("EnsureSuccessCompilation: %v", err)
	}

	composition, err := buildProtocolComposition(runDir, ProtocolComposition{})
	if err != nil {
		t.Fatalf("buildProtocolComposition: %v", err)
	}
	if len(composition.SelectedPriorRefs) == 0 {
		t.Fatalf("selected prior refs = %v, want active prior", composition.SelectedPriorRefs)
	}
	if containsString(composition.SelectedPriorRefs, "prior-superseded") {
		t.Fatalf("selected prior refs = %v, should omit superseded prior", composition.SelectedPriorRefs)
	}
	if composition.SelectedPriorRefs[0] != "prior-active" {
		t.Fatalf("selected prior refs = %v, want active prior first", composition.SelectedPriorRefs)
	}
}
