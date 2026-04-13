package cli

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
)

func decodeStrictJSON(data []byte, dst any) error {
	if len(strings.TrimSpace(string(data))) == 0 {
		return fmt.Errorf("JSON value is empty")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(dst); err != nil {
		return err
	}
	return ensureJSONEOF(decoder)
}
