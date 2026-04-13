package cli

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	goalx "github.com/vonbai/goalx"
)

const successCompilerVersion = "compiler-v3"

type bootstrapCompilerSources struct {
	Query            *MemoryQuery
	Context          *MemoryContext
	Intake           *RunIntake
	PolicySourceRefs []string
	PriorEntryIDs    []string
	SourceSlots      []CompilerInputSlot
	RejectedPriors   []CompilerRejectedPrior
}

func EnsureSuccessCompilation(projectRoot, runDir string, cfg *goalx.Config, meta *RunMetadata) error {
	if cfg == nil {
		return fmt.Errorf("run config is nil")
	}
	if err := RefreshRunMemoryContext(runDir); err != nil {
		return fmt.Errorf("refresh run memory context: %w", err)
	}

	objectiveContract, err := EnsureObjectiveContract(runDir, cfg.Objective)
	if err != nil {
		return fmt.Errorf("ensure objective contract: %w", err)
	}
	objectiveContractHash, err := hashFileSHA256(ObjectiveContractPath(runDir))
	if err != nil {
		return err
	}
	obligationModel, err := EnsureObligationModel(runDir, nil, objectiveContract, objectiveContractHash, cfg.Objective)
	if err != nil {
		return fmt.Errorf("ensure obligation model: %w", err)
	}
	acceptanceState := NewAcceptanceState(cfg, 0)
	assurancePlan, err := EnsureAssurancePlan(runDir, acceptanceState)
	if err != nil {
		return fmt.Errorf("ensure assurance plan: %w", err)
	}
	goalHash, err := hashFileSHA256(CanonicalBoundaryPath(runDir))
	if err != nil {
		return err
	}
	compilerSources, err := buildBootstrapCompilerSources(projectRoot, runDir)
	if err != nil {
		return err
	}
	compilerInput := compileBootstrapCompilerInput(runDir, compilerSources)
	if err := SaveCompilerInput(CompilerInputPath(runDir), compilerInput); err != nil {
		return err
	}

	successModel := compileBootstrapSuccessModel(cfg, objectiveContract, nil, obligationModel, objectiveContractHash, goalHash, compilerSources)
	if err := SaveSuccessModel(SuccessModelPath(runDir), successModel); err != nil {
		return err
	}
	proofPlan := compileBootstrapProofPlan(nil, obligationModel, nil, assurancePlan, successModel)
	if err := SaveProofPlan(ProofPlanPath(runDir), proofPlan); err != nil {
		return err
	}
	workflowPlan := compileBootstrapWorkflowPlan(cfg, meta, obligationModel, successModel)
	if err := SaveWorkflowPlan(WorkflowPlanPath(runDir), workflowPlan); err != nil {
		return err
	}
	domainPack, err := compileBootstrapDomainPack(cfg, meta, compilerSources)
	if err != nil {
		return err
	}
	if err := SaveDomainPack(DomainPackPath(runDir), domainPack); err != nil {
		return err
	}
	compilerReport := compileBootstrapCompilerReport(compilerSources)
	if err := SaveCompilerReport(CompilerReportPath(runDir), compilerReport); err != nil {
		return err
	}
	protocolComposition := compileBootstrapProtocolComposition(proofPlan, workflowPlan, compilerInput, compilerReport)
	if err := SaveCompiledProtocolComposition(ProtocolCompositionPath(runDir), protocolComposition); err != nil {
		return err
	}
	return nil
}

func RefreshRunSuccessContextForRun(projectRoot, runDir string) (bool, error) {
	cfg, err := LoadRunSpec(runDir)
	if err != nil {
		return false, err
	}
	meta, err := LoadRunMetadata(RunMetadataPath(runDir))
	if err != nil {
		return false, err
	}
	if meta == nil {
		meta = &RunMetadata{
			Version:     1,
			ProjectRoot: projectRoot,
		}
	}
	return RefreshRunSuccessContext(projectRoot, runDir, cfg, meta)
}

