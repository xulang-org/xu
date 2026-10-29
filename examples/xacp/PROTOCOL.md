# XACP protocol specification

This is the authoritative specification of the implemented Xu Agent Control
Protocol (XACP), based on source and smoke-test contracts present on 2026-10-28.
The design documents from that date explain individual changes; their old status
notes and descriptions of earlier behavior are superseded here. Where they
differ, this document follows the code. Behavior without an implementation
contract is **unspecified**.

## 1. Scope and entry points

XACP provides local process inspection, bounded output reads, and control of a
registered retained `widgets.Screen`. Stdio and TCP use the same framing,
schema, authentication, permissions, and session rules. Requests execute
sequentially, with one active request per session; there is no multiplexing or
unsolicited event stream.

| Entry point | Business `main` | Transport and lifetime |
| --- | --- | --- |
| Generated `--xacp-stdio`; `xu xacp control <program>` | Skipped | stdin requests, stdout responses; one session, then control exits. `control` adds `--xacp-stdio` and inherits the caller's pipes. |
| Generated `--xacp-tcp` | Skipped | Listens on `127.0.0.1` at the nonzero build-time port. One session per peer, peers served sequentially; a bad peer does not terminate the listener. |
| Library `xacp.attach_stdio()` | Runs | Starts a control `xu` coroutine. `ScreenControl.done` receives the control exit status on EOF, fatal session error, or transport failure; application decides when to exit. |
| Library `xacp.attach_tcp(port)` | Runs | Explicit loopback listener at the supplied port, independent of the build-time port. Sequential peers; `done` reports server termination, not each peer close. |

The exclusive startup adapter has no registered Screen because main is skipped;
authorized UI operations there return `not_implemented`. Attachment lets the
application create and register its Screen while control is running.

`xu build --xacp` enables generated discovery/startup support.
`--xacp-port PORT` and `--xacp-port=PORT` also enable it; the build accepts
0..65535. Port 0 disables the generated TCP entry; starting `--xacp-tcp` then
fails. `attach_tcp` requires 1..65535. Generated support requires a hosted native
executable; lib/shared/test, embedded targets, and `--desktop` packaging are
rejected. Importing `#xacp` alone does not generate discovery/startup support.

Ordinary startup does not read control stdin or listen for connections. The
first exclusive control flag before `--` wins; arguments after `--` are business
arguments. `--xacp-help` before that boundary prints discovery and exits.
`xu xacp attach <program> [-- args...]` runs the application with the safe `--`
argument boundary; application code must still call the attachment API.
No automatic attachment environment hook is implemented.

`xu xacp connect PORT` relays complete frames to `127.0.0.1:PORT`, waiting for
one response per request. Input EOF between frames closes the client connection
without waiting for server EOF. It synthesizes neither hello nor token and has
no application-level response deadline; an overall process/I/O timeout is the
caller's responsibility.

Stdio reserves stdin for control and stdout for frames. Application/UI code must
not also read stdin. Use stderr for business logs: output capture does not
redirect business stdout away from the control pipe (section 8).

## 2. XACP/1 framing and XUN bodies

Every request and response is exactly:

```text
XACP/1\n<N>\n<exactly N bytes of XUN body>
```

Here `\n` denotes one LF byte. There is no separator after the body; another
frame may begin immediately.

- Magic is exactly `XACP/1`, case-sensitive, without CR or spaces.
- Length is 1..8 ASCII decimal digits. Leading zeros are accepted. Empty
  lengths, signs, spaces, non-digits, and zero produce `frame_error`.
- Either header line may contain at most 16 bytes before LF; a seventeenth
  non-LF byte produces `frame_error`. Length lines over eight digits remain
  invalid even within that bound.
- `N` counts bytes, not Unicode characters. The maximum is 1048576 bytes
  (1 MiB, `MAX_FRAME_BYTES`). A valid length above it produces
  `frame_too_large` without reading the body.
- Partial reads and coalesced frames are supported. Framing assigns no meaning
  to body bytes, including NUL or delimiter-like text; the body must still
  parse as XUN and satisfy schema. Invalid body XUN produces `frame_error`,
  id 0; valid XUN with invalid request schema produces `schema_error`.
