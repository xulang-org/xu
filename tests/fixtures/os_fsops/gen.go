// Reference generator for the os_fsops fixture.
//
//   cd tests/fixtures/os_fsops && go run gen.go
//
// Runs the SAME fs sequence as main.xu with Go's os package and prints one
// boolean per line, line-for-line with main.xu's 17 printlns. Two shapes
// cannot align, which is why expected.txt is handwritten to Xu's actual
// output and this file is the independent Go cross-check:
//   1. Xu's L0 Result has no unwrap_err, so Err cases are asserted with
//      is_err() booleans; the Go side uses os.IsNotExist/os.IsExist.
//   2. Xu's `stat` reports the raw st_mode (S_IFDIR = 0x4000), whereas Go's
//      os.FileMode uses os.ModeDir = 1<<31. Both are "true" for a directory,
//      but the raw values differ, so main.xu checks the raw S_IFDIR bit.
package main

import (
	"fmt"
	"os"
	"path/filepath"
)

func main() {
	dir := "m35_tmp"
	dir2 := "m35_tmp2"
	clean := func() {
		os.Remove(filepath.Join(dir2, "f.txt"))
		os.Remove(dir2)
		os.Remove(filepath.Join(dir, "f.txt"))
		os.Remove(dir)
	}
	clean()

	// Mirrors main.xu's 17 printlns.
	fmt.Println(os.Mkdir(dir, 0o777) == nil)                     // 1  mkdir ok
	d, err := os.Stat(dir)
	fmt.Println(err == nil)                                      // 2  stat dir ok
	fmt.Println(d.IsDir())                                       // 3  is_dir
	fmt.Println(d.Mode()&os.ModeDir != 0)                        // 4  dir mode bit
	fmt.Println(os.WriteFile(filepath.Join(dir, "f.txt"), []byte("hello m35"), 0o644) == nil) // 5 write ok
	f, err := os.Stat(filepath.Join(dir, "f.txt"))
	fmt.Println(err == nil)                                      // 6  stat file ok
	fmt.Println(f.Size() == 9)                                   // 7  size == 9
	fmt.Println(f.IsDir() == false)                              // 8  is_dir == false
	fmt.Println(os.Rename(dir, dir2) == nil)                     // 9  rename ok
	_, err = os.Stat(filepath.Join(dir2, "f.txt"))
	fmt.Println(err == nil)                                      // 10 stat new ok
	_, err = os.Stat(dir)
	fmt.Println(os.IsNotExist(err))                              // 11 stat old is_err
	fmt.Println(os.Remove(filepath.Join(dir2, "f.txt")) == nil)  // 12 remove file ok
	fmt.Println(os.Remove(dir2) == nil)                          // 13 remove dir ok
	_, err = os.Stat(filepath.Join(dir2, "f.txt"))
	fmt.Println(os.IsNotExist(err))                              // 14 stat deleted is_err
	e := os.Mkdir(dir2, 0o777)
	fmt.Println(e == nil)                                        // 15 mkdir(2) ok
	e = os.Mkdir(dir2, 0o777)
	fmt.Println(e == nil)                                        // 16 mkdir existing ok (false)
	fmt.Println(os.IsExist(e))                                   // 17 mkdir existing is_err

	clean()
}
