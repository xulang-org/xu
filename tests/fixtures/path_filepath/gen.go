package main

// Reference generator kept for Unix-Go comparison of slash-only vectors.
// Xu filepath also accepts '\\' as a separator. Unix fixture output stays
// slash-based; Windows builds render public paths with the native '\\'
// separator, so mixed-separator cases are hand-maintained here.
//
//	cd tests/fixtures/path_filepath && go run gen.go

import (
	"fmt"
	"path/filepath"
)

func main() {
	fmt.Println(filepath.Clean("/a/b/../c/./d//"))
	fmt.Println(filepath.Clean("a/b/../../c"))
	fmt.Println(filepath.Clean(""))
	fmt.Println(filepath.Clean("/"))
	fmt.Println(filepath.Join("a", "b", "..", "c"))
}
