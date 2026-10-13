// Vector generator for the math_bits fixture.
//
//   cd tests/fixtures/math_bits && go run gen.go > expected.txt
//
// Calls Go `math/bits` on the same vectors the Xu fixture exercises and
// prints one value per line. The Xu fixture mirrors the exact same order
// and format (`0x%x` for u64 bit patterns, decimal for counts/lengths).
package main

import (
	"fmt"
	"math/bits"
)

func main() {
	vals := []uint64{
		0x0000000000000000,
		0x0000000000000001,
		0x8000000000000000, // 1<<63
		0xffffffffffffffff, // all ones
		0x0102030405060708,
		0x00ff00ff00ff00ff,
		0x123456789abcdef0,
		0x0f0f0f0f0f0f0f0f,
		0xaaaaaaaaaaaaaaaa,
		0x5555555555555555,
	}
	for _, v := range vals {
		fmt.Printf("len(0x%x)=%d\n", v, bits.Len64(v))
		fmt.Printf("lz(0x%x)=%d\n", v, bits.LeadingZeros64(v))
		fmt.Printf("tz(0x%x)=%d\n", v, bits.TrailingZeros64(v))
		fmt.Printf("oc(0x%x)=%d\n", v, bits.OnesCount64(v))
		fmt.Printf("rev(0x%x)=0x%x\n", v, bits.Reverse64(v))
		fmt.Printf("revb(0x%x)=0x%x\n", v, bits.ReverseBytes64(v))
	}
	rots := []uint64{
		0x0102030405060708,
		0x8000000000000000,
		0xffffffffffffffff,
	}
	for _, x := range rots {
		for _, k := range []int{0, 1, 63, 64, 65} {
			// Go has no RotateRight64; rotate right by k == rotate left by -k.
			fmt.Printf("rol(0x%x,%d)=0x%x\n", x, k, bits.RotateLeft64(x, k))
			fmt.Printf("ror(0x%x,%d)=0x%x\n", x, k, bits.RotateLeft64(x, -k))
		}
	}
}
