#!/usr/bin/env python3
"""Compare the pure-Xu LLM engine against official llama.cpp on a real Qwen2.5 GGUF model.

Checks tokenizer parity and greedy-generation agreement, then benchmarks prefill (pp32/pp64),
decode (tg32), load time, peak memory, and deployment footprint on CPU.

Example:
  python3 scripts/bench_vs_llamacpp.py --compiler build/tensor-gemm/xu \
      --model ~/.cache/xu-llm-bench/qwen2.5-0.5b-instruct-q4_0.gguf
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tempfile

from test_tensor_fusion import build

PROMPTS = [
    "The capital of France is",
    "def fibonacci(n):",
    "Water boils at a temperature of",
]
SYSTEM_PREFIXES = ("/usr/lib/", "/System/")


def sh(cmd, check=True, stdin=subprocess.DEVNULL):
    p = subprocess.run([str(c) for c in cmd], stdin=stdin, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(map(str, cmd))}\n{p.stderr[-2000:]}")
    return p


def timed(cmd):
    """Run under /usr/bin/time -l and return (stdout, stderr, peak_bytes)."""
    p = sh(["/usr/bin/time", "-l", *cmd])
    m = re.search(r"(\d+)\s+peak memory footprint", p.stderr)
    return p.stdout, p.stderr, int(m.group(1)) if m else 0


def parse_kv(text):
    out = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out.setdefault(k, v)
    return out


def tool(name):
    path = shutil.which(name)
    if path is None:
        raise SystemExit(f"{name} not found on PATH (install with: brew install llama.cpp)")
    return Path(path)


def non_system_deps(binary):
    lines = sh(["otool", "-L", binary]).stdout.splitlines()[1:]
    deps = [l.strip().split(" ")[0] for l in lines if l.strip()]
    return [d for d in deps if not d.startswith(SYSTEM_PREFIXES)]


def llama_runtime_files(exe):
    """Resolve the llama.cpp executable plus its Homebrew dylibs and dynamically loaded ggml backends."""
    files = {Path(exe).resolve()}
    real = Path(exe).resolve()
    cellar_lib = real.parent.parent / "lib"
    for pat_dir in (cellar_lib,):
        if pat_dir.is_dir():
            for f in pat_dir.glob("*.dylib"):
                files.add(f.resolve())
    ggml_prefix = Path("/opt/homebrew/opt/ggml")
    for sub, pat in (("lib", "*.dylib"), ("libexec", "*.so")):
        d = ggml_prefix / sub
        if d.is_dir():
            for f in d.glob(pat):
                files.add(f.resolve())
    return sorted(files)


def common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def llama_tokenize(model, text):
    out = sh([tool("llama-tokenize"), "-m", model, "-p", text, "--ids", "--log-disable"]).stdout
    line = [l for l in out.splitlines() if l.strip().startswith("[")][-1]
    return json.loads(line)


def llama_generate(model, prompt, n, ctx):
    stdout, stderr, peak = timed([tool("llama-completion"), "-m", model, "-p", prompt, "-n", n,
                                  "--temp", "0", "--top-k", "1", "-ngl", "0", "-dev", "none", "-t", "1",
                                  "-c", ctx, "-no-cnv", "--no-display-prompt", "--seed", "1"])
    m = re.search(r"load time =\s*([\d.]+) ms", stderr)
    return stdout.rstrip("\n"), float(m.group(1)) if m else -1.0, peak


def xu_generate(exe, model, prompt_arg, n, ctx):
    stdout, _, peak = timed([exe, "generate", model, prompt_arg, n, "0", "1", "--ctx", ctx])
    kv = parse_kv(stdout)
    # generated_text may span several lines (e.g. newline tokens); take everything up to kv_free_after.
    m = re.search(r"^generated_text:(.*?)\nkv_free_after:", stdout, re.S | re.M)
    if m:
        kv["generated_text"] = m.group(1)
    ids = [int(t) for t in kv["generated_ids"].split(",") if t]
    return kv, ids, peak


def check_generation(model, exes, n_gen, ctx):
    print("\n## Greedy generation parity (CPU, 1 thread, temp=0)\n")
    rows = []
    load = {"llama.cpp": [], "xu-strict": [], "xu-fast": []}
    peak = {"llama.cpp": 0, "xu-strict": 0, "xu-fast": 0}
    for prompt in PROMPTS:
        ref_ids = llama_tokenize(model, prompt)
        l_text, l_load, l_peak = llama_generate(model, prompt, n_gen, ctx)
        load["llama.cpp"].append(l_load)
        peak["llama.cpp"] = max(peak["llama.cpp"], l_peak)
        full = llama_tokenize(model, prompt + l_text)
        l_ids = full[len(ref_ids):] if full[:len(ref_ids)] == ref_ids else []

        res = {}
        for name, exe in exes:
            kv, ids, x_peak = xu_generate(exe, model, "ids:" + ",".join(map(str, ref_ids)), n_gen, ctx)
            load[name].append(float(kv["load_ms"]))
            peak[name] = max(peak[name], x_peak)
            res[name] = (kv["generated_text"], ids)
        kv_txt, _, _ = xu_generate(exes[1][1], model, prompt, n_gen, ctx)
        tok_ok = kv_txt["prompt_ids"] == ",".join(map(str, ref_ids))

        s_text, s_ids = res["xu-strict"]
        f_text, f_ids = res["xu-fast"]
        rows.append((prompt, tok_ok, len(ref_ids), common_prefix(s_ids, l_ids), common_prefix(s_ids, f_ids),
                     len(s_ids), l_text, s_text, f_text))
        assert tok_ok, f"tokenizer mismatch for {prompt!r}: xu={kv_txt['prompt_ids']} llama={ref_ids}"

    print("| prompt | tokenizer == llama.cpp | prompt tokens | strict vs llama.cpp (same leading tokens) | strict vs fast |")
    print("| --- | --- | ---: | ---: | ---: |")
    for prompt, tok_ok, plen, sl, sf, n, *_ in rows:
        print(f"| `{prompt}` | {'yes' if tok_ok else 'NO'} | {plen} | {sl}/{n} | {sf}/{n} |")
    print()
    for prompt, *_, l_text, s_text, f_text in rows:
        print(f"- `{prompt}`")
        print(f"  - llama.cpp : {l_text!r}")
        print(f"  - xu-strict : {s_text!r}")
        print(f"  - xu-fast   : {f_text!r}")
    return {k: statistics.median(v) for k, v in load.items()}, peak


def xu_bench(exe, model, prompt_len, steps, ctx, reps):
    pp, tg, p50, p99, ttft = [], [], [], [], []
    for _ in range(reps):
        st = parse_kv(sh([exe, "bench", model, steps, "single", prompt_len, "--ctx", ctx]).stdout)
        st = {k: int(v) for k, v in st.items() if k != "tokens"}
        pp.append(st["prefill_tokens"] * 1e9 / st["prefill_ns"])
        tg.append(st["decode_steps"] * 1e9 / st["decode_total_ns"])
        p50.append(st["decode_p50_ns"] / 1e6)
        p99.append(st["decode_p99_ns"] / 1e6)
        ttft.append(st["ttft_ns"] / 1e6)
    med = statistics.median
    return {"pp": med(pp), "tg": med(tg), "p50": med(p50), "p99": med(p99), "ttft": med(ttft)}


def llama_bench(model, threads, reps):
    out = sh([tool("llama-bench"), "-m", model, "-ngl", "0", "-dev", "none", "-t", threads,
              "-p", "32,64", "-n", "32", "-r", reps, "-o", "json"]).stdout
    data = json.loads(out[out.index("["):])
    res = {}
    backend = data[0].get("backends", "") if data else ""
    for e in data:
        key = f"pp{e['n_prompt']}" if e["n_prompt"] > 0 else f"tg{e['n_gen']}"
        res[key] = (e["avg_ts"], e["stddev_ts"])
    return res, backend


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--ctx", default="512")
    parser.add_argument("--gen", default="24")
    parser.add_argument("--reps", default=3, type=int)
    parser.add_argument("--ref-threads", default="4", help="extra multi-thread llama.cpp reference")
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    model = args.model.expanduser().resolve()
    root = Path(__file__).resolve().parents[1]
    source = root / "examples/llm_engine/main.xu"

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        env = dict(os.environ, XU_STDLIB_ROOT=str(root / "src"), XU_CACHE=str(work / "cache"),
                   XU_MIR_BORROW_GATE="1", XU_TASK_POLL="0")
        exes = []
        for name, fast in (("xu-strict", "0"), ("xu-fast", "1")):
            exe = work / name
            build(compiler, dict(env, XU_TENSOR_FUSION="1", XU_TENSOR_FAST_MATH=fast), source, exe)
            exes.append((name, exe))

        print(f"# Pure-Xu vs llama.cpp on {model.name} ({model.stat().st_size / 2**20:.1f} MiB)")
        print(f"\nllama.cpp: {sh([tool('llama-bench'), '--version']).stderr.strip().splitlines()[-1]}")

        load, peak = check_generation(model, exes, args.gen, args.ctx)

        print("\n## Throughput (CPU only, median of", args.reps, "runs)\n")
        xu = {}
        for name, exe in exes:
            xu[name] = {pl: xu_bench(exe, model, str(pl), "32", args.ctx, args.reps) for pl in (32, 64, 1)}
        ll1, backend = llama_bench(model, "1", str(args.reps))
        llN, _ = llama_bench(model, args.ref_threads, str(args.reps))

        print("| engine | threads | pp32 tok/s | pp64 tok/s | tg32 tok/s | decode P50 / P99 ms | TTFT pp32 ms |")
        print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for name, _ in exes:
            r = xu[name]
            print(f"| {name} | 1 | {r[32]['pp']:.1f} | {r[64]['pp']:.1f} | {r[1]['tg']:.1f} | "
                  f"{r[1]['p50']:.2f} / {r[1]['p99']:.2f} | {r[32]['ttft']:.1f} |")
        for label, res, th in (("llama.cpp", ll1, "1"), ("llama.cpp", llN, args.ref_threads)):
            print(f"| {label} ({backend}) | {th} | {res['pp32'][0]:.1f} ± {res['pp32'][1]:.1f} | "
                  f"{res['pp64'][0]:.1f} ± {res['pp64'][1]:.1f} | {res['tg32'][0]:.1f} ± {res['tg32'][1]:.1f} | - | - |")
        print()
        for name, _ in exes:
            print(f"- {name} / llama.cpp(1 thread): pp32 {xu[name][32]['pp'] / ll1['pp32'][0]:.2f}x | "
                  f"pp64 {xu[name][64]['pp'] / ll1['pp64'][0]:.2f}x | tg32 {xu[name][1]['tg'] / ll1['tg32'][0]:.2f}x")

        print("\n## Load time, memory, deployment footprint\n")
        l_exe = tool("llama-completion")
        l_files = llama_runtime_files(l_exe)
        l_exe_kib = l_exe.resolve().stat().st_size / 1024.0
        l_total_mib = sum(f.stat().st_size for f in l_files) / 2**20
        print("| engine | load ms (median) | peak memory MiB | executable | runtime total | non-system dylib deps |")
        print("| --- | ---: | ---: | ---: | ---: | ---: |")
        for name, exe in exes:
            kib = exe.stat().st_size / 1024.0
            deps = non_system_deps(exe)
            print(f"| {name} | {load[name]:.0f} | {peak[name] / 2**20:.0f} | {kib:.1f} KiB | {kib:.1f} KiB | {len(deps)} |")
        print(f"| llama.cpp (llama-completion) | {load['llama.cpp']:.0f} | {peak['llama.cpp'] / 2**20:.0f} | "
              f"{l_exe_kib:.1f} KiB | {l_total_mib:.1f} MiB ({len(l_files)} files) | {len(non_system_deps(l_exe))} |")


if __name__ == "__main__":
    main()
