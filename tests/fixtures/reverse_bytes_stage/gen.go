package main

import (
    "fmt"
    "math/bits"
)

func main() {
    vals := []int64{0, 1, -1, -9223372036854775808, 0x0123456789abcdef}
    for _, x := range vals {
        u := uint64(x)
        fmt.Println(int64((u>>8&0x00ff00ff00ff00ff)|((u&0x00ff00ff00ff00ff)<<8)))
        fmt.Println(int64((u>>16&0x0000ffff0000ffff)|((u&0x0000ffff0000ffff)<<16)))
        fmt.Println(int64((u>>32&0x00000000ffffffff)|((u&0x00000000ffffffff)<<32)))
        fmt.Println(((x>>8)&0x00ff00ff00ff00fe)|((x&0x00ff00ff00ff00ff)<<8))
        fmt.Println(int64(bits.ReverseBytes64(u)))
    }
}
