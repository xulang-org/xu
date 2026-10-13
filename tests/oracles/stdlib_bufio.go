package main

import (
 "bufio"
 "bytes"
 "encoding/hex"
 "encoding/json"
 "fmt"
 "io"
 "os"
)
func main() {
 raw, err := os.ReadFile("tests/data/stdlib_bufio_vectors.json"); if err != nil { panic(err) }
 var v struct { Hex []string `json:"hex"`; Sizes []int `json:"sizes"` }
 if err = json.Unmarshal(raw, &v); err != nil { panic(err) }
 for _, size := range v.Sizes {
  for _, value := range v.Hex {
   fmt.Println(value); fmt.Println(size)
   data, err := hex.DecodeString(value); if err != nil { panic(err) }
   r := bufio.NewReaderSize(bytes.NewReader(data), size)
   for {
    ch, width, err := r.ReadRune(); if err == io.EOF { break }; if err != nil { panic(err) }
    fmt.Println(ch); fmt.Println(width)
    if err = r.UnreadRune(); err != nil { panic(err) }
    again, againWidth, err := r.ReadRune(); if err != nil { panic(err) }
    fmt.Println(ch == again && width == againWidth)
   }
   if r.UnreadRune() == nil { panic("unread after EOF succeeded") }
  }
 }
 r := bufio.NewReader(bytes.NewReader(nil))
 p, err := r.Peek(0); if err != nil { panic(err) }; fmt.Println(len(p))
 _, err = r.ReadByte(); if err != io.EOF { panic(err) }; fmt.Println("EOF")
 p, err = r.Peek(0); if err != nil { panic(err) }; fmt.Println(len(p))
 r = bufio.NewReader(bytes.NewBufferString("A")); r.ReadByte(); r.Peek(0)
 fmt.Println(r.UnreadByte() != nil)
 _, err = r.Peek(-1); fmt.Println(err != nil)
 for _, line := range []string{"a\r", "\r", "a\r\n", "a\n", "\r\n", "a\r\r", "\n"} {
  r = bufio.NewReader(bytes.NewBufferString(line)); line, _, err := r.ReadLine()
  if err != nil { panic(err) }; fmt.Println(hex.EncodeToString(line))
 }
 r = bufio.NewReaderSize(bytes.NewBufferString("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"), 16)
 r.Peek(15); r.Discard(13)
 line, err := r.ReadSlice('\n'); if err != bufio.ErrBufferFull { panic(err) }; fmt.Println(string(line))
 rest, err := r.ReadString('\n'); if err != io.EOF { panic(err) }; fmt.Println(rest)
 var dst bytes.Buffer
 w := bufio.NewWriterSize(&dst, 4)
 n, err := w.WriteString("ab"); if err != nil { panic(err) }; fmt.Println(n)
 n, err = w.WriteString("cdefghi"); if err != nil { panic(err) }; fmt.Println(n)
 if err = w.Flush(); err != nil { panic(err) }; fmt.Println(dst.String())
}
