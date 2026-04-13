package cli

import (
	"strings"
	"testing"
)

func TestDerivePhaseRunNamePreservesDistinctPhaseSuffixForLongSourceRun(t *testing.T) {
	source := "design-the-next-generation-backend-architecture-for-synapse"

	got := derivePhaseRunName(source, "implement", "")

	if got == source {
		t.Fatalf("derivePhaseRunName = %q, want distinct phase run name", got)
	}
	if !strings.HasSuffix(got, "-implement") {
		t.Fatalf("derivePhaseRunName = %q, want -implement suffix", got)
	}
	if len(got) > 60 {
		t.Fatalf("derivePhaseRunName length = %d, want <= 60", len(got))
	}
}
