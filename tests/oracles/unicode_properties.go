// Independent Unicode classification/title oracle using public Go APIs.
package main

import (
	"fmt"
	"os"
	"unicode"
)

func properties(r int64) (int, int64) {
	if r < 0 || r > unicode.MaxRune {
		return 0, r
	}
	bits := 0
	for i, f := range []func(rune) bool{
		unicode.IsDigit, unicode.IsLetter, unicode.IsSpace, unicode.IsUpper,
		unicode.IsLower, unicode.IsTitle, unicode.IsNumber, unicode.IsPunct,
		unicode.IsSymbol, unicode.IsPrint, unicode.IsGraphic, unicode.IsControl,
	} {
		if f(rune(r)) {
			bits |= 1 << i
		}
	}
	return bits, int64(unicode.ToTitle(rune(r)))
}
func show(r int64) { b, t := properties(r); fmt.Println(r); fmt.Println(b); fmt.Println(t) }
func main() {
	if os.Args[1] == "version" {
		fmt.Println(unicode.Version)
		return
	}
	if os.Args[1] == "edge" {
		for _, r := range []int64{-9223372036854775808, -2, -1, 0, 31, 32, 36, 43, 48, 65, 97, 127, 133, 160, 0xbd, 0x301, 0x1c4, 0x1c5, 0x1c6, 0x1c7, 0x1c8, 0x1c9, 0x1fbc, 0x2160, 0x200b, 0x2028, 0x2029, 0x1f642, 0x1d7ce, 0x1e4f0, 0x1c89, 0xd800, 0xdfff, 0x10ffff, 0x110000, 0x110002, 0x100000030, 9223372036854775807} {
			show(r)
		}
		return
	}
	for r := int64(-2); r <= unicode.MaxRune+3; r++ {
		b, t := properties(r)
		if b != 0 || t != r {
			fmt.Println(r)
			fmt.Println(b)
			fmt.Println(t)
		}
	}
}
