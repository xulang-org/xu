import os
import subprocess
import sys
import tempfile

def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    compiler = os.path.join(root, "bin", "xu.exe")
    env = os.environ.copy()
    env["XU_STDLIB_ROOT"] = os.path.join(root, "src")
    env["XU_ROOT"] = root

    xu_code = """@main

#net/http2

fn test_indexed_status() {
    $blk := ""
    blk.push_byte(136) // 0x88 = index 8 (:status 200)
    st := http2.parse_status(blk)
    if st != 200 {
        println("FAILED: expected 200 indexed, got " + str(st))
        <<< 1
    }
}

fn test_plain_literal_status() {
    $blk := ""
    blk.push_byte(8) // index 8 for name :status
    blk.push_byte(3) // len 3, plain ascii
    blk = blk + "200"
    st := http2.parse_status(blk)
    if st != 200 {
        println("FAILED: expected 200 plain literal, got " + str(st))
        <<< 1
    }
}

fn test_huffman_status_302() {
    $blk := ""
    blk.push_byte(8)   // index 8 for name :status
    blk.push_byte(130) // 0x80 | 2
    blk.push_byte(100) // 0x64
    blk.push_byte(2)   // 0x02
    st := http2.parse_status(blk)
    if st != 302 {
        println("FAILED: expected 302 huffman, got " + str(st))
        <<< 1
    }
}

fn test_huffman_status_404() {
    $blk := ""
    blk.push_byte(8)   // index 8 for name :status
    blk.push_byte(131) // 0x80 | 3
    blk.push_byte(104) // 0x68
    blk.push_byte(13)  // 0x0d
    blk.push_byte(127) // 0x7f
    st := http2.parse_status(blk)
    if st != 404 {
        println("FAILED: expected 404 huffman, got " + str(st))
        <<< 1
    }
}

fn test_huffman_status_500() {
    // '5' = 011011 (6 bits)
    // '0' = 00000 (5 bits)
    // '0' = 00000 (5 bits)
    // total 16 bits: 0110 1100 0000 0000 = 0x6c 0x00
    $blk := ""
    blk.push_byte(8)   // index 8 for name :status
    blk.push_byte(130) // 0x80 | 2
    blk.push_byte(108) // 0x6c
    blk.push_byte(0)   // 0x00
    st := http2.parse_status(blk)
    if st != 500 {
        println("FAILED: expected 500 huffman, got " + str(st))
        <<< 1
    }
}

fn test_huffman_invalid_padding() {
    $blk := ""
    blk.push_byte(8)
    blk.push_byte(131)
    blk.push_byte(104)
    blk.push_byte(13)
    blk.push_byte(0) // invalid padding: zero instead of ones
    st := http2.parse_status(blk)
    if st != 0 {
        println("FAILED: expected invalid padding to fail (0), got " + str(st))
        <<< 1
    }
}

fn test_huffman_truncated() {
    $blk := ""
    blk.push_byte(8)
    blk.push_byte(135) // claims 5 bytes, but only gives 2
    blk.push_byte(100)
    blk.push_byte(2)
    st := http2.parse_status(blk)
    if st != 0 {
        println("FAILED: expected truncated string to fail (0), got " + str(st))
        <<< 1
    }
}

fn main() {
    test_indexed_status()
    test_plain_literal_status()
    test_huffman_status_302()
    test_huffman_status_404()
    test_huffman_status_500()
    test_huffman_invalid_padding()
    test_huffman_truncated()
    println("HTTP2_HPACK_HUFFMAN_OK")
}
"""

    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "test_hpack.xu")
        exe = os.path.join(td, "test_hpack.exe")
        with open(src, "w", encoding="utf-8") as f:
            f.write(xu_code)

        build_cmd = [compiler, "build", "-o", exe, src]
        res = subprocess.run(build_cmd, capture_output=True, text=True, env=env)
        if res.returncode != 0:
            print(f"Build failed:\n{res.stderr}\n{res.stdout}")
            sys.exit(1)

        run_res = subprocess.run([exe], capture_output=True, text=True, env=env)
        if run_res.returncode != 0:
            print(f"Run failed ({run_res.returncode}):\n{run_res.stderr}\n{run_res.stdout}")
            sys.exit(1)

        if "HTTP2_HPACK_HUFFMAN_OK" not in run_res.stdout:
            print(f"Unexpected output:\n{run_res.stdout}")
            sys.exit(1)

        print("[PASS] HTTP/2 HPACK Huffman decode & validation passed!")

if __name__ == "__main__":
    main()
