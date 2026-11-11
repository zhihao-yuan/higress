package main

import (
	"encoding/json"
	"fmt"
	"runtime/debug"
	"testing"

	"github.com/higress-group/proxy-wasm-go-sdk/proxywasm/types"
	"github.com/higress-group/wasm-go/pkg/test"
	"github.com/stretchr/testify/require"
)

func TestDiscoveryUploadCallback(t *testing.T) {
	test.RunTest(t, func(t *testing.T) {
		config := json.RawMessage(`{
			"embedding":{"type":"dashscope","apiKey":"fixture-key","serviceName":"embedding.static","servicePort":8080},
			"vector":{"type":"dashvector","apiKey":"fixture-key","collectionID":"fixture","serviceName":"vector.static","serviceHost":"vector.fixture","servicePort":8081,"threshold":0.8,"thresholdRelation":"gt"},
			"enableSemanticCache":true,
			"cacheKeyStrategy":"lastQuestion"
		}`)
		host, status := test.NewTestHost(config)
		defer host.Reset()
		require.Equal(t, types.OnPluginStartStatusOK, status)
		host.CallOnHttpRequestHeaders([][2]string{
			{":method","POST"},{":path","/v1/chat/completions"},{":authority","fixture"},
			{"content-type","application/json"},{"x-mse-consumer","fixture-consumer"},
		})
		require.Equal(t, types.ActionPause, host.CallOnHttpRequestBody([]byte(`{"messages":[{"role":"user","content":"question"}],"stream":false}`)))
		require.Len(t,host.GetHttpCalloutAttributes(),1)
		host.CallOnHttpCall([][2]string{{":status","200"}},[]byte(`{"output":{"embeddings":[{"embedding":[0.1,0.2]}]}}`))
		require.Len(t,host.GetHttpCalloutAttributes(),1)
		host.CallOnHttpCall([][2]string{{":status","200"}},[]byte(`{"code":0,"output":[]}`))
		host.CallOnHttpResponseHeaders([][2]string{{":status","200"},{"content-type","application/json"}})
		answer := []byte(`{"choices":[{"message":{"role":"assistant","content":"answer"}}]}`)
		require.Equal(t, types.ActionContinue, host.CallOnHttpResponseBody(answer))
		calls := host.GetHttpCalloutAttributes()
		require.Len(t,calls,1)
		t.Logf("writeback callout: %+v",calls[0])
		defer func() {
			panicValue:=recover()
			require.NotNil(t,panicValue,"expected the existing callback panic")
			t.Logf("HTTP 200 upload completion panicked: %s\n%s",fmt.Sprint(panicValue),debug.Stack())
		}()
		host.CallOnHttpCall([][2]string{{":status","200"}},[]byte(`{"code":0}`))
	})
}
