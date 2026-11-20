import os
import sys
import subprocess
import tempfile

def main():
    xu_bin = os.path.abspath("bin/xu.exe")
    if not os.path.exists(xu_bin):
        print(f"Error: {xu_bin} not found", file=sys.stderr)
        return 1

    os.environ["XU_STDLIB_ROOT"] = os.path.abspath("src")
    os.environ["XU_ROOT"] = os.path.abspath(".")

    test_src = """@main
#compress/zstd

fn test_roundtrip(size int) {
    $s := ""
    $chunk := "0123456789abcdef"
    $rem := size
    while rem >= 16 {
        s = s + chunk
        rem = rem - 16
    }
    for i in 0:rem {
        s = s + "z"
    }

    comp := zstd.compress(&s)
    decomp := zstd.decompress(&comp) or (err) {
        println("ERROR: decompress failed for size " + str(size) + ": " + err.msg())
        <<< 1
    }
    if decomp.len != s.len || decomp != s {
        println("ERROR: roundtrip mismatch for size " + str(size))
        <<< 1
    }
}

fn test_fhd_bytes() {
    // 0 bytes: FHD=32 (0x20)
    e0 := ""
    c0 := zstd.compress(&e0)
    if (c0[4] & 255) != 32 {
        println("ERROR: size 0 FHD expected 32, got " + str(c0[4] & 255))
        <<< 1
    }

    // 255 bytes: FCS_Field_Size=1 (FCS_Flag=0, Single_Segment=1) -> FHD=32 (0x20)
    $s255 := ""
    for i in 0:255 { s255 = s255 + "a" }
    c255 := zstd.compress(&s255)
    fhd255 := c255[4] & 255
    if fhd255 != 32 {
        println("ERROR: size 255 FHD expected 32, got " + str(fhd255))
        <<< 1
    }

    // 256 bytes: FCS_Field_Size=2 (FCS_Flag=1, Single_Segment=1) -> FHD = (1<<6)|(1<<5) = 96 (0x60)
    $s256 := ""
    for i in 0:256 { s256 = s256 + "a" }
    c256 := zstd.compress(&s256)
    fhd256 := c256[4] & 255
    if fhd256 != 96 {
        println("ERROR: size 256 FHD expected 96, got " + str(fhd256))
        <<< 1
    }
    // FCS stored for 256 is 256 - 256 = 0 (2 bytes little-endian: 0, 0)
    if (c256[5] & 255) != 0 || (c256[6] & 255) != 0 {
        println("ERROR: size 256 FCS value expected 0, 0")
        <<< 1
    }

    // 65791 bytes: FCS_Field_Size=2 -> FHD=96
    $s65791 := ""
    $chunk := ""
    for k in 0:1000 { chunk = chunk + "x" }
    for k in 0:65 { s65791 = s65791 + chunk }
    for k in 0:791 { s65791 = s65791 + "x" }
    if s65791.len != 65791 {
        println("ERROR: expected s65791 len 65791, got " + str(s65791.len))
        <<< 1
    }
    c65791 := zstd.compress(&s65791)
    fhd65791 := c65791[4] & 255
    if fhd65791 != 96 {
        println("ERROR: size 65791 FHD expected 96, got " + str(fhd65791))
        <<< 1
    }

    // 65792 bytes: FCS_Field_Size=4 (FCS_Flag=2, Single_Segment=1) -> FHD = (2<<6)|(1<<5) = 160 (0xA0)
    s65792 := s65791 + "y"
    c65792 := zstd.compress(&s65792)
    fhd65792 := c65792[4] & 255
    if fhd65792 != 160 {
        println("ERROR: size 65792 FHD expected 160, got " + str(fhd65792))
        <<< 1
    }
}

fn check_decompress(data &string) bool {
    _ := zstd.decompress(data) or (err) {
        << false
    }
    << true
}

fn test_truncated() {
    $s255 := ""
    for i in 0:255 { s255 = s255 + "a" }
    c255 := zstd.compress(&s255)

    // Truncated to 4 bytes (only magic)
    trunc4 := c255[0:4]
    if check_decompress(&trunc4) {
        println("ERROR: truncated 4 did not throw!")
        <<< 1
    }

    // Truncated to 6 bytes (FCS but no block)
    trunc6 := c255[0:6]
    if check_decompress(&trunc6) {
        println("ERROR: truncated 6 did not throw!")
        <<< 1
    }

    // Truncated block payload (header says 255 bytes, but cut off at 20 bytes)
    trunc20 := c255[0:20]
    if check_decompress(&trunc20) {
        println("ERROR: truncated 20 did not throw!")
        <<< 1
    }
}

fn test_rle_decoding() {
    // Construct a valid Zstd frame containing an RLE block manually:
    // Magic: 0x28, 0xb5, 0x2f, 0xfd (4 bytes)
    // FHD: 0x20 (Single_Segment=1, FCS_Field_Size=0 -> 1 byte FCS)
    // FCS: 10 bytes -> 10
    // Block Header:
    //   Last_Block = 1 (bit 0 = 1)
    //   Block_Type = 1 (RLE, bits 2-1 = 1 << 1 = 2)
    //   Block_Size = 10 (bits 23-3 = 10 << 3 = 80)
    //   Header = 1 | 2 | 80 = 83 (0x53)
    //   3 bytes: 83, 0, 0
    // Block Content:
    //   1 byte: 65 ('A')
    $frame := []int{}
    frame.push(40)
    frame.push(181)
    frame.push(47)
    frame.push(253)
    frame.push(32) // FHD
    frame.push(10) // FCS = 10
    frame.push(83) // 1 | (1<<1) | (10<<3) = 83
    frame.push(0)
    frame.push(0)
    frame.push(65) // 'A'

    rle_str := string_from_bytes(frame)
    decoded := zstd.decompress(&rle_str) or (err) {
        println("ERROR: RLE decompress threw: " + err.msg())
        <<< 1
    }
    if decoded != "AAAAAAAAAA" {
        println("ERROR: RLE decompress mismatch, got: " + decoded)
        <<< 1
    }
    println("OK: RLE block decompress passed")
}

fn main() {
    println("Testing FHD header encoding...")
    test_fhd_bytes()

    println("Testing roundtrips (0, 255, 256, 257, 1000, 65791, 65792)...")
    test_roundtrip(0)
    test_roundtrip(255)
    test_roundtrip(256)
    test_roundtrip(257)
    test_roundtrip(1000)
    test_roundtrip(65791)
    test_roundtrip(65792)

    println("Testing multi-block (140000 bytes)...")
    test_roundtrip(140000)

    println("Testing RLE decoding...")
    test_rle_decoding()

    println("Testing truncation errors...")
    test_truncated()

    println("ALL_ZSTD_STEP_TESTS_PASSED")
}
"""
    scratch_path = os.path.abspath("scratch_zstd_test.xu")
    try:
        with open(scratch_path, "w", encoding="utf-8") as f:
            f.write(test_src)
        
        # Build first for fast execution
        exe_path = os.path.abspath("scratch_zstd_test.exe")
        bld = subprocess.run([xu_bin, "build", "-o", exe_path, scratch_path], capture_output=True, text=True)
        if bld.returncode != 0:
            print("BUILD FAILED:\n" + bld.stderr)
            return bld.returncode
            
        proc = subprocess.run([exe_path], capture_output=True, text=True)
        print("STDOUT:\n" + proc.stdout)
        print("STDERR:\n" + proc.stderr)
        
        if os.path.exists(exe_path):
            os.remove(exe_path)
            
        if proc.returncode != 0 or "ALL_ZSTD_STEP_TESTS_PASSED" not in proc.stdout:
            return 1

        # Also test with system bsdtar (libzstd 1.5.7) as mentioned in audit plan:
        # "Zstd 另用系统 bsdtar 3.8.9 的 libzstd 1.5.7 读取 Xu 帧。"
        import tarfile
        for size in [0, 255, 256, 257, 1024, 65791, 65792]:
            with tempfile.TemporaryDirectory() as td:
                tar_path = os.path.join(td, "test.tar")
                sample_data = b"x" * size
                with tarfile.open(tar_path, "w") as tar:
                    ti = tarfile.TarInfo("sample.txt")
                    ti.size = len(sample_data)
                    import io
                    tar.addfile(ti, io.BytesIO(sample_data))
                
                with open(tar_path, "rb") as f:
                    raw_tar = f.read()

                # Compress raw_tar using Xu
                xu_comp_src = f"""@main
#compress/zstd
#os

fn main() {{
    data := os.read("{tar_path.replace('\\', '/')}") or (err) {{
        println("read failed: " + err.msg())
        <<< 1
    }}
    comp := zstd.compress(&data)
    _ := os.write("{tar_path.replace('\\', '/')}.zst", comp) or (err) {{
        println("write failed: " + err.msg())
        <<< 1
    }}
}}
"""
                comp_xu_path = os.path.join(td, "comp.xu")
                with open(comp_xu_path, "w", encoding="utf-8") as f:
                    f.write(xu_comp_src)
                
                env = os.environ.copy()
                env["XU_STDLIB_ROOT"] = os.path.abspath("src")
                res = subprocess.run([xu_bin, "run", comp_xu_path], capture_output=True, text=True, env=env)
                if res.returncode != 0:
                    print(f"ERROR: Xu compress failed for tar size {size}:\n{res.stderr}")
                    return 1
                
                zst_path = tar_path + ".zst"
                # Now verify system tar can read it
                tar_res = subprocess.run(["tar", "-tf", zst_path], capture_output=True, text=True)
                if tar_res.returncode != 0 or "sample.txt" not in tar_res.stdout:
                    print(f"ERROR: bsdtar rejected Xu zstd frame for size {size}:\n{tar_res.stderr}")
                    return 1
                print(f"OK: bsdtar successfully verified Xu zstd archive of size {size}")

        print("ALL_BSDTAR_ZSTD_VERIFICATIONS_PASSED")
        return 0
    finally:
        if os.path.exists(scratch_path):
            os.remove(scratch_path)

if __name__ == "__main__":
    sys.exit(main())
