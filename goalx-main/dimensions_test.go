package goalx

import "testing"

func TestResolveDimensionSpecsSupportsBuiltinConfigAndInline(t *testing.T) {
	specs, err := ResolveDimensionSpecs([]string{
		"depth",
		"audit",
		"domain=Focus on domain invariants and contract correctness.",
	}, map[string]string{
		"project": "Project-specific focus.",
		"depth":   "override should not win",
	}, map[string]string{
		"project": "Project-specific focus override.",
	})
	if err != nil {
		t.Fatalf("ResolveDimensionSpecs: %v", err)
	}
	if len(specs) != 3 {
		t.Fatalf("len(specs) = %d, want 3", len(specs))
	}

	if specs[0].Name != "depth" || specs[0].Source != DimensionSourceBuiltin || specs[0].Guidance != BuiltinDimensions["depth"] {
		t.Fatalf("specs[0] = %#v", specs[0])
	}
	if specs[1].Name != "audit" || specs[1].Source != DimensionSourceBuiltin || specs[1].Guidance != BuiltinDimensions["audit"] {
		t.Fatalf("specs[1] = %#v", specs[1])
	}
	if specs[2].Name != "domain" || specs[2].Source != DimensionSourceInline || specs[2].Guidance != "Focus on domain invariants and contract correctness." {
		t.Fatalf("specs[2] = %#v", specs[2])
	}
}

func TestResolveDimensionSpecsIncludesAuditBuiltin(t *testing.T) {
	specs, err := ResolveDimensionSpecs([]string{"audit"})
	if err != nil {
		t.Fatalf("ResolveDimensionSpecs(audit): %v", err)
	}
	if len(specs) != 1 {
		t.Fatalf("len(specs) = %d, want 1", len(specs))
	}
	if specs[0].Name != "audit" || specs[0].Source != DimensionSourceBuiltin {
		t.Fatalf("audit spec = %#v", specs[0])
	}
	if specs[0].Guidance == "" {
		t.Fatal("audit guidance is empty")
	}
}

func TestResolveDimensionSpecsRejectsUnknownBareName(t *testing.T) {
	if _, err := ResolveDimensionSpecs([]string{"unknown"}); err == nil {
		t.Fatal("expected error for unknown dimension")
	}
}
