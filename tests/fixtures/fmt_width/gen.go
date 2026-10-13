package main

// Vector generator for the fmt_width fixture.
//
//   cd tests/fixtures/fmt_width && go run gen.go > expected.txt
//
// Mirrors main.xu line-for-line. print/printf/println in Xu go through the
// builtin println (always a trailing newline).

import "fmt"

func main() {
	fmt.Println(fmt.Sprintf("%5d", 42))
	fmt.Println(fmt.Sprintf("%-5d", 42))
	fmt.Println(fmt.Sprintf("%05d", 42))
	fmt.Println(fmt.Sprintf("%+d", 42))
	fmt.Println(fmt.Sprintf("% d", 42))
	fmt.Println(fmt.Sprintf("%+d", -7))
	fmt.Println(fmt.Sprintf("%#x", 255))
	fmt.Println(fmt.Sprintf("%#X", 255))
	fmt.Println(fmt.Sprintf("%#o", 8))
	fmt.Println(fmt.Sprintf("%#b", 3))
	fmt.Println(fmt.Sprintf("%#x", 0))
	fmt.Println(fmt.Sprintf("%.2f", 3.14159))
	fmt.Println(fmt.Sprintf("%8.2f", 3.14))
	fmt.Println(fmt.Sprintf("%-8.2f", 3.14))
	fmt.Println(fmt.Sprintf("%*d", 4, 7))
	fmt.Println(fmt.Sprintf("%.*s", 2, "hello"))
	fmt.Println(fmt.Sprintf("%.3s", "hello"))
	fmt.Println(fmt.Sprintf("%5s", "hi"))
	fmt.Println(fmt.Sprintf("%-5s", "hi"))
	fmt.Println(fmt.Sprintf("%x", "ab"))
	fmt.Println(fmt.Sprintf("%X", "ab"))
	fmt.Println(fmt.Sprintf("%#x", "ab"))
	fmt.Println(fmt.Sprintf("% x", "ab"))
	fmt.Println(fmt.Sprintf("%q", "a\"b"))
	fmt.Println(fmt.Sprintf("%5.3d", 2))
	fmt.Println(fmt.Sprintf("%+05d", 42))
	fmt.Println(fmt.Sprintf("%#05x", 15))
	fmt.Println(fmt.Sprintf("%q", 97))
	fmt.Println(fmt.Sprintf("n=%d", 9))
	fmt.Println("A 1")
	fmt.Println("B=2")
	fmt.Println("C")
}
