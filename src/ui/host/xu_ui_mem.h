// In-process UI mailbox — replaces %TEMP%\xu_ui_* file protocol for pack/oneexe.
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Resource limits for the in-process mailbox ABI.
 *
 * Slot names are stored in a fixed-size table entry.  The limit is the
 * number of bytes before the terminating NUL; callers must not rely on a
 * longer name being truncated (truncation would make two distinct names
 * alias one another).
 *
 * A mailbox value is intentionally bounded as well.  The bound keeps the
 * unsigned ABI length from turning an untrusted write into an unbounded host
 * allocation.  Larger binary assets should use the normal file path instead
 * of the :xu: in-process mailbox.
 */
#define XU_UI_MEM_MAX_NAME 95u
#define XU_UI_MEM_MAX_PAYLOAD (64u * 1024u * 1024u)
#define XU_UI_EMIT_MAX_BYTES (1024u * 1024u)
#define XU_UI_EMIT_MAX_RECORDS 256u

#ifdef __linux__
/* Passed to xu_app_start_hosted by the pack shim. Creates a detached libc
 * thread with its own TLS; the Xu scheduler entry owns its lifetime. */
int xu_ui_runtime_start_worker(void *(*entry)(void *), void *argument);
#endif

/* Take one complete, length-delimited WebView notification. Caller free().
 * Supports the old RS slot as a fallback; no get/clear race or fixed buffer. */
char *xu_ui_emit_take(unsigned *out_len);
void xu_ui_emit_clear(void);
void xu_ui_emit_start(void);
void xu_ui_emit_close(void);

/* Slot API (name like "xu_ui_title.txt"). Overwrite / read / append line. */
void xu_ui_mem_set(const char *name, const char *body);
void xu_ui_mem_set_n(const char *name, const char *body, unsigned body_len);
/* Returns bytes copied (excluding NUL), or -1 if missing/invalid. Always
 * NUL-terminates when n>0.  A successful mailbox value is at most
 * XU_UI_MEM_MAX_PAYLOAD bytes, so the int return cannot overflow. */
int xu_ui_mem_get(const char *name, char *out, unsigned n);
/* Append body (+ optional "\n" if add_nl != 0). */
void xu_ui_mem_append(const char *name, const char *body, int add_nl);
void xu_ui_mem_clear(const char *name);
/* Atomically detach the whole slot, with no fixed consumer buffer. Returns an
 * owned NUL-terminated allocation (caller free), or NULL for a missing slot.
 * Writers after this operation append to a new slot, never the detached one. */
char *xu_ui_mem_take(const char *name, unsigned *out_len);

/* Wait until slot `name` is nonempty, or timeout_ms elapses.
 * Returns 1 if nonempty, 0 on timeout, -1 on bad args.
 * Writers (set/append/clear) wake waiters. */
int xu_ui_mem_wait_nonempty(const char *name, int timeout_ms);

/* Wait until slot `name` body differs from `old_body` (NULL/"" = empty), or timeout.
 * Returns 1 if changed, 0 on timeout, -1 on bad args. */
int xu_ui_mem_wait_ne(const char *name, const char *old_body, int timeout_ms);

/* Park the invoke worker until a sync/legacy invoke is pending, or timeout.
 * Shell events have a separate consumer. Returns 1 if ready, 0 on timeout.
 * Also via write_file(":xu:/__ipc_wait", "250"). */
int xu_ui_mem_wait_ipc(int timeout_ms);

/* Host UI thread: register to drain cmds ASAP when Xu writes xu_ui_cmd.txt.
 * Also via write_file(":xu:/__host_kick", "1"). */
typedef void (*xu_ui_host_kick_fn)(void);
void xu_ui_host_set_kick(xu_ui_host_kick_fn fn);
void xu_ui_host_kick(void);

/* Pack entry registers an exact relative-path reader before Xu starts. Returned
 * bytes must remain immutable and valid for the process lifetime. NULL=missing;
 * a non-NULL pointer with length zero is a present empty asset. */
typedef const unsigned char *(*xu_ui_asset_reader_fn)(const char *, unsigned *);
void xu_ui_set_asset_reader(xu_ui_asset_reader_fn reader);

/* Scheme invoke: Host blocks in xu_ui_invoke_sync; Xu worker
 * read_file(":xu:/__invoke_take") / write_file(":xu:/__invoke_reply", …).
 * No xu_ui_ipc_req.txt / resp.txt round-trip for this path.
 * Returns malloc'd XUN response (caller free); never NULL. */
char *xu_ui_invoke_sync(const char *req_xun);

/* Runtime intercept for Xu write_file/read_file when path is ":xu:/…" or
 * ":xu:…".  A syntactically virtual path is handled even when its slot name
 * is invalid; in that case reads observe an empty value and try_write stores
 * zero in out_n.  On success out_n is the number of bytes accepted. */
int xu_ui_mem_try_write(const char *path_z, const void *data, unsigned data_len, unsigned *out_n);
int xu_ui_mem_try_read_len(const char *path_z, unsigned *out_len);
int xu_ui_mem_try_read_copy(const char *path_z, void *out, unsigned cap);

/* True if path is the virtual ":xu:" mailbox. */
int xu_ui_mem_is_path(const char *path_z);

#ifdef __cplusplus
}
#endif