func RefreshRunSuccessContext(projectRoot, runDir string, cfg *goalx.Config, meta *RunMetadata) (bool, error) {
	if cfg == nil {
		return false, fmt.Errorf("run config is nil")
	}
	if meta == nil {
		loaded, err := LoadRunMetadata(RunMetadataPath(runDir))
		if err != nil {
			return false, err
		}
		if loaded != nil {
			meta = loaded
		} else {
			meta = &RunMetadata{
				Version:     1,
				ProjectRoot: projectRoot,
			}
		}
	}

	beforeContext, err := LoadMemoryContextFile(MemoryContextPath(runDir))
	if err != nil {
		return false, err
	}
	beforeCompilerInput, err := LoadCompilerInput(CompilerInputPath(runDir))
	if err != nil {
		return false, err
	}
	beforeDomainPack, err := LoadDomainPack(DomainPackPath(runDir))
	if err != nil {
		return false, err
	}

	if !fileExists(SuccessModelPath(runDir)) || !fileExists(ProofPlanPath(runDir)) || !fileExists(WorkflowPlanPath(runDir)) || !fileExists(ProtocolCompositionPath(runDir)) {
		if err := EnsureSuccessCompilation(projectRoot, runDir, cfg, meta); err != nil {
			return false, err
		}
	} else {
		if err := RefreshRunMemoryContext(runDir); err != nil {
			return false, fmt.Errorf("refresh run memory context: %w", err)
		}
		compilerSources, err := buildBootstrapCompilerSources(projectRoot, runDir)
		if err != nil {
			return false, err
		}
		compilerInput := compileBootstrapCompilerInput(runDir, compilerSources)
		domainPack, err := compileBootstrapDomainPack(cfg, meta, compilerSources)
		if err != nil {
			return false, err
		}
		afterContext, err := LoadMemoryContextFile(MemoryContextPath(runDir))
		if err != nil {
			return false, err
		}
		inputChanged := compilerInputSignature(beforeCompilerInput) != compilerInputSignature(compilerInput) ||
			!stringSliceEqual(domainPackPriorIDs(beforeDomainPack), domainPackPriorIDs(domainPack)) ||
			!stringSliceEqual(successPriorStatements(beforeContext), successPriorStatements(afterContext))
		if inputChanged {
			if err := EnsureSuccessCompilation(projectRoot, runDir, cfg, meta); err != nil {
				return false, err
			}
		}
	}

	afterContext, err := LoadMemoryContextFile(MemoryContextPath(runDir))
	if err != nil {
		return false, err
	}
	afterCompilerInput, err := LoadCompilerInput(CompilerInputPath(runDir))
	if err != nil {
		return false, err
	}
	afterDomainPack, err := LoadDomainPack(DomainPackPath(runDir))
	if err != nil {
		return false, err
	}
	return compilerInputSignature(beforeCompilerInput) != compilerInputSignature(afterCompilerInput) ||
		!stringSliceEqual(domainPackPriorIDs(beforeDomainPack), domainPackPriorIDs(afterDomainPack)) ||
		(!stringSliceEqual(successPriorStatements(beforeContext), successPriorStatements(afterContext)) && compilerInputSignature(afterCompilerInput) == ""), nil
}

