// Independent oracle: invoke public Go APIs, never Xu's tables/helpers.
package main

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"unicode"
)

type vectors struct {
	Text, Cutsets []string
	Pairs         [][]string
}

func decode(s string) string {
	b, err := hex.DecodeString(s)
	if err != nil {
		panic(err)
	}
	return string(b)
}
func output(s string) { fmt.Println(hex.EncodeToString([]byte(s))) }
func fields(a []string) {
	fmt.Println(len(a))
	for _, s := range a {
		output(s)
	}
}
func separator(r rune) bool { return r == 0x4e2d || r == 0x1f642 || r == 0xfffd || r == 0 || r == ',' }
func main() {
	if os.Args[1] == "version" {
		fmt.Println(unicode.Version)
		return
	}
	if os.Args[1] == "case" {
		for r := rune(-2); r <= unicode.MaxRune+3; r++ {
			u, l, f := unicode.ToUpper(r), unicode.ToLower(r), unicode.SimpleFold(r)
			if u != r || l != r || f != r {
				fmt.Println(r)
				fmt.Println(u)
				fmt.Println(l)
				fmt.Println(f)
			}
		}
		return
	}
	var v vectors
	data, err := os.ReadFile("tests/data/stdlib_rune_vectors.json")
	if err != nil {
		panic(err)
	}
	if err = json.Unmarshal(data, &v); err != nil {
		panic(err)
	}
	for _, h := range v.Text {
		s := decode(h)
		b := []byte(s)
		output(strings.ToLower(s))
		output(strings.ToUpper(s))
		output(string(bytes.ToLower(b)))
		output(string(bytes.ToUpper(b)))
		fmt.Println(strings.IndexByte(s, 128))
		fmt.Println(strings.LastIndexByte(s, 128))
		fmt.Println(bytes.IndexByte(b, 128))
		fmt.Println(bytes.LastIndexByte(b, 128))
		mapped := append([]byte(nil), b...)
		for i := range mapped {
			mapped[i] &= 127
		}
		output(string(mapped))
		output(string(mapped))
		for _, cut := range v.Cutsets {
			c := decode(cut)
			fmt.Println(strings.IndexAny(s, c))
			fmt.Println(strings.LastIndexAny(s, c))
			fmt.Println(strings.ContainsAny(s, c))
			output(strings.TrimLeft(s, c))
			output(strings.TrimRight(s, c))
			output(strings.Trim(s, c))
			fmt.Println(bytes.IndexAny(b, c))
			fmt.Println(bytes.LastIndexAny(b, c))
			fmt.Println(bytes.ContainsAny(b, c))
			output(string(bytes.TrimLeft(b, c)))
			output(string(bytes.TrimRight(b, c)))
			output(string(bytes.Trim(b, c)))
		}
		fmt.Println(strings.IndexFunc(s, separator))
		fmt.Println(strings.LastIndexFunc(s, separator))
		fmt.Println(strings.ContainsFunc(s, separator))
		output(strings.TrimLeftFunc(s, separator))
		output(strings.TrimRightFunc(s, separator))
		output(strings.TrimFunc(s, separator))
		fields(strings.FieldsFunc(s, separator))
		fmt.Println(bytes.IndexFunc(b, separator))
		fmt.Println(bytes.LastIndexFunc(b, separator))
		fmt.Println(bytes.ContainsFunc(b, separator))
		output(string(bytes.TrimLeftFunc(b, separator)))
		output(string(bytes.TrimRightFunc(b, separator)))
		output(string(bytes.TrimFunc(b, separator)))
		a := bytes.FieldsFunc(b, separator)
		fmt.Println(len(a))
		for _, x := range a {
			output(string(x))
		}
		for _, r := range []rune{-1, 0, 0x4e2d, 0x1f642, 0xfffd, 0xd800, 0x110000} {
			fmt.Println(strings.IndexRune(s, r))
			fmt.Println(strings.ContainsRune(s, r))
			fmt.Println(bytes.IndexRune(b, r))
			fmt.Println(bytes.ContainsRune(b, r))
		}
	}
	for _, p := range v.Pairs {
		a, b := decode(p[0]), decode(p[1])
		fmt.Println(strings.EqualFold(a, b))
		fmt.Println(bytes.EqualFold([]byte(a), []byte(b)))
	}
}