- EOF within a header/body produces `truncated_frame`, id 0, with a best-effort
  reply. EOF at a frame boundary closes normally without an EOF response.
  Fatal errors discard later input, including frames already in the same read.
  There is no legacy framing fallback.

A request body is a dictionary with exactly `id`, `op`, and `args`:

```text
id: !i 1
op: xacp.hello
args:
  ver: !ver 1.0.0
  nonce: "client-chosen-unique-nonce"
```

`id` requires `!i`; `op` is a nonempty string; `args` is a dictionary. Unknown
operations or argument keys are schema errors. Integers, booleans, and floats
require `!i`, `!b true/false`, and `!f`. String fields generally require nonempty
untagged/`!s` scalars; hello token may be empty. Checked scalar strings are
bounded by 65536 bytes. Default limits are 64 argument fields (also input-step
count and fields per step), 10000 table rows per window, and node ids up to
16777215. Screen enumeration has a separate 512-node cap. Hosts may lower core
limits; supplied transports use defaults and the timeout settings below.
Duplicate-key handling and id overflow are unspecified as XACP contracts.

Success contains `id: !i`, `ok: !b true`, and operation-specific `data`.
Tree/screenshot success also includes `redacted: !b` at the root and in `data`.
An error body is:

```text
id: !i 2
ok: !b false
error:
  code: invalid_request_id
  msg: "request id is not monotonic"
```

Errors echo a parseable top-level `id: !i N`, including zero/negative values.
If no id can be obtained, or failure is at framing/XUN-parse level, id is 0.
Hello/idle expiry also uses 0. `error.code` is the machine-readable discriminator;
exact diagnostic wording is unspecified except where fixed below. `msg` is
optional, omitted when empty, path-filtered, and truncated to at most 256 bytes
at a UTF-8 boundary **before** quoting. Escaping can make its serialized field
longer. It is one physical line in double quotes, using XUN escapes such as
`\"`, `\\`, `\n`, `\r`, `\t`, and `\xHH`.

## 3. Hello, permissions, and replay protection

A session starts in NEW with no permissions and `next_id = 1`. Its first
schema-valid operation must be `xacp.hello`. Required arguments are
`ver: !ver 1.0.0` and a nonempty nonce of at most 65536 bytes. Other versions
are schema errors; there is no version-negotiation fallback. Optional arguments
are string `token` and `permissions: !i 0..31`; unknown bits are schema errors.
The grant is `requested & allowed`; omission requests the whole allowed mask.
Requesting unavailable bits within 0..31 is not an authentication failure.

| Bit | Name | Required for |
| --- | --- | --- |
| 1 | `PERM_INFO` | `proc.status` |
| 2 | `PERM_PROCESS` | `proc.output` |
| 4 | `PERM_UI_READ` | `ui.tree`, `ui.screenshot`, `ui.record` |
| 8 | `PERM_UI_MUTATE` | `ui.input`, `ui.act` |
| 16 | `PERM_UI_RAW` | Additional permission for tree/screenshot `raw: !b true` |

`PERM_NONE = 0`, `PERM_ALL = 31`; hello requires no permission bit.

- With no nonempty host `XU_XACP_TOKEN`, allowed permissions are INFO (1), even
  if the client supplies a token or the host sets `XU_XACP_ALLOW_RAW=1`.
- With a host token, hello must supply it. Comparison uses
  `crypto/subtle.constant_time_compare`. Missing/empty/mismatched tokens return
  `auth_failed` and close. A matching token allows 15 by default; only exact
  host setting `XU_XACP_ALLOW_RAW=1` adds RAW and allows 31.
- Development permissions are explicit host policy: `development_permissions()`
  returns 31; `enable_development`/`set_permissions` can set a NEW session's
  mask. They do not bypass schema, size, window, or lifecycle checks. Supplied
  transports negotiate the policy above, without automatically enabling full
  development permissions. Permissions cannot be changed after OPEN.

The transport reads the expected token at session start; RAW opt-in is checked
during hello. After authentication and permission validation, the host-owned
nonce registry rejects a replay with same-id `nonce_replay`, clears the session,
and disconnects without entering OPEN. Comparisons use exact decoded bytes,
without normalization. Schema/authentication failures do not record a nonce;
recorded nonces survive session close.

