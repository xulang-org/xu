// Independent Go standard-library oracle for the two Xu text fixtures.
// Run: go run tests/oracles/stdlib_text.go boundaries|space
package main

import (
	"bytes"
	"encoding/hex"
	"fmt"
	"os"
	"strings"
)

func dump(p []string) {
	fmt.Println(len(p))
	for _, s := range p {
		fmt.Println(hex.EncodeToString([]byte(s)))
	}
}
func dumpBytes(p [][]byte) {
	fmt.Println(len(p))
	for _, s := range p {
		fmt.Println(hex.EncodeToString(s))
	}
}
func main() {
	if os.Args[1] == "boundaries" {
		for _, b := range [][]byte{
			{},
			{97},
			{97, 98, 99},
			{228, 184, 173, 240, 159, 153, 130, 195, 169},
			{255, 254, 65, 192, 175},
			{228, 184},
			{239, 191, 189, 255, 255, 90},
			{97, 0, 98},
		} {
			s := string(b)
			fmt.Println(strings.Count(s, ""))
			dump(strings.Split(s, ""))
			dump(strings.SplitAfter(s, ""))
			for _, n := range []int{-1, 0, 1, 2, 4} {
				dump(strings.SplitN(s, "", n))
				dump(strings.SplitAfterN(s, "", n))
				fmt.Println(hex.EncodeToString([]byte(strings.Replace(s, "", "|", n))))
			}
			for _, r := range []string{"?", "", "🙂"} {
				fmt.Println(hex.EncodeToString([]byte(strings.ToValidUTF8(s, r))))
			}
			fmt.Println(bytes.Count(b, nil))
			dumpBytes(bytes.Split(b, nil))
			dumpBytes(bytes.SplitAfter(b, nil))
			for _, n := range []int{-1, 0, 1, 2, 4} {
				dumpBytes(bytes.SplitN(b, nil, n))
				dumpBytes(bytes.SplitAfterN(b, nil, n))
				fmt.Println(hex.EncodeToString(bytes.Replace(b, nil, []byte("|"), n)))
			}
			for _, r := range []string{"?", "", "🙂"} {
				fmt.Println(hex.EncodeToString(bytes.ToValidUTF8(b, []byte(r))))
			}
		}
	} else {
		for _, b := range [][]byte{
			{9, 65, 9, 66, 9},
			{10, 65, 10, 66, 10},
			{11, 65, 11, 66, 11},
			{12, 65, 12, 66, 12},
			{13, 65, 13, 66, 13},
			{32, 65, 32, 66, 32},
			{194, 133, 65, 194, 133, 66, 194, 133},
			{194, 160, 65, 194, 160, 66, 194, 160},
			{225, 154, 128, 65, 225, 154, 128, 66, 225, 154, 128},
			{226, 128, 128, 65, 226, 128, 128, 66, 226, 128, 128},
			{226, 128, 129, 65, 226, 128, 129, 66, 226, 128, 129},
			{226, 128, 130, 65, 226, 128, 130, 66, 226, 128, 130},
			{226, 128, 131, 65, 226, 128, 131, 66, 226, 128, 131},
			{226, 128, 132, 65, 226, 128, 132, 66, 226, 128, 132},
			{226, 128, 133, 65, 226, 128, 133, 66, 226, 128, 133},
			{226, 128, 134, 65, 226, 128, 134, 66, 226, 128, 134},
			{226, 128, 135, 65, 226, 128, 135, 66, 226, 128, 135},
			{226, 128, 136, 65, 226, 128, 136, 66, 226, 128, 136},
			{226, 128, 137, 65, 226, 128, 137, 66, 226, 128, 137},
			{226, 128, 138, 65, 226, 128, 138, 66, 226, 128, 138},
			{226, 128, 168, 65, 226, 128, 168, 66, 226, 128, 168},
			{226, 128, 169, 65, 226, 128, 169, 66, 226, 128, 169},
			{226, 128, 175, 65, 226, 128, 175, 66, 226, 128, 175},
			{226, 129, 159, 65, 226, 129, 159, 66, 226, 129, 159},
			{227, 128, 128, 65, 227, 128, 128, 66, 227, 128, 128},
			{},
			{9, 10, 11, 12, 13, 32, 194, 133, 194, 160, 225, 154, 128, 226, 128, 128, 226, 128, 129, 226, 128, 130, 226, 128, 131, 226, 128, 132, 226, 128, 133, 226, 128, 134, 226, 128, 135, 226, 128, 136, 226, 128, 137, 226, 128, 138, 226, 128, 168, 226, 128, 169, 226, 128, 175, 226, 129, 159, 227, 128, 128},
			{255, 32, 254},
			{194},
			{240, 159, 153, 130, 226, 128, 139, 228, 184, 173, 239, 187, 191},
		} {
			s := string(b)
			fmt.Println(hex.EncodeToString([]byte(strings.TrimSpace(s))))
			dump(strings.Fields(s))
			fmt.Println(hex.EncodeToString(bytes.TrimSpace(b)))
			dumpBytes(bytes.Fields(b))
		}
	}
}
