package main

import (
	"bytes"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"
)

func main() {
	http.HandleFunc("/v1/chat/completions", func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		_ = r.Body.Close()
		mode := r.Header.Get("x-fixture-case")
		body := []byte(`{"model":"fixture","usage":{"prompt_tokens":10,"completion_tokens":15,"total_tokens":25}}`)
		contentType := "application/json"
		switch mode {
		case "pretty-json":
			body = []byte(`{
  "model": "fixture",
  "usage": {
    "prompt_tokens": 20,

    "completion_tokens": 30,
    "total_tokens": 50
  }
}`)
		case "sse":
			contentType = "text/event-stream"
			body = []byte("data: {\"choices\":[{\"delta\":{\"content\":\"hello\"}}]}\n\ndata: {\"usage\":{\"prompt_tokens\":10,\"completion_tokens\":15,\"total_tokens\":25}}\n\ndata: [DONE]\n\n")
		case "large-json":
			body = []byte(`{"content":"` + strings.Repeat("x", 2*1024*1024) + `","usage":{"prompt_tokens":10,"completion_tokens":15,"total_tokens":25}}`)
		}
		w.Header().Set("content-type", contentType)
		w.Header().Set("content-length", strconv.Itoa(len(body)))
		w.WriteHeader(http.StatusOK)
		if mode == "usage-key" {
			split := bytes.Index(body, []byte(`"usage"`)) + 4
			_, _ = w.Write(body[:split])
			w.(http.Flusher).Flush()
			time.Sleep(200 * time.Millisecond)
			_, _ = w.Write(body[split:])
			log.Printf("case=%s observation=%s writes=%d,%d pause=200ms", mode, r.Header.Get("x-observation-id"), split, len(body)-split)
		} else {
			_, _ = w.Write(body)
			log.Printf("case=%s observation=%s writes=%d", mode, r.Header.Get("x-observation-id"), len(body))
		}
	})
	log.Fatal(http.ListenAndServe(":9090", nil))
}