The TCP listener shares its registry across accepted connections; stdio uses
the same checking logic for its single session. In the supported single-controller
host model this covers successive connections in that process. Separate
processes do not share a registry; global sharing across independently created
controllers is unspecified.

The registry is a bounded FIFO ring. `XU_XACP_NONCE_CACHE` defaults to 1024,
accepts ASCII decimal 1..65536, and uses the default for invalid values. Replays
do not refresh order. Evicted nonces may be reused: protection covers the last
N successful hellos. Exact `XU_XACP_NONCE_REPLAY=0` disables checking and
retention; all other values enable it. Both settings are read at registry/server
initialization.

Success enters OPEN and returns data `state: OPEN`, quoted `nonce`, granted
`permissions: !i`, and `permission_label`: `none` for 0, `info` for 1,
`development` for 31, otherwise `custom`. Nonce echo is path-filtered, so a
path-like nonce need not echo verbatim; replay checks still use original bytes.
A second schema-valid hello in OPEN returns `permission_denied`. Close clears
active state, permissions, and session nonce and invalidates its generation,
without clearing replay history.

## 4. Request ids, errors, and disconnects

Envelope/argument validation precedes `begin_request`. That function checks,
in order: closed session, NEW non-hello, active request, exact next id, then
permission. Thus schema failure takes precedence over lifecycle/id errors;
NEW non-hello returns `hello_required` and closes even if its numeric id is wrong.

Each accepted request reserves its id and increments `next_id` by one. Hello
must start at 1. Zero/negative, repeated, backward, or skipped ids return
`invalid_request_id` with `msg: "request id is not monotonic"`, without closing
or consuming an id. NEW hello id 2 may be followed by hello id 1 within the
original hello deadline. Permission denial, including RAW denial, also preserves
the id. Execution failures after reservation consume it. Cancellation clears
the active reservation without rolling back `next_id`.

| Error code | Meaning | Disconnect/id policy |
| --- | --- | --- |
| `frame_error` | Invalid header/length or body XUN | Close; id 0 |
| `frame_too_large` | Declared body exceeds 1048576 bytes | Close; id 0 |
| `truncated_frame` | EOF within frame | Close; id 0; best-effort reply |
| `schema_error` | Invalid envelope, operation, argument key/type/bound | Close, except invalid `proc.output` arguments in OPEN: keep connection and id |
| `hello_required` | NEW operation is not hello, or hello was not negotiated | Close |
| `auth_failed` | Configured token absent or wrong | Close |
| `nonce_replay` | Nonce remains in replay registry | Close |
| `hello_timeout` | Hello deadline expires | Close; id 0 |
| `session_idle` | OPEN complete-frame idle deadline expires | Close; id 0 |
| `permission_denied` | Missing operation bit, second hello, or RAW denied | Keep; id not consumed |
| `invalid_request_id` | Id differs from positive `next_id` | Keep; id not consumed |
| `request_in_flight` | Active core reservation or full Screen mailbox | Keep; core rejection preserves id; mailbox rejection is after reservation and consumes it |
| `request_timeout` | Attached UI reply deadline expires | Keep; id consumed |
| `not_implemented` | No Screen/adapter or output capture unavailable | Keep; id consumed |
| `adapter_error` | Execution failure: bad tree window/node, output cursor past end, response overflow, raster backend unavailable, etc. | Keep; id consumed |
| `stale_window` | Foreign/closed window or changed/removed registration | Keep; id consumed |
| `stream_required` | Registered `ui.record` needs a separate sink | Keep; id consumed |
| `screenshot_too_large` | Pixel, inline response, or file limit exceeded | Keep; id consumed |
| `file_unavailable` | Private screenshot file cannot be written | Keep; id consumed |
| `encode_error` | Pixel readback/PNG encoding failure | Keep; id consumed |
| `stale_request` | Completion does not match active id/generation | Core safeguard; does not itself close |
| `session_closed` | Operation/completion on a closed session | Already closed |

