// In-process string slots for Xu UI host ↔ worker (no TEMP xu_ui_* directory).

#include "xu_ui_mem.h"
#include "xu_draw_frame.h"
#include "xu_ui_display_list.h"
#include "xu_ui_requests.h"
#include "xu_ui_files.h"

#include <stdint.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <atomic>
#include <chrono>

// Observe notifications across the predicate-to-park gap without taking the
// slot/invoke locks under the condition-variable mutex.
static std::atomic<uint64_t> g_wait_epoch{0};
static const char g_ui_licenses[] = "Xu UI: libgrapheme 3.0.0 / Unicode 17.0.0\n\n"
#include "third_party/libgrapheme/notice.inc"
;

#ifdef _WIN32
extern "C" __attribute__((weak)) void xu_trace(const char *msg);
static void do_trace(const char *msg) {
  if (xu_trace) xu_trace(msg);
}
#else
static void do_trace(const char *) {}
#endif

#ifdef _WIN32
#include <windows.h>
static SRWLOCK g_lock = SRWLOCK_INIT;
static CRITICAL_SECTION g_wait_cs;
static CONDITION_VARIABLE g_wait_cv;
static HANDLE g_wait_event = NULL;
static LONG g_wait_init = 0;
static void lock_w(void) { AcquireSRWLockExclusive(&g_lock); }
static void unlock_w(void) { ReleaseSRWLockExclusive(&g_lock); }
static void lock_r(void) { AcquireSRWLockShared(&g_lock); }
static void unlock_r(void) { ReleaseSRWLockShared(&g_lock); }
static void wait_init(void) {
  if (InterlockedCompareExchange(&g_wait_init, 1, 0) == 0) {
    InitializeCriticalSection(&g_wait_cs);
    InitializeConditionVariable(&g_wait_cv);
    g_wait_event = CreateEventA(NULL, FALSE, FALSE, NULL);
    InterlockedExchange(&g_wait_init, 2);
  } else {
    while (InterlockedCompareExchange(&g_wait_init, 2, 2) != 2) Sleep(0);
  }
}
static void wake_waiters(void) {
  wait_init();
  EnterCriticalSection(&g_wait_cs);
  g_wait_epoch.fetch_add(1, std::memory_order_release);
  WakeAllConditionVariable(&g_wait_cv);
  if (g_wait_event) SetEvent(g_wait_event);
  LeaveCriticalSection(&g_wait_cs);
}
#else
#include <errno.h>
#include <pthread.h>
#include <sys/time.h>
#include <time.h>
static pthread_rwlock_t g_lock = PTHREAD_RWLOCK_INITIALIZER;
static pthread_mutex_t g_wait_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_wait_cv;
static pthread_once_t g_wait_once = PTHREAD_ONCE_INIT;
static void wait_init_once(void) {
  pthread_condattr_t attributes;
  pthread_condattr_init(&attributes);
#if !defined(__APPLE__)
  pthread_condattr_setclock(&attributes, CLOCK_MONOTONIC);
#endif
  pthread_cond_init(&g_wait_cv, &attributes);
  pthread_condattr_destroy(&attributes);
}
static void wait_init(void) { pthread_once(&g_wait_once, wait_init_once); }
#ifdef __linux__
int xu_ui_runtime_start_worker(void *(*entry)(void *), void *argument) {
  if (!entry) return 0;
  pthread_attr_t attributes;
  if (pthread_attr_init(&attributes) != 0) return 0;
  int result = pthread_attr_setdetachstate(&attributes, PTHREAD_CREATE_DETACHED);
  pthread_t thread;
  if (result == 0) result = pthread_create(&thread, &attributes, entry, argument);
  pthread_attr_destroy(&attributes);
  return result == 0 ? 1 : 0;
}
#endif
static void lock_w(void) { pthread_rwlock_wrlock(&g_lock); }
static void unlock_w(void) { pthread_rwlock_unlock(&g_lock); }
static void lock_r(void) { pthread_rwlock_rdlock(&g_lock); }
static void unlock_r(void) { pthread_rwlock_unlock(&g_lock); }
static void wake_waiters(void) {
  wait_init();
  pthread_mutex_lock(&g_wait_mu);
  g_wait_epoch.fetch_add(1, std::memory_order_release);
  pthread_cond_broadcast(&g_wait_cv);
  pthread_mutex_unlock(&g_wait_mu);
}
#endif

long long xu_ui_input_now_ns(void) {
#ifdef _WIN32
  LARGE_INTEGER counter, frequency;
  if (!QueryPerformanceCounter(&counter) || !QueryPerformanceFrequency(&frequency) || frequency.QuadPart <= 0) return 0;
  return (counter.QuadPart / frequency.QuadPart) * 1000000000LL +
         (counter.QuadPart % frequency.QuadPart) * 1000000000LL / frequency.QuadPart;
#else
  struct timespec now{};
  if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) return 0;
  return (long long)now.tv_sec * 1000000000LL + now.tv_nsec;
#endif
}

/* ---- Sync scheme invoke (Host ↔ Xu worker). Not slot/file shaped. ---- */
enum { INV_IDLE = 0, INV_REQ = 1, INV_BUSY = 2, INV_RESP = 3 };

#ifdef _WIN32
static CRITICAL_SECTION g_inv_cs;
static CONDITION_VARIABLE g_inv_cv;
static HANDLE g_inv_event = NULL;
static LONG g_inv_init = 0;
static void inv_init(void) {
  if (InterlockedCompareExchange(&g_inv_init, 1, 0) == 0) {
    InitializeCriticalSection(&g_inv_cs);
    InitializeConditionVariable(&g_inv_cv);
    g_inv_event = CreateEventA(NULL, FALSE, FALSE, NULL);
    InterlockedExchange(&g_inv_init, 2);
  } else {
    while (InterlockedCompareExchange(&g_inv_init, 2, 2) != 2) Sleep(0);
  }
}
static void inv_lock(void) { inv_init(); EnterCriticalSection(&g_inv_cs); }
static void inv_unlock(void) { LeaveCriticalSection(&g_inv_cs); }
static void inv_signal(void) {
  inv_init();
  WakeAllConditionVariable(&g_inv_cv);
  if (g_inv_event) SetEvent(g_inv_event);
}
static void inv_wait(DWORD ms) {
  DWORD wait_ms = (ms == 0) ? 20 : (ms > 20 ? 20 : ms);
  LeaveCriticalSection(&g_inv_cs);
  WaitForSingleObject(g_inv_event, wait_ms);
  EnterCriticalSection(&g_inv_cs);
}
#else
static pthread_mutex_t g_inv_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_inv_cv = PTHREAD_COND_INITIALIZER;
static void inv_lock(void) { pthread_mutex_lock(&g_inv_mu); }
static void inv_unlock(void) { pthread_mutex_unlock(&g_inv_mu); }
static void inv_signal(void) { pthread_cond_broadcast(&g_inv_cv); }
static void inv_wait_deadline(const struct timespec *dl) {
  pthread_cond_timedwait(&g_inv_cv, &g_inv_mu, dl);
}
#endif

static char *g_inv_req = NULL;
static unsigned g_inv_req_len = 0;
static char *g_inv_resp = NULL;
static unsigned g_inv_resp_len = 0;
static int g_inv_state = INV_IDLE;

#include "xu_ui_web_requests.inc"

static int invoke_pending_unlocked(void) { return g_inv_state == INV_REQ; }

static int invoke_pending(void) {
  int p;
  inv_lock();
  p = invoke_pending_unlocked();
  inv_unlock();
  return p;
}

/* Keep all length arithmetic checked before it reaches malloc/memcpy.  The
 * mailbox ABI uses unsigned (32-bit) lengths, while size_t is 32-bit on some
 * supported hosts and 64-bit on others. */
static int size_add_checked(size_t a, size_t b, size_t *out) {
  if (!out || b > (size_t)-1 - a) return 0;
  *out = a + b;
  return 1;
}

static int u32_add_checked(unsigned a, unsigned b, unsigned *out) {
  if (!out || b > UINT_MAX - a) return 0;
  *out = a + b;
  return 1;
}

static int u32_add3_checked(unsigned a, unsigned b, unsigned c, unsigned *out) {
  unsigned ab;
  return u32_add_checked(a, b, &ab) && u32_add_checked(ab, c, out);
}

/* Keep every mailbox allocation below a deliberate resource ceiling.  The
 * public ABI carries lengths as unsigned, so integer-overflow checks alone
 * would still permit a caller to request a multi-gigabyte allocation. */
static int payload_len_allowed(unsigned len) {
  return len <= (unsigned)XU_UI_MEM_MAX_PAYLOAD;
}

static int alloc_bytes_for_u32(unsigned len, size_t *out) {
  return payload_len_allowed(len) &&
         size_add_checked((size_t)len, (size_t)1, out);
}

static int cstr_len_u32(const char *s, unsigned *out) {
  size_t n;
  if (!out) return 0;
  if (!s) {
    *out = 0;
    return 1;
  }
  /* All callers eventually put this string in a bounded mailbox buffer.
   * Stop at the same limit instead of letting an attacker force an
   * unbounded strlen walk before the size check. */
  for (n = 0; n <= (size_t)XU_UI_MEM_MAX_PAYLOAD; n++) {
    if (s[n] == '\0') {
      *out = (unsigned)n;
      return 1;
    }
  }
  return 0;
}

static long long xu_now_ms(void) {
#ifdef _WIN32
  return (long long)GetTickCount64();
#else
  struct timeval tv;
  gettimeofday(&tv, NULL);
  return (long long)tv.tv_sec * 1000LL + (long long)tv.tv_usec / 1000LL;
#endif
}

static char *dup_cstr_n(const char *s, unsigned n) {
  size_t bytes;
  char *p;
  if (!payload_len_allowed(n) || (n && !s)) return NULL;
  if (!alloc_bytes_for_u32(n, &bytes)) return NULL;
  p = (char *)malloc(bytes);
  if (!p) return NULL;
  if (n) memcpy(p, s, n);
  p[n] = 0;
  return p;
}

static char *dup_cstr_literal(const char *s) {
  unsigned n;
  if (!cstr_len_u32(s, &n)) return NULL;
  return dup_cstr_n(s, n);
}

char *xu_ui_invoke_sync(const char *req_xun) {
  const char *req = req_xun ? req_xun : "";
  unsigned n;
  char *req_copy;
  char *out;
  long long ms;
#ifdef _WIN32
  ULONGLONG t0 = GetTickCount64();
#else
  struct timeval t0, t1;
  gettimeofday(&t0, NULL);
#endif
  if (!cstr_len_u32(req, &n)) {
    return dup_cstr_literal("ok: false\nerror: !s request too large\n");
  }
  req_copy = dup_cstr_n(req, n);
  if (!req_copy) {
    return dup_cstr_literal("ok: false\nerror: !s oom\n");
  }

  inv_lock();
  /* Serialize: one in-flight scheme invoke. */
  while (g_inv_state != INV_IDLE) {
#ifdef _WIN32
    inv_wait(50);
#else
    {
      struct timeval tv;
      struct timespec dl;
      gettimeofday(&tv, NULL);
      dl.tv_sec = tv.tv_sec;
      dl.tv_nsec = (long)tv.tv_usec * 1000L + 50000000L;
      if (dl.tv_nsec >= 1000000000L) {
        dl.tv_sec += 1;
        dl.tv_nsec -= 1000000000L;
      }
      inv_wait_deadline(&dl);
    }
#endif
  }
  free(g_inv_req);
  g_inv_req = req_copy;
  g_inv_req_len = n;
  free(g_inv_resp);
  g_inv_resp = NULL;
  g_inv_resp_len = 0;
  g_inv_state = INV_REQ;
  inv_unlock();
  if (getenv("XU_UI_TIMING") && getenv("XU_UI_TIMING")[0] == '1') {
    fprintf(stderr, "xu_ui_timing %lld posted\n", xu_now_ms());
  }
  wake_waiters(); /* Xu parked in wait_ipc */

  inv_lock();
  {
#ifdef _WIN32
    DWORD start = GetTickCount();
    for (;;) {
      if (g_inv_state == INV_RESP) break;
      if (GetTickCount() - start >= 5000u) break;
      inv_wait(50);
    }
#else
    struct timeval tv0;
    struct timespec deadline;
    gettimeofday(&tv0, NULL);
    deadline.tv_sec = tv0.tv_sec + 5;
    deadline.tv_nsec = (long)tv0.tv_usec * 1000L;
    for (;;) {
      struct timeval now;
      if (g_inv_state == INV_RESP) break;
      gettimeofday(&now, NULL);
      if (now.tv_sec > deadline.tv_sec ||
          (now.tv_sec == deadline.tv_sec && (long)now.tv_usec * 1000L >= deadline.tv_nsec))
        break;
      inv_wait_deadline(&deadline);
    }
#endif
  }
#ifdef _WIN32
  ms = (long long)(GetTickCount64() - t0);
#else
  gettimeofday(&t1, NULL);
  ms = ((long long)t1.tv_sec - (long long)t0.tv_sec) * 1000LL +
       ((long long)t1.tv_usec - (long long)t0.tv_usec) / 1000LL;
#endif
  if (getenv("XU_UI_TIMING") && getenv("XU_UI_TIMING")[0] == '1') {
    fprintf(stderr, "xu_ui_timing wait_done state=%d elapsed=%lldms\n", g_inv_state, ms);
  }
  if (g_inv_state == INV_RESP && g_inv_resp) {
    out = g_inv_resp;
    g_inv_resp = NULL;
    g_inv_resp_len = 0;
  } else {
    free(g_inv_resp);
    g_inv_resp = NULL;
    g_inv_resp_len = 0;
    out = dup_cstr_literal("ok: false\nerror: !s invoke timeout\n");
  }
  free(g_inv_req);
  g_inv_req = NULL;
  g_inv_req_len = 0;
  g_inv_state = INV_IDLE;
  inv_signal();
  inv_unlock();
  if (!out) out = dup_cstr_literal("ok: false\nerror: !s oom\n");
#ifdef _WIN32
  ms = (long long)(GetTickCount64() - t0);
#else
  gettimeofday(&t1, NULL);
  ms = ((long long)t1.tv_sec - (long long)t0.tv_sec) * 1000LL +
       ((long long)t1.tv_usec - (long long)t0.tv_usec) / 1000LL;
#endif
  if (getenv("XU_UI_TIMING") && getenv("XU_UI_TIMING")[0] == '1') {
    fprintf(stderr, "xu_ui_timing c_sync=%lldms\n", ms);
  }
  return out;
}