func compileBootstrapSuccessModel(cfg *goalx.Config, objectiveContract *ObjectiveContract, goalState *GoalState, obligationModel *ObligationModel, objectiveContractHash, goalHash string, sources *bootstrapCompilerSources) *SuccessModel {
	model := &SuccessModel{
		Version:               1,
		CompilerVersion:       successCompilerVersion,
		ObjectiveContractHash: objectiveContractHash,
		ObligationModelHash:   goalHash,
		Dimensions: []SuccessDimension{
			{
				ID:       "dim-objective",
				Kind:     "objective",
				Text:     strings.TrimSpace(cfg.Objective),
				Required: true,
			},
		},
	}
	if obligationModel != nil {
		for _, item := range obligationModel.Required {
			if strings.TrimSpace(item.ID) == "" || strings.TrimSpace(item.Text) == "" {
				continue
			}
			model.Dimensions = append(model.Dimensions, SuccessDimension{
				ID:       item.ID,
				Kind:     firstNonEmpty(strings.TrimSpace(item.Kind), "obligation"),
				Text:     strings.TrimSpace(item.Text),
				Required: true,
			})
		}
	} else if goalState != nil {
		for _, item := range goalState.Required {
			if strings.TrimSpace(item.ID) == "" || strings.TrimSpace(item.Text) == "" {
				continue
			}
			model.Dimensions = append(model.Dimensions, SuccessDimension{
				ID:       item.ID,
				Kind:     firstNonEmpty(strings.TrimSpace(item.Role), "goal_item"),
				Text:     strings.TrimSpace(item.Text),
				Required: true,
			})
		}
	}
	if sources != nil && sources.Intake != nil {
		for i, antiGoal := range sources.Intake.AntiGoals {
			text := strings.TrimSpace(antiGoal)
			if text == "" {
				continue
			}
			model.AntiGoals = append(model.AntiGoals, SuccessAntiGoal{
				ID:   fmt.Sprintf("intake-%d", i+1),
				Text: text,
			})
		}
	}
	return model
}

func compileBootstrapProofPlan(goalState *GoalState, obligationModel *ObligationModel, acceptanceState *AcceptanceState, assurancePlan *AssurancePlan, successModel *SuccessModel) *ProofPlan {
	plan := &ProofPlan{
		Version: 1,
		Items: []ProofPlanItem{
			{
				ID:               "proof-summary-objective",
				CoversDimensions: []string{"dim-objective"},
				Kind:             "run_artifact",
				Required:         true,
				SourceSurface:    "summary",
			},
		},
	}
	if obligationModel != nil {
		for _, item := range obligationModel.Required {
			if strings.TrimSpace(item.ID) == "" {
				continue
			}
			proofKind := "run_artifact"
			sourceSurface := "summary"
			if strings.TrimSpace(item.Kind) == "proof" || item.AssuranceRequired || assurancePlanCoversObligation(assurancePlan, item.ID) {
				proofKind = "assurance_check"
				sourceSurface = "assurance"
			}
			plan.Items = append(plan.Items, ProofPlanItem{
				ID:               "proof-obligation-" + goalx.Slugify(item.ID),
				CoversDimensions: []string{item.ID},
				Kind:             proofKind,
				Required:         true,
				SourceSurface:    sourceSurface,
			})
		}
	} else if goalState != nil {
		for _, item := range goalState.Required {
			if strings.TrimSpace(item.ID) == "" {
				continue
			}
			proofKind := "run_artifact"
			sourceSurface := "summary"
			if strings.TrimSpace(item.Role) == goalItemRoleProof {
				proofKind = "assurance_check"
				sourceSurface = "assurance"
			}
			plan.Items = append(plan.Items, ProofPlanItem{
				ID:               "proof-obligation-compat-" + goalx.Slugify(item.ID),
				CoversDimensions: []string{item.ID},
				Kind:             proofKind,
				Required:         true,
				SourceSurface:    sourceSurface,
			})
		}
	}
	if assurancePlan != nil && len(assurancePlan.Scenarios) > 0 {
		for _, scenario := range assurancePlan.Scenarios {
			if strings.TrimSpace(scenario.ID) == "" {
				continue
			}
			covers := compactStrings(scenario.CoversObligations)
			if len(covers) == 0 {
				covers = []string{"dim-objective"}
			}
			plan.Items = append(plan.Items, ProofPlanItem{
				ID:               "proof-assurance-" + goalx.Slugify(scenario.ID),
				CoversDimensions: covers,
				Kind:             "assurance_check",
				Required:         true,
				SourceSurface:    "assurance",
			})
		}
	} else if acceptanceState != nil {
		for _, check := range acceptanceState.Checks {
			if strings.TrimSpace(check.ID) == "" {
				continue
			}
			plan.Items = append(plan.Items, ProofPlanItem{
				ID:               "proof-assurance-compat-" + goalx.Slugify(check.ID),
				CoversDimensions: []string{"dim-objective"},
				Kind:             "assurance_check",
				Required:         true,
				SourceSurface:    "assurance",
			})
		}
	}
	if successModel != nil && len(successModel.Dimensions) == 1 && len(plan.Items) == 1 {
		plan.Items[0].Kind = "bootstrap_proof"
	}
	return plan
}