The last two codes are core lifecycle safeguards; normal sequential wire requests
cannot submit arbitrary completions. Transport read/write/wait failures close
and clean up the session but cannot guarantee delivery of an error response.
TCP closes that peer and continues accepting; stdio ends its control loop.
An attached application's main is not forcibly terminated by a session error.

## 5. Deadlines and precedence

Values are milliseconds, read once when the supplied server initializes limits
(once per TCP listener, not per peer). Only ASCII decimal digits are accepted;
leading zeros are allowed. Empty, signed, malformed, out-of-range, or overflowing
values silently use defaults.

| Setting | Default | Accepted values | Scope/result |
| --- | --- | --- | --- |
| `XU_XACP_REQUEST_TIMEOUT_MS` | 5000 | 1..600000 | Attached UI wait; same-id `request_timeout`, keep OPEN |
| `XU_XACP_HELLO_TIMEOUT_MS` | 5000 | 1..600000 | Control-loop start (stdio/attach loop or TCP accept) to successful hello; id-0 `hello_timeout`, close |
| `XU_XACP_IDLE_TIMEOUT_MS` | 60000 | 1000..3600000, or 0 to disable | OPEN time since complete inbound frame; id-0 `session_idle`, close |

Request timing starts just after successful reservation, before Screen lookup,
enqueue, and reply wait; frame reading/parsing/validation is excluded. The
implemented timer bounds attached `ui.tree/ui.screenshot/ui.act/ui.input/ui.record`
marshal waits. Hello, process operations, and exclusive adapter failures execute
synchronously without an independent cancellation timer. File export after a
timely UI reply is synchronous too. Blocked response-write deadlines are
unspecified.

Partial headers/bodies do not renew hello/idle time. Recoverable NEW errors do
not restart hello time. Complete request bodies refresh the OPEN idle reference,
including requests returning recoverable errors. Coalesced frames use their
read's arrival time, not later dispatch completion. Expiry is checked before
accepting late bytes or dispatching the next body.

During a UI request wait, only the request deadline applies; idle is checked
after dispatch returns. A request taking longer than idle yields its same-id
result/`request_timeout` first, then immediate id-0 `session_idle` if idle has
elapsed. Completion does not grant a fresh idle interval. Hello expiry applies
only in NEW; idle expiry only in OPEN.

Diagnostics are `"request exceeded T ms"`, `"hello not completed within H ms"`,
and `"no complete frame for I ms"`, with the configured numeric value.
Already executing UI work is not interrupted. Late results cannot satisfy a
later request, but a timed-out mutation may already have taken effect.

## 6. Screen marshalling and tree pagination

The supported model is one attached controller and one registered Screen per
process. The Screen-owning coroutine calls `register_screen($&control, &screen)`
and nonblocking `poll($&control, $&screen)` between UI iterations. A poll
services at most one job. Closed-Screen or duplicate registration is rejected;
unregister before registering a replacement or abandoning an open poll loop.

The control coroutine owns the authoritative session. Copied request bodies,
permissions/scalars, registration generation, and channels cross the single-slot
mailbox; mutable Screen references do not cross coroutines. The UI owner checks
window/canvas/Screen and registration generations, executes the checked adapter,
and serializes results before replying. Each request has its own buffered reply
channel. Timeout removes unpolled work; executing jobs may finish into an
abandoned reply channel without blocking or replying to another id.

Without registration, UI operations return `not_implemented` after permission
checks. Unregister invalidates queued work with `stale_window`. Screen
close/dispose (including window-close events) sends a single-slot notification:
waiting work fails with `stale_window`; after invalidation later UI requests
return `not_implemented`. Registration changes invalidate old jobs. Wrong window
identity returns `stale_window`.

### `ui.tree`

Requires UI_READ. Arguments:

| Argument | Type/default | Rule |
| --- | --- | --- |
| `win` | Optional `!i` >=0 | Omission selects registered Screen; a supplied value must match its positive window id. 0 yields `stale_window`. |
| `include_hidden` | `!b`, false | Include invisible nodes. |
| `start` | `!i`, 0 | Nonnegative index into filtered sequence. |
| `max_table_rows` | `!i`, min(512, limit) | 1..`limits.max_table_rows` (default limit 10000); invalid bounds are schema errors, not clamped. |
| `raw` | `!b`, false | True additionally requires RAW. |

