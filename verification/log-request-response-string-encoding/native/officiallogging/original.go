package officiallogging
import("encoding/json"; "github.com/tidwall/gjson")
var output []byte
var proxywasm = struct{SetProperty func([]string, []byte)error}{func(_ []string, v []byte)error {output=v;return nil}}
var log = struct{Errorf func(string,...interface{})}{func(_ string,_ ...interface{}){}}
func setPropertyWithMarshal(key string, value string) {
	// Create a helper map to properly escape the string using JSON marshaling
	helper := map[string]string{
		"placeholder": value,
	}

	// Marshal the helper map to JSON
	marshalledHelper, _ := json.Marshal(helper)

	// Extract the properly escaped value using gjson
	marshalledRaw := gjson.GetBytes(marshalledHelper, "placeholder").Raw

	var marshalledStr string
	if len(marshalledRaw) >= 2 {
		// Remove the surrounding quotes from the JSON string
		marshalledStr = marshalledRaw[1 : len(marshalledRaw)-1]
	} else {
		log.Errorf("failed to marshal json string, raw string is: %s", value)
		marshalledStr = ""
	}

	// Set the property with the marshaled string
	if err := proxywasm.SetProperty([]string{key}, []byte(marshalledStr)); err != nil {
		log.Errorf("failed to set %s in filter state, err: %v, raw:\n%s", key, err, value)
	}
}