func compileBootstrapWorkflowPlan(cfg *goalx.Config, meta *RunMetadata, obligationModel *ObligationModel, successModel *SuccessModel) *WorkflowPlan {
	intent := runIntentDeliver
	if meta != nil && strings.TrimSpace(meta.Intent) != "" {
		intent = strings.TrimSpace(meta.Intent)
	}
	requiresBuilder := workflowRequiresBuilder(intent, obligationModel)
	requiresCritic := workflowRequiresCritic(intent, obligationModel, successModel, requiresBuilder)
	requiresFinisher := workflowRequiresFinisher(intent, obligationModel, requiresBuilder)

	roles := []WorkflowRoleRequirement{}
	gates := []string{}
	if requiresBuilder {
		roles = append(roles, WorkflowRoleRequirement{ID: "builder", Required: true})
		gates = append(gates, "builder_result_present")
	}
	if requiresCritic {
		roles = append(roles, WorkflowRoleRequirement{ID: "critic", Required: true})
		gates = append(gates, "critic_review_present")
	}
	if requiresFinisher {
		roles = append(roles, WorkflowRoleRequirement{ID: "finisher", Required: true})
		gates = append(gates, "finisher_pass_present")
	}
	if len(roles) == 0 {
		roles = append(roles, WorkflowRoleRequirement{ID: "critic", Required: true})
		gates = append(gates, "critic_review_present")
	}

	return &WorkflowPlan{
		Version:       1,
		RequiredRoles: roles,
		Gates:         gates,
	}
}

func buildBootstrapCompilerSources(projectRoot, runDir string) (*bootstrapCompilerSources, error) {
	query, err := LoadMemoryQueryFile(MemoryQueryPath(runDir))
	if err != nil {
		return nil, err
	}
	context, err := LoadMemoryContextFile(MemoryContextPath(runDir))
	if err != nil {
		return nil, err
	}
	intake, err := LoadLiveRunIntake(runDir)
	if err != nil {
		return nil, err
	}
	sources := &bootstrapCompilerSources{
		Query:   query,
		Context: context,
		Intake:  intake,
	}
	if query != nil {
		selected, rejected, err := evaluateSuccessPriorCandidates(*query)
		if err != nil {
			return nil, err
		}
		for _, entry := range selected {
			sources.PriorEntryIDs = append(sources.PriorEntryIDs, entry.ID)
		}
		sources.RejectedPriors = append(sources.RejectedPriors, rejected...)
	}
	if _, err := os.Stat(filepath.Join(projectRoot, "AGENTS.md")); err == nil {
		sources.PolicySourceRefs = append(sources.PolicySourceRefs, "AGENTS.md")
		sources.SourceSlots = append(sources.SourceSlots, CompilerInputSlot{
			Slot: CompilerInputSlotRepoPolicy,
			Refs: []string{"AGENTS.md"},
		})
	}
	runContextRefs := []string{}
	if context != nil {
		runContextRefs = append(runContextRefs, filepath.Join("control", "memory-context.json"))
	}
	if intake != nil {
		runContextRefs = append(runContextRefs, filepath.Join("control", "intake.json"))
	}
	if len(runContextRefs) > 0 {
		sources.SourceSlots = append(sources.SourceSlots, CompilerInputSlot{
			Slot: CompilerInputSlotRunContext,
			Refs: runContextRefs,
		})
	}
	if len(sources.PriorEntryIDs) > 0 {
		sources.SourceSlots = append(sources.SourceSlots, CompilerInputSlot{
			Slot: CompilerInputSlotLearnedSuccessPriors,
			Refs: append([]string(nil), sources.PriorEntryIDs...),
		})
	}
	return sources, nil
}