Nodes retain Screen enumeration order after hidden/deleted-node filtering.
Page indexes do not renumber node ids. Full filtered enumeration is capped at
512 before pagination; exceeding this produces `adapter_error`, not a silently
truncated tree.

Data contains `redacted`, `win`, `generation`, `start`, `count`, `total`,
`truncated: !b`, `next_start: !i`, and `nodes`. The page is
`[start, start + count)`, where `count = min(max_table_rows, total - start)`;
`next_start = start + count`, `truncated = next_start < total`. Continue with
`start = next_start`; on the last page `next_start == total`. `start == total`
returns `nodes: []`; `start > total` is `adapter_error`. Response-budget overflow
is `adapter_error`; reduce `max_table_rows`.

Each node contains integer `id/kind/parent`, float `x/y/width/height`, boolean
`visible/enabled/focusable/focused`, and quoted `text`. Use node ids within their
Screen lifetime. `generation` is Screen identity, not a revision counter for
every text/layout mutation. Restart at 0 if it changes between pages; unchanged
generation also does not promise snapshot consistency. Atomic multi-page
snapshots are unspecified.

Default redaction empties secure/password/secret-input text and adds node
`redacted: !b true`. Other text is path-filtered and truncated to 256 bytes at
a UTF-8 boundary, with `text_truncated: !b true` when shortened. Root/data
`redacted` means the policy was applied, even if no secret existed. RAW disables
serializer secret-text suppression and truncation, but path filtering remains.
The underlying Screen enumerator already suppresses password-editor text even
for RAW; RAW cannot restore it. No window title is emitted, including in RAW.

Tree text, hello nonce echo, and error messages use a path-token filter:
recognized absolute POSIX/drive/UNC paths and `$HOME` tokens become `<path>`.
Relative paths and URI slashes remain ordinary text. This is the implemented
filter, not a guarantee of detecting every path representation. It is not
applied to `proc.output` bytes.

## 7. Screenshots, mutations, and recording

### `ui.screenshot`

Requires UI_READ, plus RAW for `raw: !b true`. Arguments are required positive
`win: !i`; optional `node: !i` (0..16777215, absent/0 selects whole Screen);
`scale: !f` (0.1..4.0, default 1.0); `mode` (`inline_b64` or `file`, default
`inline_b64`); and `raw: !b` (false). A positive node must exist; invalid targets
are `adapter_error`. A matching live Screen and native raster backend are
necessary; simulation alone may return `adapter_error`.

Data includes `redacted`, logical `width/height: !f`,
`pixel_width/pixel_height: !i`, `mime: image/png`, `bytes: !i` (PNG byte count),
and `mode`. Export is RGBA8 PNG with only IHDR/IDAT/IEND chunks, no text/EXIF
metadata. Pixel dimensions round up logical size times scale; each dimension
is bounded by 16384 and RGBA storage by 67108864 bytes. Oversized requests
return `screenshot_too_large`.

Default redaction fills visible secure/password/secret-input rectangles with
opaque `(128,128,128,255)` (`#808080`) in an owning pixel copy. Mapping accounts
for node crop origin, actual scaled density, floor/ceil edges, and clipping.
The full tree is inspected independently of pagination/hidden-node requests.
The source Surface is unchanged and disposed before PNG encoding. RAW skips
masking. Ordinary text pixels are not masked; there is no OCR redaction.

`inline_b64` adds quoted `data` with base64 PNG. The complete response body,
including envelope, redaction metadata, and base64, must fit the frame limit;
otherwise `screenshot_too_large` suggests lowering scale or using file mode.
Pixel readback/encoding failures return `encode_error`.

`mode: file` uses the POSIX native UI bridge and a fixed private directory:

- Nonempty `XDG_RUNTIME_DIR`: `$XDG_RUNTIME_DIR/xacp/<pid>/`.
- Otherwise: `${TMPDIR:-/tmp}/xacp-<uid>/<pid>/`.

