# Xu — hosted compiler is the product. Self-host: previous bin/xu (or
# developer/bin snapshot) compiles gen1 → gen2 → gen3, then gen4 only if needed;
# cmp gen2 gen3 confirms Gen3; a transition requires cmp gen3 gen4.
# Rust bootstrap/ is frozen (bootstrap/FROZEN.md): oracle only.

CARGO    ?= cargo

# Publishing with BUMP updates versions as a prerequisite, never while parsing
# the Makefile (so make -n and make help cannot accidentally bump a version).
PYTHON   ?= python3
BOOTSTRAP_ROOT := $(shell ./scripts/xu_host_seed.sh --bootstrap-root)
export XU_BOOTSTRAP_ROOT := $(BOOTSTRAP_ROOT)
export XU_ROOT := $(CURDIR)
MANIFEST := $(BOOTSTRAP_ROOT)/Cargo.toml
empty :=
space := $(empty) $(empty)
BOOTSTRAP_BOUNDARY := $(subst $(space),\$(space),$(BOOTSTRAP_ROOT)/BOUNDARY.json)
BIN      := bin
EXE_SUFFIX := $(if $(filter Windows_NT,$(OS)),.exe,)
XU       := $(BIN)/xu$(EXE_SUFFIX)

.DEFAULT_GOAL := help

.PHONY: help memsafe all xu xu-desktop xu-fmt xu-doctor xu-map xu-doc xu-platform tools \
	server-build-local server-build-linux server-check-linux server-start server-health server-smoke-local server-unit \
	server-remote-check server-remote-deploy server-remote-status server-remote-health server-remote-smoke \
	server-remote-restart server-remote-stop server-remote-rollback \
	gate check test selfhost gen1-test oracle product-selfhost \
	ncall fixtures fixtures-gen3 programs-gen3 verify-gen3 \
	safety safety-cross safety-embedded safety-escape hardening-gate \
	platform gen1-platform cli-platform bench bench-runtime bench-stdlib bench-opt-levels bench-nbody-residency bench-opt-full bench-crosslang bench-language bench-game \
	stdlib-matrix stdlib-matrix-check \
	verify-product-math-x64 verify-product-algorithm-x64 \
	ci ci-fast doc-test packages-test \
	boundary module-path-check release-version-prepare release-version-sync release-version-check \
	bootstrap bootstrap-release bootstrap-e2e bootstrap-warn \
	clean