func compileBootstrapCompilerInput(runDir string, sources *bootstrapCompilerSources) *CompilerInput {
	input := &CompilerInput{
		Version:              1,
		CompilerVersion:      successCompilerVersion,
		ObjectiveContractRef: filepath.Base(ObjectiveContractPath(runDir)),
		ObligationModelRef:   filepath.Base(CanonicalBoundaryPath(runDir)),
	}
	if sources == nil {
		return input
	}
	if sources.Query != nil {
		input.MemoryQueryRef = filepath.Join("control", "memory-query.json")
	}
	if sources.Context != nil {
		input.MemoryContextRef = filepath.Join("control", "memory-context.json")
	}
	input.PolicySourceRefs = append([]string(nil), sources.PolicySourceRefs...)
	input.SelectedPriorRefs = append([]string(nil), sources.PriorEntryIDs...)
	input.SourceSlots = append([]CompilerInputSlot(nil), sources.SourceSlots...)
	return input
}

func compileBootstrapCompilerReport(sources *bootstrapCompilerSources) *CompilerReport {
	report := &CompilerReport{
		Version:         1,
		CompilerVersion: successCompilerVersion,
	}
	if sources == nil {
		return report
	}
	for _, slot := range sources.SourceSlots {
		report.AvailableSourceSlots = append(report.AvailableSourceSlots, CompilerReportSlot{
			Slot: slot.Slot,
			Refs: append([]string(nil), slot.Refs...),
		})
		for _, output := range []string{"success-model", "proof-plan", "workflow-plan", "domain-pack", "protocol-composition"} {
			report.OutputSources = append(report.OutputSources, CompilerOutputSource{
				Output:     output,
				SourceSlot: slot.Slot,
				Refs:       append([]string(nil), slot.Refs...),
			})
		}
	}
	report.SelectedPriorRefs = append([]string(nil), sources.PriorEntryIDs...)
	report.RejectedPriors = append([]CompilerRejectedPrior(nil), sources.RejectedPriors...)
	return report
}

func compileBootstrapDomainPack(cfg *goalx.Config, meta *RunMetadata, sources *bootstrapCompilerSources) (*DomainPack, error) {
	priorEntryIDs := []string{}
	if sources != nil {
		priorEntryIDs = append(priorEntryIDs, sources.PriorEntryIDs...)
	}
	signals := []string{firstNonEmpty(strings.TrimSpace(string(cfg.Mode)), "mode_unspecified")}
	if meta != nil && strings.TrimSpace(meta.Intent) != "" {
		signals = append(signals, "intent:"+strings.TrimSpace(meta.Intent))
	}
	if sources != nil && sources.Query != nil && strings.TrimSpace(sources.Query.ProjectID) != "" {
		signals = append(signals, "project:"+strings.TrimSpace(sources.Query.ProjectID))
	}
	if sources != nil && sources.Context != nil && (len(sources.Context.Facts)+len(sources.Context.Procedures)+len(sources.Context.Pitfalls)+len(sources.Context.SecretRefs)+len(sources.Context.SuccessPriors)) > 0 {
		signals = append(signals, "memory_context_present")
	}
	if sources != nil && sources.Intake != nil {
		signals = append(signals, "intake_present")
	}
	if len(priorEntryIDs) > 0 {
		signals = append(signals, "success_prior_present")
	}
	pack := &DomainPack{
		Version:       1,
		Signals:       signals,
		PriorEntryIDs: priorEntryIDs,
	}
	if sources != nil {
		if len(sources.PolicySourceRefs) > 0 {
			pack.Slots.RepoPolicy = DomainPackSlot{
				Source: sources.PolicySourceRefs[0],
				Refs:   append([]string(nil), sources.PolicySourceRefs...),
			}
		}
		if sources.Context != nil {
			pack.Slots.RunContext = DomainPackSlot{
				Source: filepath.Join("control", "memory-context.json"),
				Refs:   []string{filepath.Join("control", "memory-context.json")},
			}
		}
		if len(priorEntryIDs) > 0 {
			pack.Slots.LearnedSuccessPriors = DomainPackSlot{
				EntryIDs: append([]string(nil), priorEntryIDs...),
			}
		}
	}
	return pack, nil
}

