// Vector generator for the encoding_binary fixture.
//
//   cd tests/fixtures/encoding_binary && go run gen.go > expected.txt
//
// Calls Go `encoding/binary` for the put/get round-trips and byte-order
// vectors. The out-of-bounds lines at the end mirror the Xu fixture's
// Result semantics (Go's Put*/Uint* panic on out-of-range instead of
// returning an error, so those expected lines are printed literally).
package main

import (
	"encoding/binary"
	"fmt"
)

func hexBytes(b []byte) string {
	s := ""
	for i, by := range b {
		if i > 0 {
			s += " "
		}
		s += fmt.Sprintf("%02x", by)
	}
	return s
}

func main() {
	le := binary.LittleEndian
	be := binary.BigEndian

	u16s := []uint16{0x0000, 0x0001, 0x00ff, 0x0102, 0xffff}
	u32s := []uint32{0x00000000, 0x01020304, 0xffffffff}
	u64s := []uint64{
		0x0000000000000000,
		0x0000000000000001,
		0x00000000000000ff,
		0x0000000000000102,
		0x0000000001020304,
		0x0102030405060708,
		0x8000000000000000, // INT64_MIN bit pattern
		0xffffffffffffffff, // all ones
	}

	for _, v := range u16s {
		b := make([]byte, 2)
		le.PutUint16(b, v)
		fmt.Printf("le u16 0x%x -> %s -> 0x%x\n", v, hexBytes(b), le.Uint16(b))
		be.PutUint16(b, v)
		fmt.Printf("be u16 0x%x -> %s -> 0x%x\n", v, hexBytes(b), be.Uint16(b))
	}
	for _, v := range u32s {
		b := make([]byte, 4)
		le.PutUint32(b, v)
		fmt.Printf("le u32 0x%x -> %s -> 0x%x\n", v, hexBytes(b), le.Uint32(b))
		be.PutUint32(b, v)
		fmt.Printf("be u32 0x%x -> %s -> 0x%x\n", v, hexBytes(b), be.Uint32(b))
	}
	for _, v := range u64s {
		b := make([]byte, 8)
		le.PutUint64(b, v)
		fmt.Printf("le u64 0x%x -> %s -> 0x%x\n", v, hexBytes(b), le.Uint64(b))
		be.PutUint64(b, v)
		fmt.Printf("be u64 0x%x -> %s -> 0x%x\n", v, hexBytes(b), be.Uint64(b))
	}

	// Out-of-bounds (mirrors Xu Result semantics; Go panics here).
	// An 8-byte buffer filled with 0xab; a failing put must leave it intact.
	fmt.Println("get u16 off=8 is_err=true")
	fmt.Println("get u16 off=-1 is_err=true")
	fmt.Println("get u64 off=1 is_err=true")
	fmt.Println("put u16 off=7 is_err=true")
	fmt.Println("buf=ab ab ab ab ab ab ab ab")
	fmt.Println("put u64 off=-1 is_err=true")
	fmt.Println("buf=ab ab ab ab ab ab ab ab")
}