help:
	@echo "Xu — hosted compiler"
	@echo
	@echo "Product"
	@echo "  make all / xu        hosted compiler → $(XU) then $(BIN)/platform/<os>-<arch>/xu (seed: bin/xu or developer/bin)"
	@echo "  make xu BUMP=patch   bump VERSION + all manifest xu: fields, then rebuild (also minor/major)"
	@echo "  make release-version-sync / release-version-check  align/check manifests against VERSION"
	@echo "  make xu-platform     cross product xu → $(BIN)/platform/<os>-<arch>/ (needs $(XU); XU_SKIP_CROSS=1 / XU_PLATFORM_TARGETS=…)"
	@echo "  product compiler consumers use scripts/run_product_compiler.sh (XUPATH/cache isolated)"
	@echo "  make xu-desktop      desktop pack → $(BIN)/xu-desktop"
	@echo "  make xu-doctor       desktop toolchain check → $(BIN)/xu-doctor"
	@echo "  make xu-fmt          formatter → $(BIN)/xu-fmt"
	@echo "  make xu-map          source path map → $(BIN)/xu-map"
	@echo "  make xu-doc          declaration docs → $(BIN)/xu-doc"
	@echo "  make tools           xu-desktop + xu-fmt + xu-doctor + xu-map + xu-doc (needs $(XU))"
	@echo "  make server-build-local  build xu-examples/examples/11_http_server for this host"
	@echo "  make server-build-linux  cross-build Xu HTTP server for linux-x64"
	@echo "  make server-check-linux  build + verify linux-x64 ELF"
	@echo "  make server-start        run local Xu HTTP server in foreground"
	@echo "  make server-health       check local /health endpoint"
	@echo "  make server-smoke-local  build + run 50 local health/hello/echo/404 rounds"
	@echo "  make server-unit         print hardened systemd unit template"
	@echo "  make server-remote-check  inspect server.md target (read-only)"
	@echo "  make server-remote-deploy build, upload, verify, atomically switch and health-check"
	@echo "  make server-remote-status/health/smoke/restart/stop/rollback  manage remote unit"
	@echo "  make gate            定点成果: primer oracle (gen1_test.sh)"
	@echo "  make oracle          same as gate with --oracle=bootstrap banner (weekly CI)"
	@echo "  make product-selfhost hosted Gen1→Gen2→Gen3; build Gen4 only if Gen2 differs from Gen3"
	@echo "  make selfhost        alias for product-selfhost (blocked if hosted chain is not green)"
	@echo
	@echo "Confirmed product binary verification — 调试 bin/xu 本身用"
	@echo "  make verify-gen3     fixtures + programs 全量跑在 confirmed bin/xu 上"
	@echo "  make fixtures-gen3   438 fixtures 用 confirmed bin/xu 编译运行比对"
	@echo "  make programs-gen3   tests/gen1/programs bootstrap vs bin/xu 行为对照"
	@echo
	@echo "Also"
	@echo "  make platform         multi-target compile matrix"
	@echo "  make cli-platform     product CLI flags/env smoke (see CLI_CROSS_PLATFORM.md)"
	@echo "  make doc-test         xu doc Markdown golden + CLI smoke"
	@echo "  make packages-test    package regressions using product xu and local protocol peers"
	@echo "  make gen1-platform    hosted multi-target matrix"
	@echo "  make bench-runtime    运行时基准(xu-bench,bootstrap vs confirmed product,--save/--check 见脚本)"
	@echo "  make bench-stdlib     标准库热路径（os/io/fs/path/time/strings）基准（xu-bench/scripts/bench_stdlib.sh）"
	@echo "  make stdlib-matrix    生成标准库包/API/fixture/平台矩阵"
	@echo "  make stdlib-matrix-check  检查矩阵是否与当前源码一致"
	@echo "  make bench-opt-levels O0–O3 门禁（17 负载 stdout + nrc/--ra= 拆分 + 墙钟/CPU + O2/O3 vs O1；--quick 仍 5 负载）"
	@echo "  make bench-nbody-residency  产品 nbody 金标、GPR/FP 驻留与 O2/O3 配对 CPU 门禁"
	@echo "  make bench-opt-full   全量 O0–O3 运行+资源+编译对照 → xu-bench/reports/bench_opt_levels.latest.txt"
	@echo "  make bench-crosslang  跨语言能力套件(Xu/Go/C/Rust/Swift → /tmp/xu_cross.txt)"
	@echo "  make bench-language   全局语言评测（横向能力+Game+优化器+标准库+安全+平台+自举+runtime/compile）→ docs/audit/language_eval.latest.md"
	@echo "  make verify-product-math-x64  bin/xu 生成并运行 X64 math/f64 回归"
	@echo "  make verify-product-algorithm-x64  bin/xu 生成并运行 X64 sort/search/slices/heap 回归"
	@echo "  make bench-game       Benchmarks Game 尺子(Xu/C/C++/Rust/Go → docs/audit/)"
	@echo "  make ci               ncall+fixtures+safety+verify-gen3（oracle 不在每次 PR）"
	@echo "  make hardening-gate   统一安全/泄漏/协程/vreg 门禁（HARDENING_GATE_ARGS=…）"
	@echo "  make boundary          strict bootstrap↔Xu source-of-truth / ABI seam 门禁"
	@echo "  make clean"
	@echo
	@echo "Bootstrap (FROZEN primer — bootstrap/FROZEN.md)"
	@echo "  make bootstrap        cargo xu/gen1_ref; freeze banner; not on the product build path"
	@echo "  make oracle           primer gen1_test (hello / safety / gen3==gen4 after warm-up)"

all: xu

# Local peers need no external databases or credentials. Product rebuilds are
# explicit (make xu); this target never silently swaps in the Rust oracle.
packages-test:
	XU="$(abspath $(XU))" $(PYTHON) tests/test_sql_driver_boundary.py -v
	XU="$(abspath $(XU))" $(PYTHON) scripts/run_companion.py packages tests/test_packages_regressions.py -v