static int invoke_try_take_len(unsigned *out_len) {
  inv_lock();
  if (g_inv_state != INV_REQ) {
    if (out_len) *out_len = 0;
    inv_unlock();
    return 1; /* handled as empty */
  }
  if (out_len) *out_len = g_inv_req_len;
  inv_unlock();
  return 1;
}

static int invoke_try_take_copy(void *out, unsigned cap) {
  unsigned copy;
  inv_lock();
  if (g_inv_state != INV_REQ || !out || cap == 0) {
    if (out && cap) ((char *)out)[0] = 0;
    inv_unlock();
    return 1;
  }
  copy = g_inv_req_len;
  if (copy >= cap) copy = cap - 1;
  if (copy && g_inv_req) memcpy(out, g_inv_req, copy);
  ((char *)out)[copy] = 0;
  g_inv_state = INV_BUSY;
  inv_unlock();
  if (getenv("XU_UI_TIMING") && getenv("XU_UI_TIMING")[0] == '1') {
    fprintf(stderr, "xu_ui_timing %lld take len=%u\n", xu_now_ms(), copy);
  }
  return 1;
}

/* Return non-zero only when a response was committed to the rendezvous.
 * A syntactically virtual write is still handled by the caller even when this
 * returns zero; the distinction lets the ABI report an accurate out_n value
 * instead of claiming that an OOM/late reply consumed the input. */
static int invoke_try_reply(const void *data, unsigned data_len) {
  char *copy;
  unsigned stored_len = data_len;
  inv_lock();
  if (g_inv_state != INV_BUSY && g_inv_state != INV_REQ) {
    inv_unlock();
    if (getenv("XU_UI_TIMING") && getenv("XU_UI_TIMING")[0] == '1') {
      fprintf(stderr, "xu_ui_timing reply_swallow state\n");
    }
    return 0; /* swallow, nothing accepted */
  }
  /* A non-zero length with a null pointer is malformed at the ABI boundary;
   * turn it into an explicit error response instead of reading from a fake
   * empty string (which used to make the lengths disagree). */
  if (!payload_len_allowed(data_len)) {
    copy = dup_cstr_literal("ok: false\nerror: !s response too large\n");
    if (copy) {
      (void)cstr_len_u32(copy, &stored_len);
    }
  } else if (data_len && !data) {
    copy = dup_cstr_literal("ok: false\nerror: !s invalid response buffer\n");
    if (copy) {
      (void)cstr_len_u32(copy, &stored_len);
    }
  } else {
    copy = dup_cstr_n((const char *)data, data_len);
  }
  if (!copy) {
    inv_unlock();
    return 0;
  }
  free(g_inv_resp);
  g_inv_resp = copy;
  g_inv_resp_len = stored_len;
  g_inv_state = INV_RESP;
  inv_signal();
  inv_unlock();
  if (getenv("XU_UI_TIMING") && getenv("XU_UI_TIMING")[0] == '1') {
    fprintf(stderr, "xu_ui_timing %lld reply len=%u\n", xu_now_ms(), data_len);
  }
  return 1;
}

enum { XU_UI_MEM_MAX = 128, XU_UI_MEM_NAME = XU_UI_MEM_MAX_NAME + 1u };

struct XuUiSlot {
  char name[XU_UI_MEM_NAME];
  char *body;
  unsigned len;
  size_t cap;
  int used;
};

static XuUiSlot g_slots[XU_UI_MEM_MAX];

/* Normalize a slot name without ever truncating it.  The old snprintf-based
 * path stored only the first XU_UI_MEM_MAX_NAME bytes, making e.g. two long
 * names that differed after that point address the same slot.  Rejecting the
 * name keeps the operation fail-closed and makes lookup/store semantics
 * identical.  The bounded scan also avoids walking an unbounded string when
 * this function is called from the virtual-path ABI. */
static const char *slot_key(const char *name) {
  size_t skip;
  size_t len;
  if (!name) return NULL;
  for (skip = 0; skip < (size_t)XU_UI_MEM_NAME; skip++) {
    if (name[skip] != '/' && name[skip] != '\\') break;
  }
  if (skip >= (size_t)XU_UI_MEM_NAME) return NULL;
  name += skip;
  for (len = 0; len < (size_t)XU_UI_MEM_NAME; len++) {
    if (name[len] == '\0') break;
  }
  if (len == 0 || len >= (size_t)XU_UI_MEM_NAME) return NULL;
  return name;
}

static XuUiSlot *find_slot_unlocked(const char *key) {
  unsigned i;
  if (!key || !key[0]) return NULL;
  for (i = 0; i < XU_UI_MEM_MAX; i++) {
    if (g_slots[i].used && strcmp(g_slots[i].name, key) == 0) return &g_slots[i];
  }
  return NULL;
}

static XuUiSlot *alloc_slot_unlocked(const char *key) {
  unsigned i;
  XuUiSlot *s;
  size_t key_len;
  if (!key) return NULL;
  for (key_len = 0; key_len < (size_t)XU_UI_MEM_NAME; key_len++) {
    if (key[key_len] == '\0') break;
  }
  if (key_len == 0 || key_len >= (size_t)XU_UI_MEM_NAME) return NULL;
  s = find_slot_unlocked(key);
  if (s) return s;
  for (i = 0; i < XU_UI_MEM_MAX; i++) {
    if (!g_slots[i].used) {
      s = &g_slots[i];
      memset(s, 0, sizeof(*s));
      memcpy(s->name, key, key_len + 1u);
      s->used = 1;
      return s;
    }
  }
  return NULL;
}

static int slot_set_unlocked(XuUiSlot *s, const char *body, unsigned body_len) {
  size_t bytes;
  char *nbuf;
  if (!s || !payload_len_allowed(body_len) || (body_len && !body)) return 0;
  if (!body) body = "";
  if (!alloc_bytes_for_u32(body_len, &bytes)) return 0;
  nbuf = (char *)malloc(bytes);
  if (!nbuf) return 0;
  if (body_len) memcpy(nbuf, body, body_len);
  nbuf[body_len] = 0;
  free(s->body);
  s->body = nbuf;
  s->len = body_len;
  s->cap = bytes;
  return 1;
}

static int slot_nonempty(const char *key) {
  XuUiSlot *s;
  int ok;
  lock_r();
  s = find_slot_unlocked(key);
  ok = (s && s->body && s->len > 0) ? 1 : 0;
  unlock_r();
  return ok;
}

void xu_ui_mem_set(const char *name, const char *body) {
  const char *b = body ? body : "";
  unsigned n;
  if (!cstr_len_u32(b, &n)) return;
  xu_ui_mem_set_n(name, b, n);
}

/* Store a normalized key and report whether the value was actually accepted.
 * The public set API predates an error return, so it remains void; virtual
 * writes use this helper to return an accurate byte count to the caller. */
static int slot_set_key(const char *key, const char *body, unsigned body_len) {
  XuUiSlot *s;
  int ok;
  if (!key || !payload_len_allowed(body_len) || (body_len && !body)) return 0;
  lock_w();
  s = alloc_slot_unlocked(key);
  ok = slot_set_unlocked(s, body, body_len);
  unlock_w();
  if (!ok) return 0;
  wake_waiters();
  /* Nonempty shell cmd → wake UI thread. Empty clear must NOT kick (drain loop). */
  if (key && body_len > 0 && strcmp(key, "xu_ui_cmd.txt") == 0) xu_ui_host_kick();
  return 1;
}

void xu_ui_mem_set_n(const char *name, const char *body, unsigned body_len) {
  (void)slot_set_key(slot_key(name), body, body_len);
}

static std::atomic<xu_ui_host_kick_fn> g_host_kick{NULL};
static std::atomic<bool> g_host_kick_pending{false};

void xu_ui_host_set_kick(xu_ui_host_kick_fn fn) {
  g_host_kick.store(fn);
  g_host_kick_pending.store(false);
  if (fn && slot_nonempty("xu_ui_cmd.txt")) xu_ui_host_kick();
}

void xu_ui_host_kick(void) {
  xu_ui_host_kick_fn fn = g_host_kick.load();
  if (fn && !g_host_kick_pending.exchange(true)) fn();
}

static int slot_body_eq(const char *key, const char *old_body) {
  XuUiSlot *s;
  const char *want = old_body ? old_body : "";
  unsigned wlen;
  int eq;
  if (!cstr_len_u32(want, &wlen) || !payload_len_allowed(wlen)) return 0;
  lock_r();
  s = find_slot_unlocked(key);
  if (!s || !s->body) {
    eq = (wlen == 0) ? 1 : 0;
  } else if (s->len != wlen) {
    eq = 0;
  } else {
    eq = (wlen == 0 || memcmp(s->body, want, wlen) == 0) ? 1 : 0;
  }
  unlock_r();
  return eq;
}

int xu_ui_mem_get(const char *name, char *out, unsigned n) {
  const char *key = slot_key(name);
  XuUiSlot *s;
  unsigned copy;
  if (!out || n == 0) return -1;
  out[0] = 0;
  lock_r();
  s = find_slot_unlocked(key);
  if (!s || !s->body) {
    unlock_r();
    return -1;
  }
  copy = s->len;
  if (copy >= n) copy = n - 1;
  if (copy) memcpy(out, s->body, copy);
  out[copy] = 0;
  unlock_r();
  return (int)copy;
}

static int slot_append_unlocked(const char *key, const void *body, unsigned blen, int add_nl) {
  const char *b = (const char *)body;
  XuUiSlot *s;
  unsigned nlen;
  size_t bytes;
  char *nbuf;
  if (!key || !payload_len_allowed(blen) || (blen && !b)) return 0;
  s = alloc_slot_unlocked(key);
  if (!s) {
    return 0;
  }
  unsigned keep = s->len;
  // Coalesce only consecutive moves for the same window/canvas. A button,
  // key, cancel or any other event is an ordering barrier.
  bool move1 = blen >= 9 && memcmp(b, "input\t74\t", 9) == 0;
  bool move2 = blen >= 10 && memcmp(b, "input2\t74\t", 10) == 0;
  if (add_nl && strcmp(key, "xu_ui_shell_event.txt") == 0 && blen <= 512 &&
      (move1 || move2) && s->len && s->body[s->len - 1] == '\n') {
    unsigned prefix = 0, tabs = 0;
    unsigned identity_tabs = move2 ? 5u : 4u;
    while (prefix < blen && tabs < identity_tabs) if (b[prefix++] == '\t') ++tabs;
    unsigned start = s->len - 1, scanned = 0;
    while (start && s->body[start - 1] != '\n' && scanned++ <= 512) --start;
    if (tabs == identity_tabs && scanned <= 512 && s->len - start >= prefix &&
        memcmp(s->body + start, b, prefix) == 0) keep = start;
  }
  if (!u32_add3_checked(keep, blen, add_nl ? 1u : 0u, &nlen) ||
      !payload_len_allowed(nlen) ||
      !alloc_bytes_for_u32(nlen, &bytes)) {
    return 0;
  }
  if (bytes > s->cap) {
    size_t capacity = s->cap ? s->cap : 256u;
    const size_t ceiling = (size_t)XU_UI_MEM_MAX_PAYLOAD + 1u;
    while (capacity < bytes) {
      capacity = capacity > ceiling / 2u ? ceiling : capacity * 2u;
    }
    nbuf = (char *)realloc(s->body, capacity);
    if (!nbuf) {
      return 0;
    }
    s->body = nbuf;
    s->cap = capacity;
  }
  nbuf = s->body;
  if (blen) memcpy(nbuf + keep, b, blen);
  if (add_nl) nbuf[keep + blen] = '\n';
  nbuf[nlen] = 0;
  s->len = nlen;
  return 1;
}

static int slot_append_key(const char *key, const void *body, unsigned blen, int add_nl) {
  lock_w();
  int ok = slot_append_unlocked(key, body, blen, add_nl);
  unlock_w();
  if (ok) {
    wake_waiters();
    if (blen > 0 && key && strcmp(key, "xu_ui_cmd.txt") == 0) xu_ui_host_kick();
  }
  return ok;
}

