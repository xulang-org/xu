# Native runtime and package protocol gates

The Installed SDK workflow (`sdk.yml`) runs on PRs to `dev` and `main`, on its
schedule, and by dispatch. Release builds and reuse of a prior release bundle
both require its reusable six-platform gate before publication can proceed.
The existing Intel seed regeneration job runs the Intel macOS runtime checks;
the native matrix runs Linux, macOS ARM64 and both Windows architectures. Manual
seed reuse schedules all six native targets; a manual `native_target` selection
is a diagnostic subset, while PRs and releases always select the full matrix.

## Public runtime fixtures

Run on a matching native host, with a verified product compiler:

```sh
./scripts/platform_test.sh --xu=bin/xu --ci-native --targets=linux-x64
```

`--ci-native` uses the public fixtures in `scripts/test_platform_runtime.py`.
It exercises file round trips, path normalization, SHA-256, system entropy,
ECDSA verification, X.509 certificate signatures, chain/hostname verification,
the system certificate pool, TLS pipes, TLS ECDHE interoperability with Python,
JSON parsing, wall time, parallel workers with maps, buffered and rendezvous
string channels, interface enumeration/lookup, TCP IPv4/IPv6, connected and
unconnected UDP, Unix socket loopback and network rejection contracts. Python socket peers independently
check the request bytes. Every artifact executes with a timeout and must match
its expected output and exit status. A mismatched host/target, missing compiler,
failed build, missing IPv6, timeout, or inability to execute fails the job.

The local default `platform_test.sh` matrix still uses the ignored `tests/`
corpus and its historical emulation/compile-only behavior. CI explicitly selects
`--ci-native`; the public suite supplies representative coverage of its library,
networking and concurrency families without publishing that local corpus.
It does not claim to run every fixture in that corpus. Crypto fixtures live in
`scripts/platform_crypto_cases.py`: public test keys and certificates generated
independently with Python cryptography, with certificate validity 2020–2099.
No LoongArch/RISC-V hardware or desktop GUI gate is added.

Windows runs `test_windows_socket_poll.py` (all four optimization levels, three
runs each) and `test_windows_workers.py` on **both** native architectures. These
scripts reject non-Windows hosts. Windows Unix-domain loopback is the sole
explicit omission: Xu does not support that API on Windows, so the suite emits
`::notice::SKIP net_unix_loopback` with the reason and executes the unsupported
API rejection contract instead. There is no catch-and-pass for runner failures.
No other runner limitation currently has a skip exception.

## Local package protocol fixtures

On Linux, install the independent test signer and run:

```sh
python3 -m pip install 'cryptography>=41'
python3 scripts/test_package_protocol.py --compiler bin/xu
```

The SDK Linux x64 job executes this suite. It uses disposable projects, isolated
caches, loopback HTTP proxies and a local SumDB with a fixed **test-only** signing
seed. Python hashlib/ZIP/Ed25519 implementations generate the wire data; Xu's
existing dependency, sumdb and driver dependency code consumes it through real
`install` and `build` commands. The tests cover:

- Authenticated bad digest and corrupted checkpoint signature rejection, with
  no accepted cache entry left behind.
- An MVS diamond selecting the higher shared version, retaining both graph
  versions in the lock, and replaying offline after the module cache is removed.
- Comma fallback on 404/410, fail-closed comma behavior on 503, pipe fallback
  on 503, and no fallback after a malformed successful response.
- Vendor tampering rejected by a frozen build after a successful build control.
- Persisted record and nontrivial Merkle proof cache working offline/frozen
  after the servers close, with unchanged cache bytes; missing nodes or records
  fail explicitly.
- A validly signed fork at the accepted checkpoint size rejected on a fresh
  module lookup, preserving the trusted checkpoint and rejecting publication.

These tests require Python cryptography and curl; missing prerequisites fail.
No public package registry, production signing key, credentials, external
package checkout or ignored `tests/` file is used. Package protocol execution is
currently gated on Linux x64; macOS/Windows package protocol behavior is not
claimed by this suite. Native runtime results for other operating systems must
come from their CI runners, not Linux cross-compilation.

Only CI, test scripts and this gate documentation change; product and module
versions are unchanged. Rollback consists of reverting these gate changes.