func compileBootstrapProtocolComposition(proofPlan *ProofPlan, workflowPlan *WorkflowPlan, compilerInput *CompilerInput, compilerReport *CompilerReport) *CompiledProtocolComposition {
	state := &CompiledProtocolComposition{
		Version:         1,
		CompilerVersion: successCompilerVersion,
		Philosophy: compactStrings([]string{
			"durable_state_first",
			"dispatch_before_self_implementation",
			"success_model_before_local_optimization",
			"evidence_before_completion",
			"localized_override_not_reset",
			"thin_control_explicit_judgment",
		}),
		BehaviorContract: compactStrings([]string{
			"compact_decisive_output",
			"automatic_follow_through",
			"durable_state_first_recovery",
			"localized_override_semantics",
			"evidence_backed_completion",
			"workflow_gates_are_real",
		}),
	}
	if workflowPlan != nil {
		for _, role := range workflowPlan.RequiredRoles {
			if role.Required {
				state.RequiredRoles = append(state.RequiredRoles, role.ID)
			}
		}
		state.RequiredGates = append(state.RequiredGates, workflowPlan.Gates...)
	}
	if proofPlan != nil {
		seenProofKinds := make(map[string]struct{}, len(proofPlan.Items))
		for _, item := range proofPlan.Items {
			key := strings.TrimSpace(item.Kind)
			if key == "" {
				continue
			}
			if _, ok := seenProofKinds[key]; ok {
				continue
			}
			seenProofKinds[key] = struct{}{}
			state.RequiredProofKinds = append(state.RequiredProofKinds, key)
		}
	}
	if compilerInput != nil {
		for _, slot := range compilerInput.SourceSlots {
			state.SourceSlots = append(state.SourceSlots, ProtocolCompositionSlot{
				Slot: slot.Slot,
				Refs: append([]string(nil), slot.Refs...),
			})
		}
		state.SelectedPriorRefs = append([]string(nil), compilerInput.SelectedPriorRefs...)
	}
	if compilerReport != nil {
		if len(compilerReport.SelectedPriorRefs) > 0 {
			state.SelectedPriorRefs = append([]string(nil), compilerReport.SelectedPriorRefs...)
		}
		if len(state.SourceSlots) == 0 {
			for _, slot := range compilerReport.AvailableSourceSlots {
				state.SourceSlots = append(state.SourceSlots, ProtocolCompositionSlot{
					Slot: slot.Slot,
					Refs: append([]string(nil), slot.Refs...),
				})
			}
		}
		for _, output := range compilerReport.OutputSources {
			state.OutputSources = append(state.OutputSources, ProtocolCompositionOutput{
				Output:     output.Output,
				SourceSlot: output.SourceSlot,
				Refs:       append([]string(nil), output.Refs...),
			})
		}
	}
	return state
}

func workflowRequiresBuilder(intent string, obligationModel *ObligationModel) bool {
	switch strings.TrimSpace(intent) {
	case runIntentDeliver, runIntentImplement, runIntentEvolve:
		return true
	}
	if obligationModel == nil {
		return false
	}
	for _, item := range obligationModel.Required {
		switch strings.TrimSpace(item.Kind) {
		case "outcome", "enabler":
			return true
		}
	}
	return false
}

func workflowRequiresCritic(intent string, obligationModel *ObligationModel, successModel *SuccessModel, requiresBuilder bool) bool {
	if requiresBuilder {
		return true
	}
	if obligationModel != nil {
		if len(obligationModel.Guardrails) > 0 {
			return true
		}
		for _, item := range obligationModel.Required {
			if item.AssuranceRequired || strings.TrimSpace(item.Kind) == "proof" {
				return true
			}
		}
	}
	return successModel != nil && len(successModel.AntiGoals) > 0
}