struct XuDrawPending {
  XuUiFrameLease *lease; uint64_t ticket;
  unsigned window_id, canvas_id, generation;
};
static XuDrawPending g_draw_pending[XU_DRAW_FRAME_MAX_PENDING];
static uint64_t g_draw_ticket = 0;
struct XuCanvasIdentity { unsigned window_id, canvas_id, generation; };
static XuCanvasIdentity g_canvases[XU_DRAW_MAX_CANVASES];
static unsigned g_canvas_generation = 0;
static bool g_canvas_started = false;

#include "xu_ui_images.inc"
#include "xu_ui_gradients.inc"
#include "xu_ui_composite.inc"
#include "xu_ui_text.inc"
#include "xu_ui_paths.inc"

static XuUiDisplayList *display_list_snapshot(uint64_t,unsigned,unsigned);
struct XuFramePath { unsigned offset=0,length=0; std::string prepared; };
struct XuUiFrameLease {
  void *body;
  unsigned len;
  XuUiBitmap *images[XU_UI_IMAGE_MAX_COUNT];
  std::unordered_map<uint64_t, XuUiText *> texts;
  std::vector<XuFramePath> paths;
  XuUiDisplayList *lists[XU_UI_LIST_MAX_COUNT];
};
const void *xu_ui_frame_data(const XuUiFrameLease *frame, unsigned *out_len) {
  if (out_len) *out_len = frame ? frame->len : 0;
  return frame ? frame->body : NULL;
}
XuUiBitmap *xu_ui_frame_bitmap(const XuUiFrameLease *frame, uint64_t id) {
  if (!frame || !id) return NULL;
  auto *bitmap = frame->images[id & (XU_UI_IMAGE_MAX_COUNT - 1u)];
  return bitmap && bitmap->id == id ? bitmap : NULL;
}
XuUiText *xu_ui_frame_text(const XuUiFrameLease *frame, uint64_t id) {
  if (!frame || !id) return NULL;
  auto at = frame->texts.find(id);
  return at == frame->texts.end() ? NULL : at->second;
}
const void *xu_ui_frame_path(const XuUiFrameLease *frame,unsigned offset,unsigned *length) {
  if(length) *length=0;
  if(!frame) return NULL;
  auto at=std::lower_bound(frame->paths.begin(),frame->paths.end(),offset,
    [](const XuFramePath &path,unsigned value) { return path.offset<value; });
  if(at==frame->paths.end() || at->offset!=offset) return NULL;
  if(length) *length=at->prepared.empty() ? at->length : (unsigned)at->prepared.size();
  return at->prepared.empty() ? (const char *)frame->body+offset+8 : at->prepared.data();
}
static bool draw_prepare_paths(XuUiFrameLease *frame) {
  unsigned cursor=32,work=262144,bytes=0; XuDrawCommand command;
  try {
    while(cursor<frame->len) {
      unsigned offset=cursor;
      if(xdf_next(frame->body,frame->len,&cursor,&command)!=1) return false;
      if(command.opcode!=XDF_PATH) continue;
      XuFramePath path; path.offset=offset; path.length=command.text_len;
      if(!xu_path::prepare(command.text,command.text_len,path.prepared,work) || path.prepared.size()>XU_DRAW_FRAME_MAX_BYTES-bytes) return false;
      bytes+=(unsigned)path.prepared.size(); frame->paths.push_back(std::move(path));
    }
  } catch(...) { return false; }
  return cursor==frame->len;
}
void xu_ui_frame_release(XuUiFrameLease *frame) {
  if (!frame) return;
  for (auto *bitmap : frame->images) xu_ui_bitmap_release(bitmap);
  for (const auto &entry : frame->texts) xu_ui_text_release(entry.second);
  for(auto *list:frame->lists)xu_ui_display_list_release(list);
  free(frame->body); delete frame;
}
// Called under the registry lock: all uses of a resource in one frame observe
// the same immutable version, even while another thread uploads an update.
static bool draw_snapshot_images(XuUiFrameLease *frame, unsigned canvas, unsigned generation) {
  unsigned cursor = 32; XuDrawCommand command;
  while (cursor<frame->len) {
    auto *record=(const unsigned char *)frame->body+cursor;
    unsigned opcode=xdf_u16(record);
    // The owned frame was already validated. Do not rescan large paths/text
    // while holding the global resource registry lock.
    if(opcode!=XDF_IMAGE && opcode!=XDF_TEXT_LAYOUT && opcode!=XDF_DISPLAY_LIST) { cursor+=xdf_u32(record+4); continue; }
    if(xdf_next(frame->body,frame->len,&cursor,&command)!=1) return false;
    if(command.opcode==XDF_DISPLAY_LIST) {
      auto *&list=frame->lists[command.image_id&(XU_UI_LIST_MAX_COUNT-1)];
      if(!list)list=display_list_snapshot(command.image_id,canvas,generation);
      // Direct live IDs cannot collide in their registry slot.
      if(!list || xu_ui_frame_list(frame,command.image_id)!=list)return false;
      continue;
    }
    if (command.opcode == XDF_TEXT_LAYOUT) {
      if (frame->texts.find(command.image_id) == frame->texts.end()) {
        auto *text = text_snapshot(command.image_id, canvas, generation);
        if (!text) return false;
        try { frame->texts.emplace(command.image_id, text); }
        catch (...) { xu_ui_text_release(text); return false; }
      }
      continue;
    }
    if (command.opcode != XDF_IMAGE) continue;
    auto *&bitmap = frame->images[command.image_id & (XU_UI_IMAGE_MAX_COUNT - 1u)];
    if (!bitmap) bitmap = image_snapshot(command.image_id, canvas, generation);
    if (!bitmap || bitmap->id != command.image_id ||
        command.values[0] + command.values[2] > bitmap->width ||
        command.values[1] + command.values[3] > bitmap->height) return false;
  }
  return cursor == frame->len;
}

#include "xu_ui_display_lists.inc"
#include "xu_ui_rect_batch.inc"

static std::atomic<XuUiSurfaceRender> g_surface_render{NULL};
static std::atomic<unsigned> g_surface_flags{0};
int xu_ui_surface_set_backend_v2(XuUiSurfaceRender render,unsigned flags) {
  if(!render || (flags&~1u))return 0;
  lock_w();auto current=g_surface_render.load();
  bool valid=!current || (current==render && g_surface_flags.load()==flags);
  if(valid && !current) {g_surface_flags.store(flags);g_surface_render.store(render);}
  unlock_w();return valid;
}
int xu_ui_surface_set_backend(XuUiSurfaceRender render) {return xu_ui_surface_set_backend_v2(render,0);}
static XuUiFrameLease *draw_copy_frame(const void *, unsigned);
int xu_ui_surface_create(uint64_t id,unsigned width,unsigned height,double logical_width,double logical_height,
                          const void *data,unsigned len) {
  auto render=g_surface_render.load(); unsigned bytes=0;
  if(!render || !isfinite(logical_width) || !isfinite(logical_height) || logical_width<=0 || logical_height<=0 ||
     logical_width>1e9 || logical_height>1e9 || !image_size(width,height,width*4u,width*height*4u,&bytes) ||
     !xdf_inverse_bounded(width/logical_width,0,0,height/logical_height,1e9) ||
     width/logical_width>1e9 || height/logical_height>1e9) return 0;
  auto *lease=draw_copy_frame(data,len);
  if(!lease) return 0;
  auto *header=(const unsigned char *)lease->body;
  unsigned canvas=xdf_u32(header+16),generation=xdf_u32(header+20);
  if(!image_begin_upload(id,canvas,generation)) { xu_ui_frame_release(lease); return 0; }
  // image_begin_upload and snapshot use the same generation. Revocation between
  // either phase and publish is caught again by image_finish_upload.
  lock_w(); auto *slot=image_slot(id);
  bool valid=slot && slot->state==IMAGE_UPLOADING && image_binding_alive(*slot) &&
             draw_snapshot_images(lease,canvas,slot->generation);
  unlock_w();
  valid=valid && draw_composition_valid(lease);
  auto *bitmap=valid ? image_allocate(id,width,height,true) : NULL;
  bool rendered=false;
  if(bitmap) {
    try {
      rendered=(g_surface_flags.load()&1) && draw_rect_batch(lease,width,height,logical_width,logical_height,bitmap->pixels);
      if(!rendered)rendered=render(lease,width,height,logical_width,logical_height,bitmap->pixels)!=0;
    }
    catch(...) { rendered=false; }
    // Bound the callback contract as well as its allocation: native surfaces
    // must produce valid premultiplied pixels before an image can reference it.
    for(unsigned i=0;rendered && i<bitmap->bytes;i+=4) {
      auto *p=bitmap->pixels+i;
      if(p[0]>p[3] || p[1]>p[3] || p[2]>p[3]) rendered=false;
    }
  }
  xu_ui_frame_release(lease);
  if(!rendered) { xu_ui_bitmap_release(bitmap); bitmap=NULL; }
  return image_finish_upload(id,bitmap);
}
// XUS1: version/reserved u32, image id u64, pixel dimensions u32,
// logical dimensions f64, then a complete XDF1 frame (minimum 32 bytes).
static int surface_upload(const void *data,unsigned len) {
  if(!data || len<72 || len>40+XU_DRAW_FRAME_MAX_BYTES) return 0;
  auto *p=(const unsigned char *)data;
  if(memcmp(p,"XUS1",4) || xdf_u32(p+4)!=1) return 0;
  uint64_t id=(uint64_t)xdf_u32(p+8)|((uint64_t)xdf_u32(p+12)<<32);
  return xu_ui_surface_create(id,xdf_u32(p+16),xdf_u32(p+20),xdf_f64(p+24),xdf_f64(p+32),p+40,len-40);
}