# Rebuild when compiler or imported src/xu packages change.
COMPILE_XU := $(wildcard src/cmd/compile/*.xu)
DESKTOP_XU := $(wildcard src/cmd/desktop/*.xu)
DOCTOR_XU  := $(wildcard src/cmd/doctor/*.xu)
FMT_XU     := $(wildcard src/cmd/fmt/*.xu)
MAP_XU     := $(wildcard src/cmd/map/*.xu)
DOC_XU     := $(wildcard src/cmd/doc/*.xu)
XU_PKG_XU  := $(wildcard src/xu/*/*.xu)
# The complete product source tree is a dependency of the hosted compiler.
# The boundary checker still defines the exact Gen1 input closure; this wider
# Make dependency intentionally over-invalidates so a stdlib or newly nested
# package edit cannot leave bin/xu looking newer than its product source.
XU_SOURCE_XU := $(shell find -P src -type f -name '*.xu' -print 2>/dev/null | LC_ALL=C sort)
SELFHOST_POLICY := scripts/gen1_sources.sh scripts/xu_host_seed.sh scripts/build_hosted_chain.sh \
	scripts/stage_seed_syntax.py scripts/check_module_paths.py \
	scripts/install_product_executable.sh \
	$(BOOTSTRAP_BOUNDARY) scripts/check_bootstrap_xu_boundary.py scripts/run_product_compiler.sh \
	scripts/build_platform_xu.sh scripts/build_product_tools.sh scripts/cli_platform_test.sh \
	scripts/pack_developer_xu.sh scripts/deploy_xu_server.sh scripts/deploy_xu_remote.sh scripts/pack_macos_ui_app.py \
	scripts/pack_macos_ui_oneexe.py scripts/pack_linux_ui_oneexe.py scripts/pack_windows_ui_oneexe.py \
	scripts/companion_repos.py scripts/run_companion.py
XU_DESKTOP := $(BIN)/xu-desktop$(EXE_SUFFIX)
XU_DOCTOR  := $(BIN)/xu-doctor$(EXE_SUFFIX)
XU_FMT     := $(BIN)/xu-fmt$(EXE_SUFFIX)
XU_MAP     := $(BIN)/xu-map$(EXE_SUFFIX)
XU_DOC     := $(BIN)/xu-doc$(EXE_SUFFIX)

xu: $(XU) tools
ifneq ($(strip $(BUMP)),)
	$(PYTHON) scripts/module_versions.py --check-release
	$(PYTHON) scripts/check_release_identity.py --require-cli --xu "$(XU)"
endif

module-path-check:
	$(PYTHON) scripts/check_module_paths.py

$(XU): | module-path-check

release-version-prepare:
	PYTHON="$(PYTHON)" ./scripts/bump_version.sh "$(BUMP)"

release-version-sync:
	$(PYTHON) scripts/module_versions.py --sync-release

release-version-check:
	$(PYTHON) scripts/module_versions.py --check-release

ifneq ($(strip $(BUMP)),)
# A single prerequisite runs once under make -j and forces a rebuild after
# all release manifests have been synchronized.
$(XU): release-version-prepare
endif

# Explicit product-lane name.  This target is intentionally separate from
# `oracle`: it resolves only a hosted seed and never invokes cargo/primer.
product-selfhost: $(XU)
	@echo "product-selfhost: hosted product lane (Gen2==Gen3, or Gen3==Gen4 after a warm-up transition)"

# Cross product xu for hosted --target names. `make xu` already does this
# after the confirmed product; this target rebuilds only the platform copies.
xu-platform: $(XU)
	./scripts/build_platform_xu.sh $(XU) $(BIN)/platform

tools: xu-doctor xu-desktop xu-fmt xu-map xu-doc

xu-desktop: $(XU_DESKTOP)
xu-doctor: $(XU_DOCTOR)
xu-fmt: $(XU_FMT)
xu-map: $(XU_MAP)
xu-doc: $(XU_DOC)

$(BIN):
	mkdir -p $(BIN)

# Self-host: previous hosted xu (or developer/bin snapshot) compiles the
# next Gen1. Primer is not on this path.
$(XU): VERSION src/cmd/compile/xu.xun scripts/module_versions.py $(COMPILE_XU) $(XU_PKG_XU) $(XU_SOURCE_XU) $(SELFHOST_POLICY) | $(BIN)
	@set -e; $(PYTHON) scripts/check_bootstrap_xu_boundary.py --strict-freeze; \
	seed="$$(XU_ALLOW_ORACLE_SEED=0 ./scripts/xu_host_seed.sh)"; \
	XU_ALLOW_ORACLE_SEED=0 ./scripts/build_hosted_chain.sh "$$seed" "$(XU)"

