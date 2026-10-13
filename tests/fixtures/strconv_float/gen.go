package main

import (
	"errors"
	"fmt"
	"math"
	"strconv"
)

func ffAll(v float64) {
	for _, vb := range []byte{'f', 'e', 'g'} {
		for _, p := range []int{-1, 0, 2, 3, 6, 17} {
			fmt.Println(strconv.FormatFloat(v, vb, p, 64))
		}
	}
}

func main() {
	// ---- parse_float vectors (Go ParseFloat(s, 64)) ----
	parseInputs := []string{
		"0", "-0", "0.1", "0.5", "1.0", "3.14159", "1e21", "1e-5",
		"123456789.123", "0.000001", "9.223372036854776e18",
		"+Inf", "-Inf", "Inf", "NaN", "Infinity", "infinity", "nan", "NAN",
		"1e-999", // underflow -> 0, no error
		"abc", "", "1.2.3", "1e", "e5", "1e999", "1e400", "+", "--1",
		" 1", "+NaN", "1.5e", "1e+", "1e-", ".", "-", "1..2", "0.1.2",
	}
	for _, s := range parseInputs {
		v, err := strconv.ParseFloat(s, 64)
		if err != nil {
			if errors.Is(err, strconv.ErrRange) {
				fmt.Println("parse_float: value out of range")
			} else {
				fmt.Println("parse_float: invalid syntax")
			}
		} else {
			fmt.Println(strconv.FormatFloat(v, 'g', -1, 64))
		}
	}

	// ---- format_float vectors (Go FormatFloat(v, verb, prec, 64)) ----
	ffAll(0)
	ffAll(math.Copysign(0, -1))
	ffAll(0.1)
	ffAll(0.5)
	ffAll(1.0)
	ffAll(3.14159)
	ffAll(1e21)
	ffAll(1e-5)
	ffAll(123456789.123)
	ffAll(0.000001)
	ffAll(math.Inf(1))
	ffAll(math.Inf(-1))
	ffAll(math.NaN())
	ffAll(9.223372036854776e18)
	ffAll(0.3)
	ffAll(1.0 / 3.0)
	ffAll(2.5)
	ffAll(1.5)
	ffAll(0.05)
	ffAll(0.15)
	ffAll(0.25)
	ffAll(1.005)
	ffAll(2.675)
	ffAll(123.456)
	ffAll(6.02214076e23)
}