enum { REQUEST_RESERVED = 1, REQUEST_QUEUED = 2, REQUEST_ACTIVE = 3, REQUEST_READY = 4 };
struct XuUiRequest {
  uint64_t id;
  unsigned window, canvas, generation, kind, state, private_result, file_limit;
  long long deadline;
  char *wire, *result;
  unsigned wire_len, result_len;
};
static XuUiRequest g_requests[XU_UI_REQUEST_MAX_PENDING];
static uint64_t g_request_id = 0;
static unsigned g_request_wire_bytes = 0;
static bool g_shell_event_wake = false;
static void event_unlock(void) {
  bool wake = g_shell_event_wake; g_shell_event_wake = false;
  unlock_w();
  if (wake) wake_waiters();
}
static long long request_now(void) {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
    std::chrono::steady_clock::now().time_since_epoch()).count();
}
static XuUiRequest *request_find(uint64_t id) {
  for (auto &r : g_requests) if (r.id == id && id) return &r;
  return NULL;
}
static void request_release(XuUiRequest &r) {
  g_request_wire_bytes -= r.wire_len;
  free(r.wire); free(r.result); r = {};
}
static void request_flush(void) {
  for (auto &r : g_requests) {
    if (r.state == REQUEST_READY && !r.private_result &&
        slot_append_unlocked("xu_ui_shell_event.txt", r.result, r.result_len, 0)) { request_release(r); g_shell_event_wake = true; }
  }
}
static void request_finish(XuUiRequest &r, unsigned status, const char *text, unsigned len) {
  if (r.state == REQUEST_READY) return;
  if (status > XU_REQUEST_TIMED_OUT || len > XU_UI_REQUEST_MAX_TEXT || (len && !text) ||
      !xdf_utf8((const unsigned char *)text, len) ||
      (status==XU_REQUEST_COMPLETED && xu_file_kind(r.kind) && !xu_file_result_valid(text,len,r.kind,r.file_limit))) {
    status = XU_REQUEST_FAILED; text = "invalid native result"; len = 21;
  }
  int prefix = snprintf(r.result, 184, "request\t%llu\t%u\t%u\t%u\t%u\t%u\t",
    (unsigned long long)r.id, r.window, r.canvas, r.generation, r.kind, status);
  const char hex[] = "0123456789abcdef";
  for (unsigned i = 0; i < len; ++i) {
    unsigned c = (unsigned char)text[i]; r.result[prefix + i * 2] = hex[c >> 4]; r.result[prefix + i * 2 + 1] = hex[c & 15];
  }
  r.result_len = (unsigned)prefix + len * 2u;
  r.result[r.result_len++] = '\n'; r.result[r.result_len] = 0;
  g_request_wire_bytes -= r.wire_len;
  free(r.wire); r.wire = NULL; r.wire_len = 0;
  r.state = REQUEST_READY; r.deadline = request_now() + 60000;
  g_shell_event_wake = true;
}
static void request_expire(void) {
  long long now = request_now();
  for (auto &r : g_requests) {
    if (!r.id || r.deadline > now) continue;
    if (r.state == REQUEST_RESERVED || (r.state == REQUEST_READY && r.private_result)) request_release(r);
    else if (r.state != REQUEST_READY) request_finish(r, XU_REQUEST_TIMED_OUT, "", 0);
  }
  request_flush();
}
uint64_t xu_ui_request_reserve(void) {
  lock_w(); request_expire();
  uint64_t id = 0;
  for (auto &r : g_requests) {
    if (r.id || g_request_id == INT64_MAX) continue;
    // Completion storage is reserved up front, so closing a canvas cannot
    // lose its terminal result because a later allocation fails.
    char *result = (char *)malloc(XU_UI_REQUEST_MAX_TEXT * 2u + 184u);
    if (!result) break;
    id = ++g_request_id; r.id = id; r.result = result;
    r.state = REQUEST_RESERVED; r.deadline = request_now() + 10000; break;
  }
  event_unlock(); return id;
}
void xu_ui_request_abandon(uint64_t id) {
  lock_w(); auto *r = request_find(id);
  if (r && (r->state == REQUEST_RESERVED || (r->state == REQUEST_READY && r->private_result))) request_release(*r);
  event_unlock();
}
static bool request_number(const char *p, unsigned len, uint64_t limit, uint64_t *out) {
  if (!len) return false;
  uint64_t value = 0;
  for (unsigned i = 0; i < len; ++i) {
    unsigned c = (unsigned char)p[i];
    if (c < '0' || c > '9' || c - '0' > limit || value > (limit - (c - '0')) / 10u) return false;
    value = value * 10u + c - '0';
  }
  *out = value; return true;
}
int xu_ui_request_submit(const void *data, unsigned length) {
  if (!data || !length || length > XU_UI_REQUEST_MAX_TEXT * 4u + 184u) return 0;
  const char *wire = (const char *)data, *fields[9]; unsigned sizes[9] = {}, index = 0;
  fields[0] = wire;
  for (unsigned i = 0; i < length; ++i) {
    if (wire[i] == '\t') {
      if (++index == 9) return 0;
      fields[index] = wire + i + 1;
    } else { if (!wire[i] || wire[i] == '\n' || wire[i] == '\r') return 0; ++sizes[index]; }
  }
  if (index != 8) return 0;
  uint64_t numbers[7], limits[] = {INT64_MAX, 0x7fffffff, 0x7fffffff, UINT32_MAX, XU_REQUEST_WEBVIEW_COOKIES_CLEAR, 3600000, 1};
  for (unsigned i = 0; i < 7; ++i) if (!request_number(fields[i], sizes[i], limits[i], &numbers[i])) return 0;
  if (!numbers[0] || !numbers[1] || !numbers[2] || !numbers[3] || !numbers[4] || !numbers[5]) return 0;
  if ((numbers[4] == XU_REQUEST_CLIPBOARD_READ || numbers[4] == XU_REQUEST_CLIPBOARD_WRITE) &&
      (sizes[7] || (numbers[4] == XU_REQUEST_CLIPBOARD_READ && sizes[8]))) return 0;
  if (numbers[4] == XU_REQUEST_SCREENS && (sizes[7] || sizes[8])) return 0;
  // Validate decoded UTF-8 before accepting, including embedded NUL. Neither
  // native toolkit receives unbounded strings or command delimiters.
  for (unsigned i = 7; i < 9; ++i) {
    std::string text;
    if (!xu_request_unhex(std::string(fields[i], sizes[i]), &text) ||
        !xdf_utf8((const unsigned char *)text.data(), (unsigned)text.size())) return 0;
  }
  unsigned file_limit=0;
  if(xu_file_kind(numbers[4])) {
    XuUiFileOptions options;std::string seed;
    if(sizes[7]>8192 || !xu_request_unhex(std::string(fields[8],sizes[8]),&seed) || !xu_file_options(seed,numbers[4],&options))return 0;
    file_limit=options.multiple?XU_UI_FILE_MAX_PATHS:1;
  }
  lock_w(); request_expire();
  auto *r = request_find(numbers[0]);
  bool alive = false, busy = false;unsigned files=0;
  for (const auto &c : g_canvases) if (c.window_id == numbers[1] && c.canvas_id == numbers[2] && c.generation == numbers[3]) alive = true;
  for (const auto &other : g_requests) if(other.id && other.state!=REQUEST_READY) {
    if(xu_request_modal(numbers[4]) && xu_request_modal(other.kind) && other.window==numbers[1])busy=true;
    if(xu_file_kind(other.kind))++files;
  }
  if(xu_file_kind(numbers[4]) && files>=XU_UI_FILE_MAX_ACTIVE)busy=true;
  if (!r || r->state != REQUEST_RESERVED || !alive || busy || length > XU_UI_REQUEST_MAX_QUEUED_BYTES - g_request_wire_bytes) {
    event_unlock(); return 0;
  }
  char *copy = dup_cstr_n(wire, length);
  char marker[64]; int marker_len = snprintf(marker, sizeof(marker), "content.__request\t%llu\n", (unsigned long long)r->id);
  if (!copy || !slot_append_unlocked("xu_ui_cmd.txt", marker, (unsigned)marker_len, 0)) { free(copy); event_unlock(); return 0; }
  r->window = (unsigned)numbers[1]; r->canvas = (unsigned)numbers[2]; r->generation = (unsigned)numbers[3];
  r->kind = (unsigned)numbers[4]; r->private_result = (unsigned)numbers[6];r->file_limit=file_limit;
  r->wire = copy; r->wire_len = length; g_request_wire_bytes += length;
  r->state = REQUEST_QUEUED; r->deadline = request_now() + (long long)numbers[5];
  event_unlock(); wake_waiters(); xu_ui_host_kick(); return 1;
}
static char *request_take(uint64_t id, unsigned canvas, unsigned generation, unsigned kind) {
  lock_w(); request_expire(); auto *r = request_find(id); char *wire = NULL;
  if (r && r->state == REQUEST_QUEUED && r->canvas == canvas && r->generation == generation && (!kind || r->kind == kind)) {
    wire = r->wire; g_request_wire_bytes -= r->wire_len; r->wire = NULL; r->wire_len = 0; r->state = REQUEST_ACTIVE;
  }
  event_unlock(); return wire;
}
char *xu_ui_request_take(uint64_t id, unsigned canvas, unsigned generation) { return request_take(id,canvas,generation,0); }
char *xu_ui_request_take_kind(uint64_t id, unsigned canvas, unsigned generation, unsigned kind) {
  return kind ? request_take(id,canvas,generation,kind) : NULL;
}
int xu_ui_request_alive(uint64_t id) {
  lock_w(); request_expire(); auto *r = request_find(id);
  int alive = r && (r->state == REQUEST_QUEUED || r->state == REQUEST_ACTIVE);
  event_unlock(); return alive;
}
int xu_ui_request_complete(uint64_t id, unsigned status, const char *text, unsigned length) {
  lock_w(); request_expire(); auto *r = request_find(id);
  int accepted = r && (r->state == REQUEST_QUEUED || r->state == REQUEST_ACTIVE);
  if (accepted) { request_finish(*r, status, text, length); request_flush(); }
  event_unlock(); return accepted;
}
int xu_ui_request_cancel(uint64_t id) {
  int accepted = xu_ui_request_complete(id, XU_REQUEST_CANCELLED, "", 0);
  if (accepted) xu_ui_host_kick();
  return accepted;
}
void xu_ui_request_poll(void) { lock_w(); request_expire(); event_unlock(); }
void xu_ui_request_discard_marker(const char *command) {
  uint64_t id = 0; if (!xu_request_marker(command, &id)) return;
  lock_w(); request_expire(); auto *r = request_find(id);
  if (r && r->state == REQUEST_QUEUED) { request_finish(*r, XU_REQUEST_UNSUPPORTED, "", 0); request_flush(); }
  event_unlock();
}
static unsigned request_result_len(uint64_t id) {
  lock_w(); request_expire(); auto *r = request_find(id);
  unsigned length = r && r->state == REQUEST_READY && r->private_result ? r->result_len : 0;
  event_unlock(); return length;
}
static void request_result_copy(uint64_t id, void *out, unsigned cap) {
  if (!out || !cap) return;
  lock_w(); request_expire(); auto *r = request_find(id); ((char *)out)[0] = 0;
  if (r && r->state == REQUEST_READY && r->private_result && cap > r->result_len) {
    memcpy(out, r->result, r->result_len + 1); request_release(*r);
  }
  event_unlock();
}


#include "xu_ui_text_input.inc"

unsigned xu_ui_canvas_open(unsigned window_id, unsigned canvas_id) {
  if (!window_id || window_id > 0x7fffffffu || !canvas_id || canvas_id > 0x7fffffffu) return 0;
  lock_w();
  unsigned free_slot = XU_DRAW_MAX_CANVASES;
  for (unsigned i = 0; i < XU_DRAW_MAX_CANVASES; ++i) {
    if (g_canvases[i].canvas_id == canvas_id) { unlock_w(); return 0; }
    if (!g_canvases[i].canvas_id && free_slot == XU_DRAW_MAX_CANVASES) free_slot = i;
  }
  if (free_slot == XU_DRAW_MAX_CANVASES || g_canvas_generation == UINT32_MAX) { unlock_w(); return 0; }
  unsigned generation = ++g_canvas_generation;
  g_canvases[free_slot] = {window_id, canvas_id, generation};
  image_adopt_canvas(canvas_id, generation);
  list_adopt_canvas(canvas_id,generation);
  text_adopt_canvas(canvas_id, generation);
  g_canvas_started = true;
  unlock_w();
  return generation;
}

void xu_ui_canvas_close(unsigned canvas_id, unsigned generation) {
  if (!canvas_id || !generation) return;
  lock_w();
  for (auto &canvas : g_canvases) {
    if (canvas.canvas_id != canvas_id || canvas.generation != generation) continue;
    canvas = {};
    list_close_canvas(canvas_id,generation);
    image_close_canvas(canvas_id, generation);
    text_close_canvas(canvas_id, generation);
    input_close_canvas(canvas_id, generation);
    for (auto &frame : g_draw_pending) {
      if (frame.canvas_id == canvas_id && (!frame.generation || frame.generation == generation)) {
        xu_ui_frame_release(frame.lease); frame = {};
      }
    }
    for (auto &r : g_requests) if (r.canvas == canvas_id && r.generation == generation &&
        r.state != REQUEST_READY) request_finish(r, XU_REQUEST_CANCELLED, "", 0);
    request_flush();
    break;
  }
  event_unlock();
}

#include "xu_ui_native_views.h"
static void native_views_close_parent(unsigned parent,unsigned generation);
#include "xu_ui_windows.inc"
#include "xu_ui_native_views.inc"

static XuUiFrameLease *draw_copy_frame(const void *data, unsigned len) {
  if (!data || len<32 || len>XU_DRAW_FRAME_MAX_BYTES) return NULL;
  auto *lease = new(std::nothrow) XuUiFrameLease{};
  if (!lease) return NULL;
  void *copy = malloc(len);
  if (!copy) { delete lease; return NULL; }
  memcpy(copy, data, len);
  lease->body = copy; lease->len = len;
  // Validate the owned copy. Shared dash expansion is bounded and completed
  // outside the registry lock, before any ticket/command becomes observable.
  if(!xdf_validate(copy,len) || !draw_prepare_paths(lease)) { xu_ui_frame_release(lease); return NULL; }
  return lease;
}

static int draw_submit(const void *data, unsigned len) {
  if(!data || len<32 || len>XU_DRAW_FRAME_MAX_BYTES)return 0;
  // Reject already-full queues before copying/expanding an expensive frame.
  // Final admission still rechecks after capture and composition validation.
  lock_r();bool exhausted=g_draw_ticket==UINT64_MAX;unsigned occupied=0;
  for(const auto &pending:g_draw_pending)if(pending.lease)++occupied;
  bool full=occupied==XU_DRAW_FRAME_MAX_PENDING;unlock_r();
  if(exhausted)return 0;
  if(full)return 2; // Capacity pressure is retryable; invalid frames are not.
  auto *lease=draw_copy_frame(data,len);
  if(!lease) return 0;
  const void *copy=lease->body;
  lock_w();
  const unsigned char *header = (const unsigned char *)copy;
  unsigned canvas_id = xdf_u32(header + 16), generation = xdf_u32(header + 20), window_id = 0;
  for (const auto &canvas : g_canvases) {
    if (canvas.canvas_id == canvas_id && (!generation || canvas.generation == generation)) {
      window_id = canvas.window_id;
      generation = canvas.generation;
      break;
    }
  }
  // Legacy startup may queue a frame before its default canvas is installed.
  // Once registration begins, absence means closed/unsupported, never reopen.
  if (!window_id && (!g_canvas_started && xdf_u16(header + 4) == 1)) window_id = 1;
  auto *window=window_find(window_id,generation);
  if (!window_id || native_view_find(canvas_id,generation) || (window && window->kind!=2)) { unlock_w(); xu_ui_frame_release(lease); return 0; }
  bool captured=draw_snapshot_images(lease,canvas_id,generation);
  unlock_w();
  if(!captured || !draw_composition_valid(lease)) {xu_ui_frame_release(lease);return 0;}
  lock_w();unsigned actual=0;
  bool alive=(!generation && !g_canvas_started) || (image_target(canvas_id,generation,&actual) && actual==generation);
  unsigned slot=0;while(slot<XU_DRAW_FRAME_MAX_PENDING && g_draw_pending[slot].lease)++slot;
  if(!alive || slot==XU_DRAW_FRAME_MAX_PENDING || g_draw_ticket==UINT64_MAX) {
    int result=alive && g_draw_ticket!=UINT64_MAX ? 2 : 0;
    unlock_w();xu_ui_frame_release(lease);return result;
  }
  uint64_t ticket = ++g_draw_ticket;
  char marker[64];
  int n = snprintf(marker, sizeof(marker), "content.__draw_frame\t%llu\n", (unsigned long long)ticket);
  int ok = n > 0 && (unsigned)n < sizeof(marker) &&
           slot_append_unlocked("xu_ui_cmd.txt", marker, (unsigned)n, 0);
  if (ok) g_draw_pending[slot] = {lease, ticket, window_id, canvas_id, generation};
  unlock_w();
  if (!ok) { xu_ui_frame_release(lease); return 0; }
  wake_waiters();
  xu_ui_host_kick();
  return 1;
}