The base must be absolute and open as a directory without following its final
symlink. Created XACP directories use 0700; existing XACP parent/pid directories
must belong to the current uid with no group/other or special permission bits,
and are opened with `O_NOFOLLOW`. Directory descriptors pin validated locations.
Files use `O_CREAT|O_EXCL|O_NOFOLLOW`, mode 0600, and names
`shot-<session_generation>-<request_id>.png`; existing names are never overwritten.
Data adds only relative `path: "shot-...png"` and `dir_hint: xacp-runtime`.
Host code obtains the absolute directory with `xacp.screenshot_dir()`.
Client argument `path` is unknown and yields fatal `schema_error`.

Each file is at most 33554432 bytes (32 MiB). `XU_XACP_SCREENSHOT_MAX_BYTES`
accepts ASCII decimal 1..33554432 to lower it; invalid input uses the default.
It is checked during creation/export, rather than latched with timeout settings.
Each session retains 16 files, deleting oldest on successful overflow. Close
(EOF, fatal error, timeout, or transport failure) cleans up session files and
attempts to remove the empty pid directory. Process-exit cleanup is best effort;
cleanup after abrupt termination is unspecified.

Only the authoritative session writes files after a timely UI reply; late
timed-out UI work cannot export a file. Unsafe/unavailable directories, write
failure, name collision, missing native bridge, or a platform without the POSIX
sink yields `file_unavailable`; file-size overflow is `screenshot_too_large`.
Both keep the session and consume the id.

### `ui.act` and `ui.input`

Both require UI_MUTATE and matching positive `win: !i`. `ui.act` additionally
requires `node: !i` and string `act`: `focus`, `click`, `set_text`, or
`set_checked`. `set_text` requires nonempty string `text` (<=65536 bytes);
`set_checked` requires `checked: !b`. Those fields are invalid on other actions.
Schema permits node 0, but execution requires a positive live node. Invalid or
unsupported targets are `adapter_error`. Click sends normal pointer down/up at
a button's center; `set_checked` changes a button's selected state, not an
arbitrary widget property.

`ui.input` requires a `steps` list (at most 64 by default); empty is valid.
Each step requires `ev`: `pointer_down`, `pointer_up`, `pointer_move`,
`pointer_enter`, `pointer_leave`, `pointer_cancel`, `key_down`, `key_up`,
`pointer_scroll`, or alias `scroll`. Optional `x/y/dx/dy`
are `!f`; `button/buttons/modifiers/key/scan/repeat/click_count/time_ns` are
`!i`; all default to zero. Unknown fields are schema errors. Execution requires
finite coordinates/deltas of magnitude <=1e9; button 0..3, buttons 0..7,
modifiers 0..15, key 0..1114111, scan 0..65535, repeat 0..1, and nonnegative
click_count/time_ns. Execution range failures are `adapter_error`.
Window/canvas generation comes from Screen, not client event identities.

Success contains `actions` (possibly `[]`), each with integer `id/kind`, boolean
`needs_paint/request_focus/consumed`, and float `value`. Transactional rollback
after partial execution is not provided.

### `ui.record` and library recording

`ui.record` requires UI_READ, positive `win: !i`, `mode: events|frames`, and
optional `max_bytes: !i` in 1..`limits.max_frame_bytes`. This is a recording
budget, not a cursor/page size. A matching registered Screen returns
`stream_required`; no Screen returns `not_implemented`. The transport does not
attach a streaming sink or push frames.

Separate library `start_recorder`/`write_record` APIs use a `StreamWriter`.
Records are `XAR1\t<sequence>\t<event|frame>\t<byte_length>\n<payload>\n`,
starting at sequence 1, with cumulative budget including headers/trailing LF.
Failed writes do not advance accounting. `surface_record` exports dimensions
only with `redacted=true`, not frame pixels. This is separate from XACP/1 and
CLI stdout recording.

## 8. Process operations and output capture

`proc.status` requires INFO and empty `args: {}`; data is the controlled process's
`pid: !i` and `state: OPEN`.

`proc.output` requires PROCESS and string `stream: stdout|stderr`. Optional
`since: !i` defaults to 0 and must be nonnegative; `max_bytes: !i` defaults to
`min(4096, max_frame_bytes/2)` and must be 1..`max_frame_bytes`. Wrong types,
streams, keys, or bounds are `schema_error`. With a valid envelope in OPEN,
these argument failures preserve connection and next id; envelope failures
still close.

