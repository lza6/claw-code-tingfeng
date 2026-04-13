package cli

import (
	"fmt"
	"strings"
)

// ValidateRunCharterStructure checks that the charter has a valid charter_id.
func ValidateRunCharterStructure(charter *RunCharter) error {
	if charter == nil {
		return fmt.Errorf("run charter is missing")
	}
	if strings.TrimSpace(charter.CharterID) == "" {
		return fmt.Errorf("run charter is missing charter_id")
	}
	return nil
}