# Product sibling tools (compiled by product xu; not in GEN1 selfhost list).
# Product tools: default name has no extension (Windows .exe).
define build_product_tool
	./scripts/build_product_tools.sh "$(XU)" "$(BIN)" "$(1)"
endef

$(XU_DOCTOR): $(XU) src/cmd/doctor/xu.xun $(DOCTOR_XU) $(XU_PKG_XU) | $(BIN)
	$(call build_product_tool,xu-doctor)

$(XU_DESKTOP): $(XU) $(XU_DOCTOR) src/cmd/desktop/xu.xun $(DESKTOP_XU) $(XU_PKG_XU) | $(BIN)
	$(call build_product_tool,xu-desktop)

$(XU_FMT): $(XU) src/cmd/fmt/xu.xun $(FMT_XU) $(XU_PKG_XU) | $(BIN)
	$(call build_product_tool,xu-fmt)

$(XU_MAP): $(XU) src/cmd/map/xu.xun $(MAP_XU) $(XU_PKG_XU) | $(BIN)
	$(call build_product_tool,xu-map)

$(XU_DOC): $(XU) src/cmd/doc/xu.xun $(DOC_XU) $(XU_PKG_XU) | $(BIN)
	$(call build_product_tool,xu-doc)

# Milestone / oracle: frozen primer compiles Gen1 and diffs behavior.
# Not on the product `make xu` path. CI runs this weekly (see oracle.yml).
gate check test gen1-test oracle:
	$(PYTHON) scripts/check_bootstrap_xu_boundary.py --strict-freeze
	./scripts/gen1_test.sh --oracle=bootstrap

# Historical callers used `make selfhost`; keep that spelling but make its
# product-only semantics explicit instead of silently routing to the primer.
selfhost: product-selfhost

ncall:
	$(PYTHON) scripts/check_ncall_registry.py

stdlib-matrix:
	$(PYTHON) scripts/generate_stdlib_matrix.py

stdlib-matrix-check:
	$(PYTHON) scripts/generate_stdlib_matrix.py --check

# Oracle-only corpus target; product corpus verification is fixtures-gen3
# (the target name is retained for compatibility; bin/xu is the confirmed product).
fixtures: bootstrap
	./scripts/run_fixtures.sh --xu="$(BOOTSTRAP_ROOT)/target/debug/xu" --label=oracle

# Confirmed bin/xu behavior verification: run everything on the product
# binary itself, not on the gen1 intermediate. Depends on `xu` so the
# chain is rebuilt whenever compiler sources change.
fixtures-gen3: xu
	./scripts/run_fixtures.sh --xu=$(CURDIR)/bin/xu --sub=build --label=gen3

programs-gen3: xu
	./scripts/programs_cross_check.sh --xu=$(CURDIR)/bin/xu

doc-test: xu-doc
	./scripts/doc_test.sh

verify-gen3: fixtures-gen3 programs-gen3 doc-test
	@echo "verify-gen3: PASS"

# Oracle safety parity; product safety is supplied through verify-gen3/hardening args.
safety: bootstrap
	./scripts/safety_test.sh --xu="$(BOOTSTRAP_ROOT)/target/debug/xu"

# Product-lane multi-instance memory-safety batteries.
# Override compiler: make memsafe XU=/path/to/xu
XU_PRODUCT ?= /tmp/xu_prod
.PHONY: memsafe
memsafe:
	XU="$(XU_PRODUCT)" python3 scripts/memsafe_multi_test.py --xu "$(XU_PRODUCT)"
	XU="$(XU_PRODUCT)" python3 scripts/memsafe_drop_multi_test.py
	XU="$(XU_PRODUCT)" python3 scripts/memsafe_field_assign_ledger_test.py
	XU="$(XU_PRODUCT)" python3 scripts/memsafe_string_hold_test.py
	XU="$(XU_PRODUCT)" python3 scripts/memsafe_foreach_ledger_test.py
	XU="$(XU_PRODUCT)" python3 scripts/memsafe_heap_ledger_test.py

.PHONY: memsafe
safety-cross:
	./scripts/safety_cross_target.sh

safety-embedded:
	./scripts/safety_embedded.sh

safety-escape:
	./scripts/safety_escape_test.sh

hardening-gate:
	./scripts/hardening_gate.sh $(HARDENING_GATE_ARGS)

boundary:
	$(PYTHON) scripts/check_bootstrap_xu_boundary.py --strict-freeze