XuUiFrameLease *xu_ui_draw_acquire_for(uint64_t ticket, unsigned canvas_id, unsigned generation) {
  XuUiFrameLease *lease = NULL;
  lock_w();
  for (auto &frame : g_draw_pending) {
    if (frame.lease && frame.ticket == ticket && frame.canvas_id == canvas_id &&
        (frame.generation == generation || (!frame.generation && canvas_id == 1))) {
      lease = frame.lease;
      frame = {};
      break;
    }
  }
  unlock_w();
  if (lease) wake_waiters();
  return lease;
}
static void *draw_detach_payload(XuUiFrameLease *lease, unsigned *out_len) {
  if (out_len) *out_len = lease ? lease->len : 0;
  void *body = lease ? lease->body : NULL;
  if (lease) lease->body = NULL;
  xu_ui_frame_release(lease); return body;
}
void *xu_ui_draw_take_for(uint64_t ticket, unsigned canvas_id, unsigned generation, unsigned *out_len) {
  return draw_detach_payload(xu_ui_draw_acquire_for(ticket, canvas_id, generation), out_len);
}

unsigned xu_ui_draw_window(uint64_t ticket) {
  unsigned window_id = 0;
  lock_w();
  for (const auto &frame : g_draw_pending) {
    if (frame.lease && frame.ticket == ticket) { window_id = frame.window_id; break; }
  }
  unlock_w();
  return window_id;
}

void *xu_ui_draw_take(uint64_t ticket, unsigned *out_len) {
  XuUiFrameLease *lease = NULL;
  lock_w();
  for (unsigned i = 0; i < XU_DRAW_FRAME_MAX_PENDING; ++i) {
    if (g_draw_pending[i].lease && g_draw_pending[i].ticket == ticket) {
      lease = g_draw_pending[i].lease;
      g_draw_pending[i] = {};
      break;
    }
  }
  unlock_w();
  if (lease) wake_waiters();
  return draw_detach_payload(lease, out_len);
}

void xu_ui_draw_discard_marker(const char *command) {
  const char prefix[] = "__draw_frame\t";
  if (!command || strncmp(command, prefix, sizeof(prefix) - 1)) return;
  const char *p = command + sizeof(prefix) - 1;
  uint64_t ticket = 0;
  if (!*p) return;
  for (; *p; ++p) {
    if (*p < '0' || *p > '9' || ticket > (UINT64_MAX - (unsigned)(*p - '0')) / 10u) return;
    ticket = ticket * 10u + (unsigned)(*p - '0');
  }
  free(xu_ui_draw_take(ticket, NULL));
}

int xu_ui_draw_next_v2(const void *data, unsigned len, unsigned *cursor,
                    double *values8, unsigned *meta2, const char **text, unsigned *text_len, uint64_t *image_id) {
  if (!values8 || !meta2 || !text || !text_len || !image_id) return -1;
  XuDrawCommand command;
  int result = xdf_next(data, len, cursor, &command);
  if (result == 1) {
    memcpy(values8, command.values, sizeof(command.values));
    meta2[0] = command.opcode; meta2[1] = command.rgba;
    *text = command.text; *text_len = command.text_len;
    *image_id = command.image_id;
  }
  return result;
}
int xu_ui_draw_next(const void *data, unsigned len, unsigned *cursor,
                    double *values8, unsigned *meta2, const char **text, unsigned *text_len) {
  uint64_t image_id = 0;
  return xu_ui_draw_next_v2(data, len, cursor, values8, meta2, text, text_len, &image_id);
}

void xu_ui_mem_append(const char *name, const char *body, int add_nl) {
  unsigned len;
  const char *b = body ? body : "";
  if (cstr_len_u32(b, &len)) (void)slot_append_key(slot_key(name), b, len, add_nl);
}

char *xu_ui_mem_take(const char *name, unsigned *out_len) {
  const char *key = slot_key(name);
  char *body = NULL;
  if (out_len) *out_len = 0;
  lock_w();
  if (key && strcmp(key, "xu_ui_cmd.txt") == 0) g_host_kick_pending.store(false);
  XuUiSlot *s = find_slot_unlocked(key);
  if (s) {
    body = s->body;
    if (out_len) *out_len = s->len;
    memset(s, 0, sizeof(*s));
  }
  unlock_w();
  return body;
}

void xu_ui_mem_clear(const char *name) {
  const char *key = slot_key(name);
  XuUiSlot *s;
  lock_w();
  s = find_slot_unlocked(key);
  if (s) {
    free(s->body);
    s->body = NULL;
    s->len = 0;
    s->cap = 0;
    /* Reclaim the table entry as well as its body.  Keeping used=1 forever
     * made 128 transient slot names exhaust the mailbox even after callers
     * had explicitly cleared them. */
    s->name[0] = '\0';
    s->used = 0;
  }
  unlock_w();
  wake_waiters();
}

struct XuEmitRecord { char *body; unsigned len; };
static XuEmitRecord g_emit_queue[XU_UI_EMIT_MAX_RECORDS];
static unsigned g_emit_head = 0, g_emit_count = 0, g_emit_bytes = 0;
static uint64_t g_emit_session = 1;
static bool g_emit_open = true;

// 1 accepted, 0 backpressure, -1 invalid/OOM. Allocate only after capacity is
// reserved under the lock, so blocked producers do not hold extra C copies.
static int emit_append(const void *data, unsigned len, uint64_t session) {
  if (!data || !len || len > XU_UI_EMIT_MAX_BYTES) return -1;
  lock_w();
  if (!g_emit_open || session != g_emit_session) { unlock_w(); return -1; }
  if (g_emit_count == XU_UI_EMIT_MAX_RECORDS || len > XU_UI_EMIT_MAX_BYTES - g_emit_bytes) {
    unlock_w(); return 0;
  }
  char *body = (char *)malloc((size_t)len + 1);
  if (!body) { unlock_w(); return -1; }
  memcpy(body, data, len); body[len] = 0;
  unsigned tail = (g_emit_head + g_emit_count) % XU_UI_EMIT_MAX_RECORDS;
  g_emit_queue[tail] = {body, len}; ++g_emit_count; g_emit_bytes += len;
  unlock_w(); wake_waiters();
  return 1;
}

char *xu_ui_emit_take(unsigned *out_len) {
  char *body = NULL; unsigned len = 0;
  lock_w();
  if (!g_emit_open) { unlock_w(); if (out_len) *out_len = 0; return NULL; }
  if (g_emit_count) {
    XuEmitRecord &record = g_emit_queue[g_emit_head];
    body = record.body; len = record.len; record = {};
    g_emit_head = (g_emit_head + 1) % XU_UI_EMIT_MAX_RECORDS;
    --g_emit_count; g_emit_bytes -= len;
  } else {
    // Legacy clients used an RS-separated string slot. Pop its prefix while
    // holding the same writer lock instead of racing append against rewrite.
    XuUiSlot *slot = find_slot_unlocked("xu_ui_emit_q.txt");
    if (slot && slot->len) {
      const char *end = (const char *)memchr(slot->body, 30, slot->len);
      len = end ? (unsigned)(end - slot->body) : slot->len;
      body = (char *)malloc((size_t)len + 1);
      if (body) {
        memcpy(body, slot->body, len); body[len] = 0;
        unsigned consumed = len + (end ? 1u : 0u);
        slot->len -= consumed;
        if (slot->len) memmove(slot->body, slot->body + consumed, slot->len + 1u);
        else { free(slot->body); *slot = {}; }
      }
    }
  }
  unlock_w();
  if (out_len) *out_len = body ? len : 0;
  if (body) wake_waiters();
  return body;
}

static void emit_clear_unlocked(void) {
  for (auto &record : g_emit_queue) { free(record.body); record = {}; }
  g_emit_head = g_emit_count = g_emit_bytes = 0;
  XuUiSlot *slot = find_slot_unlocked("xu_ui_emit_q.txt");
  if (slot) { free(slot->body); *slot = {}; }
  if (g_emit_session != UINT64_MAX) ++g_emit_session;
  else g_emit_open = false;
}

void xu_ui_emit_clear(void) {
  lock_w(); emit_clear_unlocked();
  unlock_w(); wake_waiters();
}

void xu_ui_emit_start(void) {
  lock_w(); if (g_emit_session != UINT64_MAX) g_emit_open = true;
  unlock_w(); wake_waiters();
}

void xu_ui_emit_close(void) {
  lock_w(); g_emit_open = false; emit_clear_unlocked();
  unlock_w(); wake_waiters();
}

// The predicate is always evaluated outside the wait mutex. A notification
// epoch bridges that gap: a writer that has already notified prevents parking;
// a writer still waiting for the mutex notifies after the atomic unlock/wait.
// Every spurious/unrelated wake retains the same monotonic deadline.
template <typename Predicate>
static int wait_for_predicate(Predicate ready, int timeout_ms) {
  if (timeout_ms < 0) timeout_ms = 0;
  if (ready()) return 1;
  if (!timeout_ms) return 0;
  using Clock = std::chrono::steady_clock;
  const auto deadline = Clock::now() + std::chrono::milliseconds(timeout_ms);
  wait_init();
  for (;;) {
    uint64_t observed = g_wait_epoch.load(std::memory_order_acquire);
    if (ready()) return 1;
    bool expired = false;
#ifdef _WIN32
    EnterCriticalSection(&g_wait_cs);
#else
    pthread_mutex_lock(&g_wait_mu);
#endif
    if (g_wait_epoch.load(std::memory_order_acquire) == observed) {
      auto remaining = deadline - Clock::now();
      if (remaining <= Clock::duration::zero()) expired = true;
      else {
#ifdef _WIN32
        auto milliseconds = std::chrono::duration_cast<std::chrono::milliseconds>(remaining).count() + 1;
        if (milliseconds > 20) milliseconds = 20;
        LeaveCriticalSection(&g_wait_cs);
        WaitForSingleObject(g_wait_event, (DWORD)milliseconds);
        EnterCriticalSection(&g_wait_cs);
#else
        auto nanoseconds = std::chrono::duration_cast<std::chrono::nanoseconds>(remaining).count();
        struct timespec until;
#if defined(__APPLE__)
        until.tv_sec = (time_t)(nanoseconds / 1000000000LL);
        until.tv_nsec = (long)(nanoseconds % 1000000000LL);
        pthread_cond_timedwait_relative_np(&g_wait_cv, &g_wait_mu, &until);
#else
        clock_gettime(CLOCK_MONOTONIC, &until);
        until.tv_sec += (time_t)(nanoseconds / 1000000000LL);
        until.tv_nsec += (long)(nanoseconds % 1000000000LL);
        if (until.tv_nsec >= 1000000000L) { ++until.tv_sec; until.tv_nsec -= 1000000000L; }
        pthread_cond_timedwait(&g_wait_cv, &g_wait_mu, &until);
#endif
#endif
      }
    }
#ifdef _WIN32
    LeaveCriticalSection(&g_wait_cs);
#else
    pthread_mutex_unlock(&g_wait_mu);
#endif
    if (expired || Clock::now() >= deadline) return ready() ? 1 : 0;
  }
}

int xu_ui_request_wait(uint64_t id, int timeout_ms) {
  if (timeout_ms < 0 || timeout_ms > 60000) return -1;
  int status = 0;
  wait_for_predicate([&] {
    lock_w(); request_expire(); auto *r = request_find(id);
    status = !r || !r->private_result ? -1 : (r->state == REQUEST_READY ? 1 : 0);
    event_unlock(); return status != 0;
  }, timeout_ms);
  return status;
}

int xu_ui_mem_wait_nonempty(const char *name, int timeout_ms) {
  char tb[160];
  snprintf(tb, sizeof(tb), "mem_wait_nonempty: %s ms=%d", name ? name : "(null)", timeout_ms);
  do_trace(tb);
  const char *key = slot_key(name);
  if (!key || !key[0]) return -1;
  return wait_for_predicate([&] { return slot_nonempty(key); }, timeout_ms);
}

int xu_ui_mem_wait_ne(const char *name, const char *old_body, int timeout_ms) {
  const char *key = slot_key(name);
  if (!key || !key[0]) return -1;
  return wait_for_predicate([&] { return !slot_body_eq(key, old_body); }, timeout_ms);
}

int xu_ui_mem_wait_ipc(int timeout_ms) {
  // Shell events have their own consumer; they must not turn the invoke
  // worker into a busy loop while pointer/progress events are queued.
  return wait_for_predicate([] {
    return !web_running() || invoke_pending() || web_pending() || slot_nonempty("xu_ui_ipc_req.txt");
  }, timeout_ms);
}

/* Parse a decimal timeout without atoi/overflow.  The input is length
 * bounded because it often comes directly from a Xu byte buffer. */
static int parse_timeout_bytes(const void *data, size_t len, int default_ms, int max_ms) {
  const unsigned char *p = (const unsigned char *)data;
  uint64_t value = 0;
  size_t i;
  int any = 0;
  if (!p || len == 0 || max_ms <= 0) return default_ms;
  for (i = 0; i < len; i++) {
    unsigned digit;
    if (p[i] < (unsigned char)'0' || p[i] > (unsigned char)'9') break;
    any = 1;
    digit = (unsigned)(p[i] - (unsigned char)'0');
    if ((uint64_t)digit > (uint64_t)max_ms) return max_ms;
    if (value > ((uint64_t)max_ms - digit) / 10u) return max_ms;
    value = value * 10u + digit;
  }
  if (!any || value == 0) return default_ms;
  if (value > (uint64_t)max_ms) return max_ms;
  return (int)value;
}

