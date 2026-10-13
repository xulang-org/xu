package main

// Vector generator for the fmt_verbs fixture.
//
//   cd tests/fixtures/fmt_verbs && go run gen.go > expected.txt
//
// Mirrors main.xu line-for-line. Success cases call Go fmt.Sprintf with the
// same arguments (Arg constructors map to Go int/string/bool/float64); the
// mismatch/missing lines print Go's real on-error marker text (which Xu's
// sprintf returns as its Err message); width/precision are formatted like Go.

import "fmt"

func main() {
	// ---- success ----
	fmt.Println(fmt.Sprintf("%d", 42))
	fmt.Println(fmt.Sprintf("%d", -7))
	fmt.Println(fmt.Sprintf("%d", 0))
	fmt.Println(fmt.Sprintf("%s", "hi"))
	fmt.Println(fmt.Sprintf("%s", ""))
	fmt.Println(fmt.Sprintf("%v", 42))
	fmt.Println(fmt.Sprintf("%v", "hi"))
	fmt.Println(fmt.Sprintf("%v", true))
	fmt.Println(fmt.Sprintf("%v", 3.14))
	fmt.Println(fmt.Sprintf("%t", true))
	fmt.Println(fmt.Sprintf("%t", false))
	fmt.Println(fmt.Sprintf("100%%"))
	fmt.Println(fmt.Sprintf("%%"))
	fmt.Println(fmt.Sprintf(""))
	fmt.Println(fmt.Sprintf("a%sb", "x"))
	fmt.Println(fmt.Sprintf("%s=%d", "n", 7))
	fmt.Println(fmt.Sprintf("%d %s %t %v", 1, "two", true, 2.5))
	fmt.Println(fmt.Sprintf("%d", 1, "x"))

	// ---- type/verb mismatch: Go on-error markers ----
	fmt.Println(fmt.Sprintf("%d", "x"))
	fmt.Println(fmt.Sprintf("%s", 7))
	fmt.Println(fmt.Sprintf("%t", 1))
	fmt.Println(fmt.Sprintf("%d", true))
	fmt.Println(fmt.Sprintf("%d", 3.14))
	fmt.Println(fmt.Sprintf("%s", false))

	// ---- missing argument ----
	fmt.Println(fmt.Sprintf("%d"))

	// ---- width/precision ----
	fmt.Println(fmt.Sprintf("%5d", 5))
	fmt.Println(fmt.Sprintf("%.2f", 3.14))
}