func workflowRequiresFinisher(intent string, obligationModel *ObligationModel, requiresBuilder bool) bool {
	switch strings.TrimSpace(intent) {
	case runIntentDeliver, runIntentEvolve:
		return requiresBuilder
	}
	if !requiresBuilder || obligationModel == nil {
		return false
	}
	for _, item := range obligationModel.Required {
		switch strings.TrimSpace(item.Kind) {
		case "outcome", "enabler":
			return true
		}
	}
	return false
}

func assurancePlanCoversObligation(plan *AssurancePlan, obligationID string) bool {
	if plan == nil || strings.TrimSpace(obligationID) == "" {
		return false
	}
	for _, scenario := range plan.Scenarios {
		for _, covered := range scenario.CoversObligations {
			if strings.TrimSpace(covered) == strings.TrimSpace(obligationID) {
				return true
			}
		}
	}
	return false
}

func evaluateSuccessPriorCandidates(query MemoryQuery) ([]MemoryEntry, []CompilerRejectedPrior, error) {
	entries, err := RetrieveMemory(query)
	if err != nil {
		return nil, nil, err
	}
	selected := make([]MemoryEntry, 0)
	selectedSet := make(map[string]struct{})
	for _, entry := range entries {
		if entry.Kind != MemoryKindSuccessPrior {
			continue
		}
		selected = append(selected, entry)
		selectedSet[entry.ID] = struct{}{}
	}

	allEntries, err := loadCanonicalEntriesForKind(MemoryKindSuccessPrior)
	if err != nil {
		return nil, nil, err
	}
	governance, err := loadMemoryPriorGovernanceSummary()
	if err != nil {
		return nil, nil, err
	}
	rejected := make([]CompilerRejectedPrior, 0)
	for _, entry := range allEntries {
		if _, ok := selectedSet[entry.ID]; ok {
			continue
		}
		rejected = append(rejected, CompilerRejectedPrior{
			Ref:        entry.ID,
			ReasonCode: compilerRejectReasonForSuccessPrior(entry, query, governance[entry.ID]),
		})
	}
	return selected, rejected, nil
}

func compilerRejectReasonForSuccessPrior(entry MemoryEntry, query MemoryQuery, summary memoryPriorGovernanceSummary) string {
	if strings.TrimSpace(firstNonEmpty(summary.SupersededBy, entry.SupersededBy)) != "" {
		return CompilerReasonSuperseded
	}
	if !memoryEntrySelectorsMatch(entry, query) {
		return CompilerReasonNoSelectorMatch
	}
	if entry.ContradictedCount+summary.ContradictedCount > 0 {
		return CompilerReasonContradicted
	}
	return CompilerReasonLowerPriority
}

func memoryEntrySelectorsMatch(entry MemoryEntry, query MemoryQuery) bool {
	querySelectors := querySelectorMap(query)
	for key, value := range entry.Selectors {
		queryValue := querySelectors[key]
		if queryValue == "" {
			continue
		}
		if queryValue != value {
			return false
		}
	}
	return true
}

func compilerInputSignature(input *CompilerInput) string {
	if input == nil {
		return ""
	}
	payload := struct {
		SelectedPriorRefs []string            `json:"selected_prior_refs,omitempty"`
		SourceSlots       []CompilerInputSlot `json:"source_slots,omitempty"`
	}{
		SelectedPriorRefs: append([]string(nil), input.SelectedPriorRefs...),
		SourceSlots:       append([]CompilerInputSlot(nil), input.SourceSlots...),
	}
	data, _ := json.Marshal(payload)
	return string(data)
}

func hashFileSHA256(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(data)
	return "sha256:" + hex.EncodeToString(sum[:]), nil
}

func successPriorStatements(context *MemoryContext) []string {
	if context == nil {
		return nil
	}
	return append([]string(nil), context.SuccessPriors...)
}

func domainPackPriorIDs(pack *DomainPack) []string {
	if pack == nil {
		return nil
	}
	return append([]string(nil), pack.PriorEntryIDs...)
}