static int parse_timeout_cstr(const char *text, int default_ms, int max_ms) {
  unsigned n;
  if (!text) return default_ms;
  if (!cstr_len_u32(text, &n)) return max_ms;
  return parse_timeout_bytes(text, (size_t)n, default_ms, max_ms);
}

int xu_ui_mem_is_path(const char *path_z) {
  /* strncmp stops at the first NUL, so a short string such as ":" is
   * rejected without indexing beyond the caller's C string object. */
  return path_z && strncmp(path_z, ":xu:", 4) == 0;
}

static const char *mem_path_key(const char *path_z) {
  const char *key;
  if (!xu_ui_mem_is_path(path_z)) return NULL;
  path_z += 4; /* skip :xu: */
  key = slot_key(path_z);
  return key;
}

static std::atomic<xu_ui_asset_reader_fn> g_asset_reader{NULL};
void xu_ui_set_asset_reader(xu_ui_asset_reader_fn reader) { g_asset_reader.store(reader, std::memory_order_release); }
static bool asset_lookup(const char *path, bool *exists_query, const unsigned char **data, unsigned *length) {
  const char get[] = ":xu:/__asset/", exists[] = ":xu:/__asset_exists/";
  const char *relative = NULL;
  if (path && !strncmp(path, get, sizeof(get) - 1)) { relative = path + sizeof(get) - 1; *exists_query = false; }
  else if (path && !strncmp(path, exists, sizeof(exists) - 1)) { relative = path + sizeof(exists) - 1; *exists_query = true; }
  else return false;
  *data = NULL; *length = 0;
  unsigned size = 0;
  while (size <= 4096 && relative[size]) ++size;
  if (!size || size > 4096 || !xdf_utf8((const unsigned char *)relative, size)) return true;
  unsigned start = 0;
  for (unsigned i = 0; i <= size; ++i) {
    if (i != size && (relative[i] == '\\' || relative[i] == ':')) return true;
    if (i != size && relative[i] != '/') continue;
    unsigned count = i - start;
    if (!count || (count == 1 && relative[start] == '.') ||
        (count == 2 && relative[start] == '.' && relative[start + 1] == '.')) return true;
    start = i + 1;
  }
  auto reader = g_asset_reader.load(std::memory_order_acquire);
  if (reader) *data = reader(relative, length);
  if (!*data || *length > XU_UI_MEM_MAX_PAYLOAD) { *data = NULL; *length = 0; }
  return true;
}

#include "xu_ui_xacp.inc"

int xu_ui_mem_try_write(const char *path_z, const void *data, unsigned data_len, unsigned *out_n) {
  char tb[160];
  snprintf(tb, sizeof(tb), "mem_try_write: %s len=%u", path_z ? path_z : "(null)", data_len);
  do_trace(tb);
  const char *key = mem_path_key(path_z);
  if (key && !strncmp(key,"__xacp_file/",12)) {
    bool ok = xacp_write_file(key,data,data_len); if(out_n) *out_n = ok ? data_len : 0; return 1;
  }
  if (key && !strncmp(key,"__xacp_cleanup/",15)) {
    xacp_cleanup_files(key); if(out_n) *out_n = data_len; return 1;
  }
  int ms;
  if (!xu_ui_mem_is_path(path_z)) return 0;
  if (!strncmp(path_z, ":xu:/__asset/", 13) || !strncmp(path_z, ":xu:/__asset_exists/", 20)) {
    if (out_n) *out_n = 0;
    return 1;
  }
  /* A syntactically virtual but invalid/empty/overlong slot is still handled
   * by the mailbox.  Returning 0 here would make the Xu runtime fall through
   * to a real filesystem open on a path that was meant to stay in-process. */
  if (!key) {
    if (out_n) *out_n = 0;
    return 1;
  }
  if (!strcmp(key,"__native_view_update") || !strcmp(key,"__native_view_slot") || !strcmp(key,"__native_view_command") || !strcmp(key,"__native_view_close")) {
    int ok=0;
    if(!strcmp(key,"__native_view_update"))ok=native_view_update(data,data_len);
    else if(!strcmp(key,"__native_view_slot"))ok=native_view_slot_write(data,data_len);
    else if(!strcmp(key,"__native_view_command"))ok=native_view_command(data,data_len);
    else if(data && data_len==8){auto *p=(const unsigned char *)data;xu_ui_native_view_close(xdf_u32(p),xdf_u32(p+4));ok=1;}
    if(out_n)*out_n=ok?data_len:0;return 1;
  }
  if (!strcmp(key,"__window_open") || !strcmp(key,"__window_bind") || !strcmp(key,"__window_command") || !strcmp(key,"__window_abandon") || !strcmp(key,"__window_slot")) {
    int ok=0;
    if(!strcmp(key,"__window_open"))ok=window_upload(data,data_len);
    else if(!strcmp(key,"__window_bind"))ok=window_bind(data,data_len);
    else if(!strcmp(key,"__window_command"))ok=window_command(data,data_len);
    else if(!strcmp(key,"__window_slot"))ok=window_slot_write(data,data_len);
    else if(data && data_len==8){auto *p=(const unsigned char *)data;xu_ui_window_abandon(xdf_u32(p),xdf_u32(p+4));ok=1;}
    if(out_n)*out_n=ok?data_len:0;return 1;
  }
  // Upload has its own header allowance; ordinary mailbox slots retain the
  // existing payload cap. Never stage a large bitmap through a mailbox slot.
  if (strcmp(key, "__image_upload") == 0) {
    int accepted = image_upload(data, data_len);
    if (out_n) *out_n = accepted ? data_len : 0;
    return 1;
  }
  if (!payload_len_allowed(data_len)) {
    /* Complete an in-flight invoke with a bounded diagnostic instead of
     * leaving the rendezvous in INV_BUSY until the five-second host timeout. */
    if (strcmp(key, "__invoke_reply") == 0) (void)invoke_try_reply(data, data_len);
    if (out_n) *out_n = 0;
    return 1;
  }
  /* A non-zero length must be backed by a real source buffer.  Treat a
   * malformed virtual write as handled-but-empty so callers never dereference
   * or copy from NULL. */
  if (data_len && !data) {
    if (out_n) *out_n = 0;
    return 1;
  }
  if (key[0] == '_' && key[1] == '_') {
    if (strcmp(key, "__text_input_bind") == 0) {
      int accepted=input_bind_upload(data,data_len); if(out_n) *out_n=accepted ? data_len : 0; return 1;
    }
    if (strcmp(key, "__text_input_upload") == 0) {
      int accepted=input_upload(data,data_len); if(out_n) *out_n=accepted ? data_len : 0; return 1;
    }
    if (strcmp(key, "__text_input_abandon") == 0 || strcmp(key, "__text_input_abort") == 0) {
      uint64_t id=0; int accepted=data && request_number((const char *)data,data_len,INT64_MAX,&id) && id;
      if(accepted) { if(!strcmp(key,"__text_input_abort")) xu_ui_text_input_abort(id); else xu_ui_text_input_abandon(id); }
      if(out_n) *out_n=accepted ? data_len : 0; return 1;
    }
    if(!strcmp(key,"__display_list_upload")) {
      int accepted=display_list_upload(data,data_len);if(out_n)*out_n=accepted?data_len:0;return 1;
    }
    if(!strcmp(key,"__display_list_abandon")) {
      uint64_t id=0;int accepted=data && request_number((const char *)data,data_len,INT64_MAX,&id) && id;
      if(accepted)xu_ui_display_list_abandon(id);if(out_n)*out_n=accepted?data_len:0;return 1;
    }
    if (strcmp(key, "__text_upload") == 0) {
      int accepted = text_upload(data, data_len);
      if (out_n) *out_n = accepted ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__text_abandon") == 0) {
      uint64_t id = 0;
      int accepted = data && request_number((const char *)data, data_len, INT64_MAX, &id) && id;
      if (accepted) xu_ui_text_abandon(id);
      if (out_n) *out_n = accepted ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__text_dispose") == 0) {
      uint64_t fields[3] = {}; unsigned start = 0, count = 0;
      bool valid = data && data_len > 0 && data_len < 64;
      const char *text = (const char *)data;
      for (unsigned i = 0; valid && i <= data_len; ++i) {
        if (i != data_len && text[i] != '\t') continue;
        if (count == 3 || !request_number(text + start, i - start, count ? UINT32_MAX : INT64_MAX, &fields[count])) valid = false;
        else { ++count; start = i + 1; }
      }
      int accepted = valid && count == 3 && xu_ui_text_dispose(fields[0], (unsigned)fields[1], (unsigned)fields[2]);
      if (out_n) *out_n = accepted ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__display_list_dispose") == 0) {
      uint64_t fields[3] = {}; unsigned start = 0, count = 0;
      bool valid = data && data_len > 0 && data_len < 64;
      const char *text = (const char *)data;
      for (unsigned i = 0; valid && i <= data_len; ++i) {
        if (i != data_len && text[i] != '\t') continue;
        if (count == 3 || !request_number(text + start, i - start, count ? UINT32_MAX : INT64_MAX, &fields[count])) valid = false;
        else { ++count; start = i + 1; }
      }
      int accepted = valid && count == 3 && xu_ui_display_list_dispose(fields[0], (unsigned)fields[1], (unsigned)fields[2]);
      if (out_n) *out_n = accepted ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__image_abandon") == 0) {
      uint64_t id = 0;
      int accepted = data && request_number((const char *)data, data_len, INT64_MAX, &id) && id;
      if (accepted) xu_ui_image_abandon(id);
      if (out_n) *out_n = accepted ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__image_dispose") == 0) {
      uint64_t fields[3] = {}; unsigned start = 0, count = 0;
      bool valid = data && data_len > 0 && data_len < 64;
      const char *text = (const char *)data;
      for (unsigned i = 0; valid && i <= data_len; ++i) {
        if (i != data_len && text[i] != '\t') continue;
        if (count == 3 || !request_number(text + start, i - start, count ? UINT32_MAX : INT64_MAX, &fields[count])) valid = false;
        else { ++count; start = i + 1; }
      }
      int accepted = valid && count == 3 && xu_ui_image_dispose(fields[0], (unsigned)fields[1], (unsigned)fields[2]);
      if (out_n) *out_n = accepted ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__request_submit") == 0) {
      int accepted = xu_ui_request_submit(data, data_len);
      if (out_n) *out_n = accepted ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__request_wait") == 0) {
      uint64_t id = 0;
      int accepted = data && request_number((const char *)data, data_len, INT64_MAX, &id) &&
                     xu_ui_request_wait(id, 250) >= 0;
      if (out_n) *out_n = accepted ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__request_cancel") == 0 || strcmp(key, "__request_abandon") == 0) {
      uint64_t id = 0;
      int accepted = data && request_number((const char *)data, data_len, INT64_MAX, &id) && id;
      if (accepted) {
        if (strcmp(key, "__request_cancel") == 0) accepted = xu_ui_request_cancel(id);
        else xu_ui_request_abandon(id);
      }
      if (out_n) *out_n = accepted ? data_len : 0;
      return 1;
    }
    if(!strcmp(key,"__surface_composite")) {
      int ok=composite_upload(data,data_len);if(out_n)*out_n=ok?data_len:0;return 1;
    }
    if (strcmp(key, "__gradient_upload") == 0) {
      int ok=gradient_upload(data,data_len);
      if(out_n) *out_n=ok ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__surface_upload") == 0) {
      int ok=surface_upload(data,data_len);
      if(out_n) *out_n=ok ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__draw_submit") == 0 || strcmp(key, "__draw_submit_wait") == 0) {
      int result = 2;
      if (strcmp(key, "__draw_submit_wait") == 0) {
        wait_for_predicate([&] { result=draw_submit(data,data_len);return result!=2; },5000);
      } else result=draw_submit(data,data_len);
      if (out_n) *out_n = result==1 ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__cmd_append") == 0) {
      int ok = data_len == 0 || !memchr(data, 0, data_len);
      if (ok) ok = slot_append_key("xu_ui_cmd.txt", data, data_len, 0);
      if (out_n) *out_n = ok ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__emit_append") == 0 || strcmp(key, "__emit_append_wait") == 0) {
      int result = 0;
      lock_r(); uint64_t session = g_emit_session; unlock_r();
      if (strcmp(key, "__emit_append_wait") == 0) {
        wait_for_predicate([&] { result = emit_append(data, data_len, session); return result != 0; }, 5000);
      } else result = emit_append(data, data_len, session);
      if (out_n) *out_n = result == 1 ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__mark") == 0) {
      if (getenv("XU_UI_TIMING") && getenv("XU_UI_TIMING")[0] == '1') {
        fprintf(stderr, "xu_ui_timing %lld mark %.*s\n", xu_now_ms(),
                data_len > 64 ? 64 : (int)data_len, data ? (const char *)data : "");
      }
      if (out_n) *out_n = data_len;
      return 1;
    }
    if (strcmp(key, "__ipc_wait") == 0) {
      ms = 250;
      if (data && data_len > 0) {
        ms = parse_timeout_bytes(data, (size_t)data_len, 250, 60000);
      }
      if (getenv("XU_UI_TIMING") && getenv("XU_UI_TIMING")[0] == '1') {
        fprintf(stderr, "xu_ui_timing %lld park_enter to=%d\n", xu_now_ms(), ms);
      }
      (void)xu_ui_mem_wait_ipc(ms);
      if (getenv("XU_UI_TIMING") && getenv("XU_UI_TIMING")[0] == '1') {
        fprintf(stderr, "xu_ui_timing %lld park_exit\n", xu_now_ms());
      }
      if (out_n) *out_n = data_len;
      return 1;
    }
    if (!strcmp(key,"__web_invoke_reply")) {bool ok=web_reply(data,data_len);if(out_n)*out_n=ok?data_len:0;return 1;}
  if (strcmp(key, "__invoke_reply") == 0) {
      int accepted = invoke_try_reply(data, data_len);
      if (out_n) *out_n = accepted ? data_len : 0;
      return 1;
    }
    if (strcmp(key, "__host_kick") == 0) {
      xu_ui_host_kick();
      if (out_n) *out_n = data_len;
      return 1;
    }
    /* Body: "<slot>\t<timeout_ms>" — park until slot nonempty. */
    if (strcmp(key, "__wait_nonempty") == 0) {
      char buf[256];
      char *tab;
      const char *slot;
      unsigned ncopy = data_len < sizeof(buf) - 1 ? data_len : (unsigned)(sizeof(buf) - 1);
      if (!data) data = "";
      memcpy(buf, data, ncopy);
      buf[ncopy] = 0;
      tab = strchr(buf, '\t');
      ms = 5000;
      if (tab) {
        *tab = 0;
        ms = parse_timeout_cstr(tab + 1, 5000, 120000);
      }
      slot = buf;
      while (*slot == ' ') slot++;
      if (slot[0]) (void)xu_ui_mem_wait_nonempty(slot, ms);
      if (out_n) *out_n = data_len;
      return 1;
    }
    /* Body: "<slot>\n<old>\n<timeout_ms>" — park until slot != old. */
    if (strcmp(key, "__wait_ne") == 0) {
      char *buf = NULL;
      char *line1 = NULL;
      char *line2 = NULL;
      char *line3 = NULL;
      char *p;
      unsigned ncopy = data_len;
      size_t bytes;
      if (!data) data = "";
      if (!alloc_bytes_for_u32(ncopy, &bytes)) {
        if (out_n) *out_n = 0;
        return 1;
      }
      buf = (char *)malloc(bytes);
      if (!buf) {
        if (out_n) *out_n = 0;
        return 1;
      }
      memcpy(buf, data, ncopy);
      buf[ncopy] = 0;
      line1 = buf;
      p = strchr(buf, '\n');
      if (p) {
        *p = 0;
        line2 = p + 1;
        p = strchr(line2, '\n');
        if (p) {
          *p = 0;
          line3 = p + 1;
        }
      }
      ms = 5000;
      if (line3 && line3[0]) {
        ms = parse_timeout_cstr(line3, 5000, 120000);
      }
      if (line1 && line1[0]) (void)xu_ui_mem_wait_ne(line1, line2 ? line2 : "", ms);
      free(buf);
      if (out_n) *out_n = data_len;
      return 1;
    }
  }
  if (out_n) {
    *out_n = slot_set_key(key, (const char *)(data ? data : ""), data_len)
                 ? data_len
                 : 0;
  } else {
    (void)slot_set_key(key, (const char *)(data ? data : ""), data_len);
  }
  return 1;
}