XACP-enabled 64-bit POSIX generated hosts capture Xu runtime print/eprint and
fd 1/2 writes through its fd-write path. Successfully written bytes are retained
while original output passes through unchanged. This is not universal capture
of foreign/native or child-process writes. Unsupported/uninstrumented hosts
return `not_implemented`, including the current Windows capture seam and builds
without `--xacp` instrumentation. Library attachment alone does not add it.

Capture activates at XACP preflight/adapter initialization, not hello, and lasts
across sessions for the process lifetime. Each stream has a separate ring with
capacity from `XU_XACP_OUTPUT_BUFFER`: default 65536 bytes, ASCII decimal
4096..16777216, invalid input falling back to default. Initialization is
idempotent; first successful activation fixes capacity. Overflow drops oldest
bytes without waiting for ring space. Writers/snapshot copies use a runtime
mutex; serialization occurs outside the lock.

Data fields are `stream`, `since`, `count`, `total`, `base`, `dropped`,
`truncated`, `next_since`, and quoted `data`. Numeric fields use `!i`, and
`truncated` uses `!b`. Offsets/counts measure original bytes:

- `total` is cumulative captured bytes; retained range is `[base, total)` with
  `base = max(0, total - capacity)`.
- Requested `since < base` starts at `base`; returned `since` is that actual
  start, `dropped = base - requested_since`. Otherwise `dropped = 0`.
- `since == total` returns an empty page; `since > total` is `adapter_error`
  with `msg: "since beyond end of stream"`, consuming the id.
- `count <= max_bytes`; `next_since = since + count`;
  `truncated = next_since < total`. Continue with `since = next_since`.
- A single snapshot fixes `base/total` for the response. Escape expansion that
  would overflow the frame causes automatic page shrinking. Pages need not
  align to UTF-8 boundaries.

Quoted `data` preserves bytes: valid UTF-8 may remain literal; quotes,
backslashes, and whitespace use escapes; other control/non-UTF-8 bytes use
`\xHH`. These are original log bytes without tree/screenshot redaction or path
filtering. Reads are immediate snapshots, not long polls; new writes or dropped
history may occur between calls.

Stdio frames use a dedicated duplicate of stdout whose fd bypasses capture
hooks: protocol frames never enter output rings. It still writes to the same
stdout destination; capture does not suppress/reroute business logs, which must
stay out of the framed stream. `proc.output` executes in the control coroutine
without Screen registration or UI-owner polling.

## 9. Timed reads and Windows status

Stdio uses `os.fd_wait_read`; TCP uses `os.socket_wait_read`. Readiness consumes
no bytes and does not reserve them against another reader; callers must own
reads. POSIX supports redirected regular files and pipes.

Windows timed stdio reading is implemented:

- `sys_fd_peek_read` maps 0/1/2 to standard HANDLEs and accepts native HANDLEs
  from the file/pipe APIs. `GetFileType` selects the probe.
- Pipes use `PeekNamedPipe`: available bytes are ready, `ERROR_BROKEN_PIPE`
  is ready for EOF, empty live pipes are pending. Disk handles are always ready,
  including EOF.
- Character/console handles use `WaitForSingleObject(handle, 0)`. Signals can
  include non-key events and do not guarantee a full line for subsequent read.
  Console non-key wakeup/line-editing behavior is a **non-goal**, not a bounded
  console-read guarantee.
- `fd_wait_read` polls with approximately 1 ms sleeps (or the remaining positive
  timeout), recomputing from a monotonic start. It changes no handle mode and
  leaves no helper reader after timeout. Timeout 0 means infinite, negative
  means immediate probe, positive means relative nanoseconds. Unsupported
  types/probe failures propagate errors.

The code is present; **Windows hardware/runtime behavior has not been tested**
in the available evidence. General XACP stdio/Screen harnesses still skip
Windows; `fd_wait_read_smoke.py` includes native pipe/file coverage suitable for
running there. No sub-ms latency, overlapped I/O, helper-thread, or IOCP support
is claimed. TCP uses its separate socket path. Windows CLI `record`, output
capture, and POSIX screenshot files retain their separate limitations above.

## 10. Non-goals and unspecified behavior

