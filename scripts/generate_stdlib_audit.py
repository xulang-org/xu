#!/usr/bin/env python3
"""Generate the stdlib coverage audit and prioritized implementation queue.

Static coverage and source markers are discovery aids, not semantic proof.
Run after generate_stdlib_matrix.py; --check detects stale reports/anchors.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from generate_stdlib_matrix import ROOT, build_matrix

GAPS = ROOT / "docs/audit/stdlib_gaps.json"
OUTPUT = ROOT / "docs/audit/STDLIB_AUDIT.md"
MARKER = re.compile(r"unsupported|not implemented|not available|TODO|stub|subset|子集|no.op|ASCII.only", re.I)


def source_link(path: str, line: int | None = None) -> str:
    # Relative links remain usable in GitHub-rendered audit documents.
    suffix = f"#L{line}" if line else ""
    return f"[{path}](../../{path}{suffix})"


def build_report() -> str:
    matrix = build_matrix()
    gaps = json.loads(GAPS.read_text(encoding="utf-8"))
    if gaps.get("schema") != "xu.stdlib-gaps.v1":
        raise ValueError("invalid stdlib gaps schema")
    packages = {p["package"]: p for p in matrix["packages"]}
    counts = matrix["counts"]
    items = gaps["items"]
    identifiers: set[str] = set()
    for item in items:
        if item["id"] in identifiers or item["priority"] not in {"P0", "P1", "P2", "P3"}:
            raise ValueError(f"invalid/duplicate gap: {item['id']}")
        identifiers.add(item["id"])
        if set(item["packages"]) - packages.keys():
            raise ValueError(f"unknown package in {item['id']}")
    lines = [
        "# 标准库现状盘点与分批补全", "",
        f"人工复核日期：{gaps['reviewed_at']}。由 `scripts/generate_stdlib_audit.py` 生成；任务源为 [stdlib_gaps.json](stdlib_gaps.json)。", "",
        "## 口径与结论", "",
        f"扫描全部 **{counts['packages']} 个可导入包**（{counts['stdlib_packages']} 个当前 inventory stdlib 分类、{counts['extension_packages']} 个扩展）、"
        f"**{counts['source_files']} 个源文件 / {counts['public_symbols']} 个公开声明**。公开声明包含方法及类型，不等于独立能力数。", "",
        "这是全目录静态盘点与重点 API 复核，不是逐 API 全量语义/安全审计。未登记问题的包仍为 inventory-only，不能据此声称完整。"
        "源码中的 subset/unsupported 只是待复核线索；合法的非法输入拒绝也会命中，不自动当作缺陷。", "",
        "旧测试证据没有源码/编译器指纹，现已拒绝套用到当前源码。新证据绑定编译器文件、包导入闭包、隐式 runtime 与 fixture 合同。"
        "PASS 只涵盖该次日志中实际执行的 fixture；包有 smoke 不代表全部导出方法可用。", "",
        "已实施批次及验证边界：[第一批 UTF-8/证据](STDLIB_BATCH1.md)、[第二批 HTTP/运行时依赖](STDLIB_BATCH2.md)、"
        "[第三批 select 唤醒与取消回收](STDLIB_BATCH3.md)、[第四批 Rune 与 Unicode 大小写](STDLIB_BATCH4.md)、[第五批 Unicode 分类与 titlecase](STDLIB_BATCH5.md)、[第六批流式复制与 gzip](STDLIB_BATCH6.md)、[第七批缓冲 I/O 边界](STDLIB_BATCH7.md)、[第八批通用缓冲包装](STDLIB_BATCH8.md)、[资源所有权第一批](RESOURCE_SAFETY_BATCH1.md)、[I/O 进度第二批](IO_PROGRESS_BATCH2.md)。执行批次是交付记录；下表是长期主题分组。", "",
        "## 已确认与分批安排", "",
        f"已登记 {len(items)} 项任务；"
        f"{sum(i['state'] == 'host-verified' for i in items)} 项完成本机验证，其余仍有待完成的依赖或验收。", "",
        "P0：错误完成度声明与取消后资源滞留；P1：基础语义、服务主链及无直接测试的新包；P2：高频扩展；P3：格式长尾。", "",
        "| 批次 | 主题 | 验收边界 |", "|---|---|---|",
        "| 1 | 证据可信度、UTF-8 文本基础 | 产品/对照编译器本机 fixture + 独立 Go oracle；不宣称发布绿 |",
        "| 2 | context、timer、HTTP 超时、进程取消、signal | 先完成最小 runtime adapter；取消/竞态/关闭/回收 |",
        "| 3 | Rune API、流式 I/O、FS、新包测试 | 独立向量与正向/边界/错误 fixture |",
        "| 4 | HTTP/2、poller、数据库、Windows 时区/管道 | 协议互操作、实际流控/取消、原生平台 |",
        "| 5 | X.509/TLS/私钥操作深化 | 支持矩阵、负向标准向量与安全合同 |",
        "| 6 | testing、regexp、序列化、模板及格式长尾 | 类型/复杂度/资源上限合同 |",
        "| 7 | 全量平台与发布收口 | native/compile-only/unsupported 分列，Gen3==Gen4 单独验收 |", "",
        "旧记录修正：`os/exec` 已有 start/wait 和 Unix stdin/stdout pipe；`filepath` 已有 glob/walk；"
        "`net/http2` 已有受限独立包；`unicode.is_space` 已支持 U+0085/U+2028/U+2029。后续项以实际实现深度为准。", "",
    ]
    for item in sorted(items, key=lambda i: (i["batch"], i["priority"], i["id"])):
        lines.extend([
            f"### {item['id']} · {item['priority']} · 批次 {item['batch']} · {item['api']}", "",
            f"包：{', '.join('`'+p+'`' for p in item['packages'])}。状态：`{item['state']}`。", "",
            item["gap"], "",
            f"依赖：{item['dependency']}。验收：{item['acceptance']}", "",
        ])
        references = []
        for ref in item["evidence"]:
            text = (ROOT / ref["file"]).read_text(encoding="utf-8")
            offset = text.find(ref["anchor"])
            if offset < 0:
                raise ValueError(f"stale evidence anchor in {item['id']}: {ref['file']}")
            references.append(source_link(ref["file"], text[:offset].count("\n") + 1))
        lines.extend(["源码依据：" + "、".join(references) + "。", ""])
    missing = [p["package"] for p in matrix["packages"] if not p["fixtures"]]
    lines.extend(["## 全包覆盖表", "",
                  f"无直接 import fixture 的包共 {len(missing)} 个：" + "、".join(f"`{p}`" for p in missing) + "。", "",
                  "fixture 只按显式 `#import` 关联；0 不等于没有间接测试。平台状态来自有指纹的日志；"
                  "`not-measured` 表示证据不足，不能推断代码不支持。完整符号、fixture 和哈希见 [stdlib_matrix.json](stdlib_matrix.json)。", "",
                  "| 包 | 公开声明 | 直接 fixture | 限制线索行数 | 当前日志语义 | macOS ARM64 | 其余 7 目标已测数 |",
                  "|---|---:|---:|---:|---|---|---:|"])
    for pkg in matrix["packages"]:
        directory = ROOT / "src" / pkg["package"]
        markers = sum(bool(MARKER.search(line)) for path in directory.glob("*.xu")
                      for line in path.read_text(encoding="utf-8").splitlines())
        platform = pkg["status"]["platform"]
        measured = sum(v != "not-measured" for t, v in platform.items() if t != "macos-arm64")
        lines.append(f"| {source_link('src/'+pkg['package']+'/mod.xu')} | {pkg['public_symbol_count']} | "
                     f"{len(pkg['fixtures'])} | {markers} | {pkg['status']['semantic']} | {platform['macos-arm64']} | {measured} |")
    lines.extend(["", "## 重放", "", "```sh",
                  "python3 scripts/generate_stdlib_matrix.py",
                  "python3 scripts/generate_stdlib_audit.py",
                  "python3 scripts/generate_stdlib_matrix.py --check",
                  "python3 scripts/generate_stdlib_audit.py --check",
                  "```", "",
                  "记录新证据前必须先生成当前矩阵并实际运行 fixture。证据 recorder 会拒绝源哈希/fixture 列表过时的矩阵。"
                  "历史未绑定证据保留为 rejected，不能补填当前哈希来冒充重新运行。", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = build_report()
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != report:
            print(f"stdlib audit is stale: {args.output}")
            return 1
    else:
        args.output.write_text(report, encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
