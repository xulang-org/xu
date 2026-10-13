package main

import (
    "fmt"
    "math/bits"
)

func main() {
    vals := []int64{0, 1, -1, -9223372036854775808, 0x0123456789abcdef}
    shifts := []int{-129, -65, -64, -63, -1, 0, 1, 63, 64, 65, 129}
    for _, x := range vals {
        acc := x
        for _, k := range shifts {
            fmt.Println(int64(bits.RotateLeft64(uint64(x), k)))
            fmt.Println(int64(bits.RotateLeft64(uint64(x), -k)))
            fmt.Println(int64(bits.RotateLeft64(uint64(x), k)))
            s := uint(k & 63)
            miss := x
            if s != 0 {
                miss = (x << s) | ((x >> (64 - s)) & ((int64(1) << s) - 2))
            }
            fmt.Println(miss)
            fmt.Println(int64(bits.RotateLeft64(uint64(x), -k)))
            rightMiss := x
            if s != 0 {
                rightMiss = ((x >> s) & ((int64(1) << (64 - s)) - 2)) | (x << (64 - s))
            }
            fmt.Println(rightMiss)
            acc = int64(bits.RotateLeft64(uint64(acc), k))
            fmt.Println(acc)
        }
    }
}