The implemented transport provides no concurrent peers, request multiplexing,
push/subscriptions, automatic attachment, remote bind/TLS, wire permission
changes, arbitrary file paths, process spawn/termination operations, transactional
UI mutations, preemptive cancellation, OCR redaction, persistent output storage,
or unlimited/cross-process replay history. CLI `debug` is inspect-then-run, not
breakpoint debugging; CLI `record` copies bounded stdout (at most 1 MiB on
supported Unix hosts), not a UI event/frame stream.

Multiple controllers/Screens beyond the supported model, atomic multi-page
snapshots, write deadlines, crash-proof screenshot cleanup, id rollover, and
diagnostic wording not fixed above are unspecified. Discovery's operation list
and historical proposals do not imply additional operations or guarantees.

## 11. Source and evidence map

| Area | Implementation |
| --- | --- |
| Schema, limits, lifecycle, permissions, nonce registry | [mod.xu](../../src/xacp/mod.xu) |
| Framing, responses, dispatch, hello/idle clocks | [stdio.xu](../../src/xacp/stdio.xu) |
| Jobs, registration, request timer, tree/actions | [marshal.xu](../../src/xacp/marshal.xu), [ui.xu](../../src/xacp/ui.xu), [Screen](../../src/ui/widgets/screen.xu) |
| Redaction, PNG/files, private native sink | [screenshot.xu](../../src/xacp/screenshot.xu), [native bridge](../../src/ui/host/xu_ui_xacp.inc), [PNG bytes](../../src/image/png/bytes.xu) |
| Output snapshots and write hooks | [output.xu](../../src/xacp/output.xu), [runtime capture](../../src/cmd/compile/rt_xacp_output.xu), [runtime I/O](../../src/cmd/compile/rt_io.xu), [runtime files](../../src/cmd/compile/rt_file.xu) |
| Discovery, build/startup integration, CLI | [startup](../../src/cmd/compile/rt_startup.xu), [build](../../src/cmd/compile/driver_build.xu), [driver](../../src/cmd/compile/driver_entry.xu), [CLI/relay](../../src/cmd/xacp/main.xu) |
| Timed reads and Windows probe | [os/socket.xu](../../src/os/socket.xu), [rt_file.xu](../../src/cmd/compile/rt_file.xu) |

Executable regression contracts:
[xacp_smoke.py](../../scripts/xacp_smoke.py),
[xacp_screen_marshal_smoke.py](../../scripts/xacp_screen_marshal_smoke.py),
[xacp_screenshot_smoke.py](../../scripts/xacp_screenshot_smoke.py),
[xacp_proc_output_smoke.py](../../scripts/xacp_proc_output_smoke.py),
[fd_wait_read_smoke.py](../../scripts/fd_wait_read_smoke.py), with
[frame helpers](../../scripts/xacp_frame.py),
[frame fuzz](../../scripts/xacp_frame_fuzz.py), and
[cross-protocol probes](../../scripts/xacp_cross_protocol_probe.py).
Test source describes coverage, not proof of execution on every platform.

Historical specifications dated 2026-10-28:
[framing](../../docs/superpowers/specs/2026-10-28-xacp-length-prefix-framing-design.md),
[fuzz](../../docs/superpowers/specs/2026-10-28-xacp-frame-fuzz-design.md),
[request timeout](../../docs/superpowers/specs/2026-10-28-xacp-request-timeout-design.md),
[hello/idle timeout](../../docs/superpowers/specs/2026-10-28-xacp-idle-hello-timeout-design.md),
[ids/pagination](../../docs/superpowers/specs/2026-10-28-xacp-pagination-id-design.md),
[nonce replay](../../docs/superpowers/specs/2026-10-28-xacp-nonce-replay-design.md),
[Screen marshal](../../docs/superpowers/specs/2026-10-28-xacp-screen-marshal-design.md),
[screenshots](../../docs/superpowers/specs/2026-10-28-xacp-screenshot-redact-design.md),
[output](../../docs/superpowers/specs/2026-10-28-xacp-proc-output-design.md),
[Windows timed stdio](../../docs/superpowers/specs/2026-10-28-xacp-windows-timed-stdio-design.md).