# Oracle cross-target matrix; hosted product matrix is gen1-platform/product tools.
platform: bootstrap
	./scripts/platform_test.sh --xu="$(BOOTSTRAP_ROOT)/target/debug/xu"

gen1-platform:
	./scripts/gen1_platform_test.sh

cli-platform:
	./scripts/cli_platform_test.sh

bench:
	$(PYTHON) scripts/run_companion.py bench scripts/bench_compile.sh

bench-runtime: xu
	$(PYTHON) scripts/run_companion.py bench scripts/bench_runtime.sh

bench-stdlib: xu
	$(PYTHON) scripts/run_companion.py bench scripts/bench_stdlib.sh

bench-opt-levels:
	$(PYTHON) scripts/run_companion.py bench scripts/bench_opt_levels.sh --check

bench-nbody-residency:
	$(PYTHON) scripts/run_companion.py bench scripts/test_nbody_residency.sh --xu="$(abspath $(XU))"

bench-opt-full:
	$(PYTHON) scripts/run_companion.py bench scripts/bench_opt_full.sh

bench-crosslang: xu
	$(PYTHON) scripts/run_companion.py bench scripts/bench_crosslang.py --out /tmp/xu_cross.txt

# Uses existing bin/xu; does not rebuild the compiler.
bench-language:
	$(PYTHON) scripts/language_eval.py

# Alias: same global evaluation.
eval: bench-language

verify-product-math-x64: xu
	./scripts/product_math_x64_test.sh

verify-product-algorithm-x64: xu
	./scripts/product_algorithm_x64_test.sh

bench-game: xu
	$(PYTHON) scripts/run_companion.py bench scripts/bench_game.py --out reports/game.txt --report reports/game.md

# Local/server support is deliberately a thin wrapper around the deployment
# script. It never SSHes, uploads, installs system units, or reads server.md.
server-build-local:
	./scripts/deploy_xu_server.sh build-local

server-build-linux:
	./scripts/deploy_xu_server.sh build-linux

server-check-linux:
	./scripts/deploy_xu_server.sh check-linux

server-start:
	./scripts/deploy_xu_server.sh start

server-health:
	./scripts/deploy_xu_server.sh health

server-smoke-local:
	./scripts/deploy_xu_server.sh smoke-local

server-unit:
	./scripts/deploy_xu_server.sh systemd-unit

server-remote-check:
	./scripts/deploy_xu_remote.sh check

server-remote-deploy:
	./scripts/deploy_xu_remote.sh deploy

server-remote-status:
	./scripts/deploy_xu_remote.sh status

server-remote-health:
	./scripts/deploy_xu_remote.sh health

server-remote-smoke:
	./scripts/deploy_xu_remote.sh smoke

server-remote-restart:
	./scripts/deploy_xu_remote.sh restart

server-remote-stop:
	./scripts/deploy_xu_remote.sh stop

server-remote-rollback:
	./scripts/deploy_xu_remote.sh rollback

# Run the executable bootstrap↔Xu policy gate on every CI bundle, even when
# bin/xu is already up to date and the self-host recipe is not re-evaluated.
ci-fast: boundary ncall fixtures
ci: ci-fast safety safety-cross safety-embedded verify-gen3

# --- independent primer (FROZEN 2026-08-28; bootstrap/FROZEN.md) ---------------
# Frozen. Product `make xu` does not call this. `make oracle` still does.

.PHONY: bootstrap-warn
bootstrap-warn:
	@echo "=== bootstrap primer is FROZEN (2026-08-28) ==="
	@echo "Only P0 correctness fixes. New features go in src/xu and src/cmd/compile."
	@echo "See $(BOOTSTRAP_ROOT)/FROZEN.md and $(BOOTSTRAP_ROOT)/SYNC_DIFF.md."

bootstrap: bootstrap-warn
	$(CARGO) build --manifest-path "$(MANIFEST)" -p xu --bin xu --bin gen1_ref

bootstrap-release: bootstrap-warn
	$(CARGO) build --release --manifest-path "$(MANIFEST)" -p xu --bin xu

bootstrap-e2e: bootstrap-warn
	$(CARGO) test -p xu --test e2e --manifest-path "$(MANIFEST)"

clean:
	if [ -f "$(MANIFEST)" ]; then $(CARGO) clean --manifest-path "$(MANIFEST)"; fi
	rm -rf $(BIN)
	rm -f hello a.out hello.exe
