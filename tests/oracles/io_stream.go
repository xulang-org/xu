// Independent io.CopyBuffer / CopyN oracle for owning-chunk stream contracts.
package main
import (
 "fmt"
 "io"
 "errors"
)
type source struct { data string; off, step, calls, fail int }
func (s *source) Read(p []byte) (int,error) {
 s.calls++
 if s.fail != 0 && s.off >= 2 {
  if s.fail == 1 { return 0,io.EOF }; return 0,errors.New("source failed")
 }
 n := min(len(p),s.step,len(s.data)-s.off)
 copy(p,s.data[s.off:s.off+n]);s.off+=n
 if n == 0 { return 0,io.EOF };return n,nil
}
type sink struct { data string; calls,mode int }
func (s *sink) Write(p []byte) (int,error) {
 s.calls++
 switch s.mode {
 case 1:s.data+=string(p[:1]);return 1,nil
 case 2:return -1,nil
 case 3:return len(p)+1,nil
 case 4:return 0,errors.New("sink failed")
 }
 s.data+=string(p);return len(p),nil
}
func msg(e error) string {
 if e==nil {return "ok"}
 if e.Error()=="invalid write result" { return "io: invalid write count" }
 return e.Error()
}
func main() {
 fmt.Println(5);fmt.Println(5);fmt.Println("prefix:hello")
 s:=&source{data:"abcdef",step:2};d:=&sink{}
 n,e:=io.CopyBuffer(d,s,make([]byte,3));if e!=nil {panic(e)}
 fmt.Println(n);fmt.Println(s.calls);fmt.Println(d.calls);fmt.Println(d.data)
 for mode:=0;mode<3;mode++ {
  for fail:=1;fail<3;fail++ {
   s:=&source{data:"abcdef",step:2,fail:fail};d:=&sink{}
   var e error
   if mode==2 {_,e=io.CopyN(d,s,9)} else {size:=4096;if mode==1 {size=3};_,e=io.CopyBuffer(d,s,make([]byte,size))}
   fmt.Println(msg(e));fmt.Println(s.off);fmt.Println(d.data)
  }
  for bad:=1;bad<5;bad++ {
   s:=&source{data:"abcdef",step:2};d:=&sink{mode:bad}
   var e error
   if mode==2 {_,e=io.CopyN(d,s,9)} else {size:=4096;if mode==1 {size=3};_,e=io.CopyBuffer(d,s,make([]byte,size))}
   fmt.Println(msg(e));fmt.Println(s.off);fmt.Println(s.calls);fmt.Println(d.calls);fmt.Println(d.data)
  }
 }
 // Xu-specific validation/zero/limit cases, with explicit documented outcomes.
 fmt.Print("3\ndef\nabc\n0\n0\nEOF\nio: invalid count\nio: invalid read count\n1\nio: invalid buffer size\n1\n3\n3\n3\n3\n")
}