static unsigned input_query_mode(const char *key) {
  if(!strncmp(key,"__text_input_hit/",17)) return 1;
  if(!strncmp(key,"__text_input_caret/",19)) return 2;
  if(!strncmp(key,"__text_input_rect/",18)) return 3;
  return 0;
}
static void input_query_record(const char *key,void *output) {
  unsigned kind=input_query_mode(key), count=0;
  const char *fields[6],*start=key+(kind==1 ? 17 : kind==2 ? 19 : 18),*at=start;
  unsigned sizes[6]; bool valid=kind!=0;
  for(;;) {
    if(!*at || *at=='/') {
      if(count==6 || at==start) { valid=false; break; }
      fields[count]=start; sizes[count++]=(unsigned)(at-start);
      if(!*at) break;
      start=at+1;
    }
    ++at;
  }
  uint64_t values[6]={}; valid=valid && count==6;
  for(unsigned i=0;valid && i<6;++i) {
    if(kind==1 && i>=4) {
      if(sizes[i]!=16) { valid=false; break; }
      for(unsigned j=0;j<16;++j) {
        unsigned c=(unsigned char)fields[i][j];
        if(c>='0' && c<='9') c-='0'; else if(c>='a' && c<='f') c=c-'a'+10;
        else { valid=false; break; }
        values[i]=(values[i]<<4)|c;
      }
    } else valid=request_number(fields[i],sizes[i],i==0 || i==3 ? INT64_MAX : UINT32_MAX,&values[i]);
  }
  double x=0,y=0,result[8]={};
  if(kind==1) { memcpy(&x,&values[4],8); memcpy(&y,&values[5],8); }
  if(valid) valid=xu_ui_text_input_query(values[0],(unsigned)values[1],(unsigned)values[2],values[3],kind-1,
    kind==1 ? 0 : (unsigned)values[4],kind==1 ? 0 : (unsigned)values[5],x,y,result)!=0;
  auto *p=(unsigned char *)output; memset(p,0,81); memcpy(p,"XIG1",4); p[4]=valid ? 1 : 0;
  for(unsigned j=0;j<8;++j) p[8+j]=(unsigned char)(values[3]>>(j*8));
  for(unsigned i=0;i<8;++i) {
    uint64_t bits; memcpy(&bits,&result[i],8);
    for(unsigned j=0;j<8;++j) p[16+i*8+j]=(unsigned char)(bits>>(j*8));
  }
}
static bool text_query_key(const char *key) {
  return !strncmp(key, "__text_hit/", 11) || !strncmp(key, "__text_caret/", 13);
}
static void text_query_record(const char *key, void *output) {
  bool hit = !strncmp(key, "__text_hit/", 11);
  const char *fields[5]; unsigned sizes[5], count = 0;
  const char *start = key + (hit ? 11 : 13), *at = start;
  bool valid = true;
  for (;;) {
    if (!*at || *at == '/') {
      if (count == 5 || at == start) { valid = false; break; }
      fields[count] = start; sizes[count++] = (unsigned)(at - start);
      if (!*at) break;
      start = at + 1;
    }
    ++at;
  }
  uint64_t values[5] = {};
  for (unsigned i = 0; valid && i < 5; ++i) {
    if (count != 5) { valid = false; break; }
    if (hit && i >= 3) {
      if (sizes[i] != 16) { valid = false; break; }
      for (unsigned j = 0; j < 16; ++j) {
        unsigned c = (unsigned char)fields[i][j];
        if (c >= '0' && c <= '9') c -= '0';
        else if (c >= 'a' && c <= 'f') c = c - 'a' + 10;
        else { valid = false; break; }
        values[i] = (values[i] << 4) | c;
      }
    } else valid = request_number(fields[i], sizes[i], i == 0 ? INT64_MAX : UINT32_MAX, &values[i]);
  }
  double x = 0, y = 0, result[7] = {};
  if (hit) { memcpy(&x, &values[3], 8); memcpy(&y, &values[4], 8); }
  if (valid) valid = xu_ui_text_query(values[0], (unsigned)values[1], (unsigned)values[2], hit ? 0 : 1,
    hit ? 0 : (unsigned)values[3], hit ? 0 : (unsigned)values[4], x, y, result) != 0;
  auto *p = (unsigned char *)output; memset(p, 0, 73); memcpy(p, "XTH1", 4); p[4] = valid ? 1 : 0;
  for (unsigned i = 0; i < 7; ++i) {
    uint64_t bits; memcpy(&bits, &result[i], 8);
    for (unsigned j = 0; j < 8; ++j) p[16 + i * 8 + j] = (unsigned char)(bits >> (j * 8));
  }
}

// One retained native layout and one mailbox read for an entire selection.
static std::string text_selection_record(const char *key) {
  uint64_t values[5]={}; const char *start=key+17;unsigned n=0;bool valid=true;
  for(const char *p=start;;++p)if(!*p || *p=='/') {
    if(n==5 || !request_number(start,(unsigned)(p-start),n==0?INT64_MAX:UINT32_MAX,&values[n])){valid=false;break;}
    ++n;if(!*p)break;start=p+1;
  }
  valid=valid && n==5 && values[3]<=values[4];
  lock_r();auto *slot=valid?text_slot(values[0]):NULL;
  auto *layout=slot && slot->state==3 && slot->canvas==values[1] &&
    (slot->generation==values[2] || (!values[2] && values[1]==1))?slot->layout:NULL;
  if(layout)xu_ui_text_retain(layout);unlock_r();
  valid=layout && text_boundary(layout,(unsigned)values[3]) && text_boundary(layout,(unsigned)values[4]);
  struct Rect{double x,y,w,h;};std::vector<Rect> rects;
  unsigned pos=(unsigned)values[3];
  while(valid && pos<values[4]) {
    double a[7],b[7];valid=text_query_layout(layout,1,pos,0,0,0,a) && text_query_layout(layout,1,pos,1,0,0,b);
    if(!valid)break;
    Rect r={std::min(a[4],b[4]),a[5],std::max(1.0,fabs(b[4]-a[4])),a[6]};
    if(fabs(a[5]-b[5])>0.01)r.w=1.0;
    if(!rects.empty()) {auto &last=rects.back();
      if(fabs(last.y-r.y)<0.01 && fabs(last.h-r.h)<0.01 && r.x<=last.x+last.w+0.01 && last.x<=r.x+r.w+0.01) {
        double right=std::max(last.x+last.w,r.x+r.w);last.x=std::min(last.x,r.x);last.w=right-last.x;
      }else rects.push_back(r);
    }else rects.push_back(r);
    unsigned next=(unsigned)(a[0]+a[1]);
    if(next<=pos) {next=pos+1;while(next<layout->length && !text_boundary(layout,next))++next;}
    pos=next;valid=rects.size()<=XU_UI_TEXT_MAX_LENGTH;
  }
  if(layout)xu_ui_text_release(layout);
  std::string out="XTS1";
  auto word=[&](uint64_t x,unsigned bytes){for(unsigned i=0;i<bytes;++i)out+=(char)(x>>(i*8));};
  word(valid?1:0,4);word(valid?rects.size():0,4);
  if(valid)for(auto r:rects)for(double x:{r.x,r.y,r.w,r.h}){uint64_t bits;memcpy(&bits,&x,8);word(bits,8);}
  return out;
}

int xu_ui_mem_try_read_len(const char *path_z, unsigned *out_len) {
  char tb[160];
  snprintf(tb, sizeof(tb), "mem_try_read_len: %s", path_z ? path_z : "(null)");
  do_trace(tb);
  bool exists = false; const unsigned char *asset = NULL; unsigned asset_len = 0;
  if (asset_lookup(path_z, &exists, &asset, &asset_len)) { if (out_len) *out_len = exists ? 1 : asset_len; return 1; }
  const char *key = mem_path_key(path_z);
  XuUiSlot *s;
  if (!xu_ui_mem_is_path(path_z)) return 0;
  if (!key) {
    if (out_len) *out_len = 0;
    return 1;
  }
  if (!strncmp(key,"__web_invoke_target/",20)) {if(out_len)*out_len=12;return 1;}
  if (!strcmp(key,"__web_invoke_id")) {if(out_len)*out_len=20;return 1;}
  if (!strcmp(key,"__xacp_generation")) {if(out_len)*out_len=20;return 1;}
  if (!strcmp(key,"__xacp_directory")) {if(out_len)*out_len=(unsigned)xacp_directory().size();return 1;}
  if (!strncmp(key,"__image_rgba/",13)) {if(out_len)*out_len=xacp_rgba_length(key);return 1;}
  if (!strncmp(key,"__web_invoke_packet/",20)) {uint64_t id=0;unsigned size=xu_request_id(key+20,&id)?web_packet_length(id):0;if(out_len)*out_len=size;return 1;}
  if (!strcmp(key,"__web_dispatch_running")) {if(out_len)*out_len=1;return 1;}
  if (!strcmp(key,"__web_invoke_take")) {if(out_len)*out_len=web_take_length();return 1;}
  if (strcmp(key, "__ui_protocol") == 0) {
    if (out_len) *out_len = 4;
    return 1;
  }
  if (!strcmp(key,"__window_reserve")) {if(out_len)*out_len=8;return 1;}
  if (!strncmp(key,"__native_view_reserve/",22)) {if(out_len)*out_len=8;return 1;}
  if (!strncmp(key,"__native_view_info/",19)) {if(out_len)*out_len=32;return 1;}
  if (!strncmp(key,"__window_info/",14)) {if(out_len)*out_len=24;return 1;}
  if (strcmp(key, "__ui_licenses") == 0) { if(out_len) *out_len=(unsigned)sizeof(g_ui_licenses)-1; return 1; }
  if (strcmp(key, "__request_id") == 0 || strcmp(key, "__image_id") == 0 || strcmp(key, "__text_id") == 0 || strcmp(key,"__display_list_id")==0 || strcmp(key, "__text_input_id") == 0 || strcmp(key, "__default_canvas") == 0) {
    if (out_len) *out_len = strcmp(key, "__default_canvas") == 0 ? 32 : 20;
    return 1;
  }
  if (strncmp(key, "__image_info/", 13) == 0) { if (out_len) *out_len = 32; return 1; }
  if(!strncmp(key,"__display_list_info/",20)) {if(out_len)*out_len=8;return 1;}
  if (strncmp(key, "__text_info/", 12) == 0) { if (out_len) *out_len = 80; return 1; }
  if (!strncmp(key,"__text_selection/",17)) {auto data=text_selection_record(key);if(out_len)*out_len=(unsigned)data.size();return 1;}
  if (text_query_key(key)) { if (out_len) *out_len = 72; return 1; }
  if (input_query_mode(key)) { if(out_len) *out_len=80; return 1; }
  if (!strncmp(key,"__text_input_info/",18)) { if(out_len) *out_len=XU_UI_TEXT_INPUT_SNAPSHOT_BYTES; return 1; }
  const char result_prefix[] = "__request_result/";
  if (strncmp(key, result_prefix, sizeof(result_prefix) - 1) == 0) {
    uint64_t id = 0;
    unsigned length = xu_request_id(key + sizeof(result_prefix) - 1, &id) ? request_result_len(id) : 0;
    if (out_len) *out_len = length;
    return 1;
  }
  if (key[0] == '_' && key[1] == '_' && strcmp(key, "__invoke_take") == 0) {
    return invoke_try_take_len(out_len);
  }
  if (strcmp(key, "__take_shell_event") == 0) { xu_ui_request_poll(); xu_ui_text_input_poll(); key = "xu_ui_shell_event.txt"; }
  if (out_len) *out_len = 0;
  lock_r();
  s = find_slot_unlocked(key);
  /* Missing mailbox slot == empty file. Never return -1: Xu compares the
   * full x0 to -1 on ARM64, but C int -1 is only in w0 — the check misses
   * and falls through to open()+throw, leaking ~64KB chunks unboundedly. */
  if (!s || !s->body) {
    unlock_r();
    return 1;
  }
  if (out_len) *out_len = s->len;
  unlock_r();
  return 1;
}

