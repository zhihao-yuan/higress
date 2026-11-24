package officiallogging
import("bytes";"encoding/json";"strings";"testing";"fmt")
// Analysis prototype: marshal a JSON string directly; preserve property bytes.
func direct(key,value string){b,_:=json.Marshal(value);proxywasm.SetProperty([]string{key},b[1:len(b)-1])}
func TestPropertyBytes(t *testing.T){for _,v:=range []string{"", "plain", "引号\"与\\反斜杠\n\r\t", "<script>&", string([]byte{0,1,31,255}), "\u2028\u2029",strings.Repeat("data: {\"delta\":\"你好\"}\n\n",4096)} {setPropertyWithMarshal("k",v);want:=append([]byte{},output...);direct("k",v);if !bytes.Equal(want,output){t.Fatalf("property changed for %q: %q != %q",v,want,output)}}}
func BenchmarkProperty(b *testing.B){for _,size:=range []int{256,4096,65536}{for _,kind:=range []string{"ASCII","SSE"}{v:=strings.Repeat("x",size);if kind=="SSE" {seed:="data: {\"delta\":\"你好\"}\n\n";v=strings.Repeat(seed,(size+len(seed)-1)/len(seed))[:size]};for _,m:=range []struct{name string;fn func(string,string)}{{"original",setPropertyWithMarshal},{"direct",direct}} {b.Run(fmt.Sprintf("%s/%d/%s",kind,size,m.name),func(b *testing.B){b.ReportAllocs();for i:=0;i<b.N;i++{m.fn("test",v)}})}}}}