int xu_ui_mem_try_read_copy(const char *path_z, void *out, unsigned cap) {
  bool exists = false; const unsigned char *asset = NULL; unsigned asset_len = 0;
  if (asset_lookup(path_z, &exists, &asset, &asset_len)) {
    if (out && cap) {
      if (exists) { if (cap >= 2) { ((char *)out)[0] = asset ? '1' : '0'; ((char *)out)[1] = 0; } else ((char *)out)[0] = 0; }
      else { unsigned count = asset_len < cap ? asset_len : cap - 1;
        if (count) memcpy(out, asset, count); ((char *)out)[count] = 0; }
    }
    return 1;
  }
  const char *key = mem_path_key(path_z);
  XuUiSlot *s;
  unsigned copy;
  if (!xu_ui_mem_is_path(path_z)) return 0;
  if (!key) {
    if (out && cap) ((char *)out)[0] = 0;
    return 1;
  }
  /* A virtual path must never fall through to a real filesystem operation
   * merely because the destination buffer is unusable.  Treat it as an
   * empty handled read; callers can distinguish this from a non-virtual path
   * via the return value of xu_ui_mem_try_read_copy. */
  if (!out || cap == 0) return 1;
  if (!strcmp(key,"__xacp_generation")) {if(cap>=21)snprintf((char *)out,cap,"%020llu",(unsigned long long)g_xacp_generation.fetch_add(1));return 1;}
  if (!strcmp(key,"__xacp_directory")) {auto directory=xacp_directory();if(cap>directory.size())memcpy(out,directory.c_str(),directory.size()+1);else memset(out,0,cap);return 1;}
  if (!strncmp(key,"__image_rgba/",13)) {xacp_rgba_copy(key,out,cap);return 1;}
  if (!strncmp(key,"__web_invoke_target/",20)) {
    memset(out,0,cap);uint64_t id=0;unsigned identity[3]={};
    if(cap>=13 && xu_request_id(key+20,&id)){web_target(id,identity);auto *p=(unsigned char *)out;for(unsigned i=0;i<3;++i)for(unsigned j=0;j<4;++j)p[i*4+j]=(unsigned char)(identity[i]>>(j*8));}return 1;
  }
  if (!strcmp(key,"__web_invoke_id")) {if(cap>=21)snprintf((char *)out,cap,"%020llu",(unsigned long long)web_dispatch_reserve());else ((char *)out)[0]=0;return 1;}
  if (!strncmp(key,"__web_invoke_packet/",20)) {uint64_t id=0;if(xu_request_id(key+20,&id))web_packet_copy(id,out,cap);else memset(out,0,cap);return 1;}
  if (!strcmp(key,"__web_dispatch_running")) {((char *)out)[0]=web_running()?'1':'0';if(cap>1)((char *)out)[1]=0;return 1;}
  if (!strcmp(key,"__web_invoke_take")) {web_take_copy(out,cap);return 1;}
  if (!strncmp(key,"__window_info/",14)) {
    if(cap>=25){auto *p=(unsigned char *)out;memset(p,0,25);const char *separator=strchr(key+14,'/');uint64_t id=0,generation=0;unsigned meta[6]={};
      if(separator && request_number(key+14,(unsigned)(separator-key-14),0x7fffffff,&id) && xu_request_id(separator+1,&generation) && generation<=UINT32_MAX)
        xu_ui_window_info((unsigned)id,(unsigned)generation,meta,NULL,0);
      for(unsigned i=0;i<6;++i)for(unsigned j=0;j<4;++j)p[i*4+j]=(unsigned char)(meta[i]>>(j*8));
    }else ((char *)out)[0]=0;return 1;
  }
  if (!strncmp(key,"__native_view_info/",19)) {
    memset(out,0,cap);const char *separator=strchr(key+19,'/');uint64_t id=0,generation=0;unsigned meta[8]={};
    if(cap>=33 && separator && request_number(key+19,(unsigned)(separator-key-19),0x7fffffff,&id) && xu_request_id(separator+1,&generation) && generation<=UINT32_MAX){
      xu_ui_native_view_info((unsigned)id,(unsigned)generation,meta,NULL);auto *p=(unsigned char *)out;for(unsigned i=0;i<8;++i)for(unsigned j=0;j<4;++j)p[i*4+j]=(unsigned char)(meta[i]>>(j*8));}return 1;
  }
  if (!strncmp(key,"__native_view_reserve/",22)) {
    if(cap>=9){unsigned identity[2]={};native_view_reserve_key(key,identity);auto *p=(unsigned char *)out;
      for(unsigned i=0;i<2;++i)for(unsigned j=0;j<4;++j)p[i*4+j]=(unsigned char)(identity[i]>>(j*8));p[8]=0;
    }else ((char *)out)[0]=0;return 1;
  }
  if (!strcmp(key,"__window_reserve")) {
    if(cap>=9){unsigned identity[2]={};xu_ui_window_reserve(identity);auto *p=(unsigned char *)out;
      for(unsigned i=0;i<2;++i)for(unsigned j=0;j<4;++j)p[i*4+j]=(unsigned char)(identity[i]>>(j*8));p[8]=0;
    }else ((char *)out)[0]=0;return 1;
  }
  if (strcmp(key, "__ui_licenses") == 0) {
    unsigned size=(unsigned)sizeof(g_ui_licenses)-1; if(size>=cap) size=cap-1;
    memcpy(out,g_ui_licenses,size); ((char *)out)[size]=0; return 1;
  }
  if (!strncmp(key,"__text_selection/",17)) {auto data=text_selection_record(key);memset(out,0,cap);if(data.size()<cap)memcpy(out,data.data(),data.size());return 1;}
  if (text_query_key(key)) {
    if (cap < 73) ((char *)out)[0] = 0;
    else text_query_record(key, out);
    return 1;
  }
  if(input_query_mode(key)) {
    if(cap<81) ((char *)out)[0]=0; else input_query_record(key,out);
    return 1;
  }
  if (strcmp(key, "__request_id") == 0 || strcmp(key, "__image_id") == 0 || strcmp(key, "__text_id") == 0 || strcmp(key,"__display_list_id")==0 || strcmp(key, "__text_input_id") == 0) {
    if (cap >= 21) snprintf((char *)out, cap, "%020llu", (unsigned long long)
      (strcmp(key, "__image_id") == 0 ? xu_ui_image_reserve() :
       strcmp(key, "__text_id") == 0 ? xu_ui_text_reserve() :
       !strcmp(key,"__display_list_id") ? xu_ui_display_list_reserve() :
       strcmp(key, "__text_input_id") == 0 ? xu_ui_text_input_reserve() : xu_ui_request_reserve()));
    else ((char *)out)[0] = 0;
    return 1;
  }
  if (!strncmp(key,"__text_input_info/",18)) {
    uint64_t id=0;
    if(cap<XU_UI_TEXT_INPUT_SNAPSHOT_BYTES+1u) ((char *)out)[0]=0;
    else { (void)xu_request_id(key+18,&id); input_info_copy(id,out,cap); }
    return 1;
  }
  if (strncmp(key, "__text_info/", 12) == 0) {
    if (cap < 81) { ((char *)out)[0] = 0; return 1; }
    uint64_t id = 0; unsigned generation = 0; double metrics[8] = {};
    unsigned valid = xu_request_id(key + 12, &id) && xu_ui_text_info(id, metrics, &generation);
    auto *p = (unsigned char *)out; memset(p, 0, 81); memcpy(p, "XTM1", 4);
    for (unsigned i = 0; i < 4; ++i) { p[4 + i] = (unsigned char)(valid >> (i * 8)); p[8 + i] = (unsigned char)(generation >> (i * 8)); }
    for (unsigned i = 0; i < 8; ++i) {
      uint64_t bits; memcpy(&bits, &metrics[i], 8);
      for (unsigned j = 0; j < 8; ++j) p[16 + i * 8 + j] = (unsigned char)(bits >> (j * 8));
    }
    return 1;
  }
  if(!strncmp(key,"__display_list_info/",20)) {
    unsigned gen=0,cost=0;uint64_t id=0;
    if(xu_request_id(key+20,&id))xu_ui_display_list_info(id,&gen,&cost);
    if(cap>=9){auto *p=(unsigned char *)out;for(unsigned i=0;i<4;++i){p[i]=(unsigned char)(gen>>(8*i));p[4+i]=(unsigned char)(cost>>(8*i));}p[8]=0;}
    else ((char *)out)[0]=0;return 1;
  }
  if (strncmp(key, "__image_info/", 13) == 0) {
    if (cap < 33) { ((char *)out)[0] = 0; return 1; }
    uint64_t id = 0; unsigned width = 0, height = 0, generation = 0;
    if (xu_request_id(key + 13, &id)) xu_ui_image_info(id, &width, &height, &generation);
    snprintf((char *)out, cap, "%010u\t%010u\t%010u", width, height, generation); return 1;
  }
  if (strcmp(key, "__default_canvas") == 0) {
    if (cap < 33) { ((char *)out)[0] = 0; return 1; }
    unsigned window = 0, canvas = 0, generation = 0;
    lock_r();
    for (const auto &c : g_canvases) if (c.canvas_id == 1) { window = c.window_id; canvas = c.canvas_id; generation = c.generation; break; }
    unlock_r();
    snprintf((char *)out, cap, "%010u\t%010u\t%010u", window, canvas, generation);
    return 1;
  }
  const char result_prefix[] = "__request_result/";
  if (strncmp(key, result_prefix, sizeof(result_prefix) - 1) == 0) {
    uint64_t id = 0;
    if (xu_request_id(key + sizeof(result_prefix) - 1, &id)) request_result_copy(id, out, cap);
    else ((char *)out)[0] = 0;
    return 1;
  }
  if (strcmp(key, "__ui_protocol") == 0) {
    if (cap >= 5) memcpy(out, "XUI2", 5);
    else ((char *)out)[0] = 0;
    return 1;
  }
  if (key[0] == '_' && key[1] == '_' && strcmp(key, "__invoke_take") == 0) {
    return invoke_try_take_copy(out, cap);
  }
  if (strcmp(key, "__take_shell_event") == 0) {
    lock_w();
    s = find_slot_unlocked("xu_ui_shell_event.txt");
    copy = s && s->body ? s->len : 0;
    if (copy >= cap) {
      copy = cap - 1u;
      // The last queued move may have grown after read_len. Never consume
      // half a record; the next read retries with the current full length.
      while (copy && s->body[copy - 1] != '\n') --copy;
    }
    if (copy) memcpy(out, s->body, copy);
    ((char *)out)[copy] = 0;
    if (s && s->body && copy) {
      s->len -= copy;
      if (s->len) {
        memmove(s->body, s->body + copy, s->len + 1u);
      } else {
        free(s->body);
        memset(s, 0, sizeof(*s));
      }
    }
    request_flush();
    event_unlock();
    return 1;
  }
  lock_r();
  s = find_slot_unlocked(key);
  if (!s || !s->body) {
    ((char *)out)[0] = 0;
    unlock_r();
    return 1;
  }
  copy = s->len;
  if (copy >= cap) copy = cap - 1;
  if (copy) memcpy(out, s->body, copy);
  ((char *)out)[copy] = 0;
  unlock_r();
  return 1;
}
