// In-process string slots for Xu UI host ↔ worker (no TEMP xu_ui_* directory).

#include "xu_ui_mem.h"

#include <stdint.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
static SRWLOCK g_lock = SRWLOCK_INIT;
static CRITICAL_SECTION g_wait_cs;
static CONDITION_VARIABLE g_wait_cv;
static LONG g_wait_init = 0;
static void lock_w(void) { AcquireSRWLockExclusive(&g_lock); }
static void unlock_w(void) { ReleaseSRWLockExclusive(&g_lock); }
static void lock_r(void) { AcquireSRWLockShared(&g_lock); }
static void unlock_r(void) { ReleaseSRWLockShared(&g_lock); }
static void wait_init(void) {
  if (InterlockedCompareExchange(&g_wait_init, 1, 0) == 0) {
    InitializeCriticalSection(&g_wait_cs);
    InitializeConditionVariable(&g_wait_cv);
    InterlockedExchange(&g_wait_init, 2);
  } else {
    while (g_wait_init != 2) Sleep(0);
  }
}
static void wake_waiters(void) {
  wait_init();
  EnterCriticalSection(&g_wait_cs);
  WakeAllConditionVariable(&g_wait_cv);
  LeaveCriticalSection(&g_wait_cs);
}
#else
#include <errno.h>
#include <pthread.h>
#include <sys/time.h>
#include <time.h>
static pthread_rwlock_t g_lock = PTHREAD_RWLOCK_INITIALIZER;
static pthread_mutex_t g_wait_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_wait_cv = PTHREAD_COND_INITIALIZER;
static void lock_w(void) { pthread_rwlock_wrlock(&g_lock); }
static void unlock_w(void) { pthread_rwlock_unlock(&g_lock); }
static void lock_r(void) { pthread_rwlock_rdlock(&g_lock); }
static void unlock_r(void) { pthread_rwlock_unlock(&g_lock); }
static void wake_waiters(void) {
  pthread_mutex_lock(&g_wait_mu);
  pthread_cond_broadcast(&g_wait_cv);
  pthread_mutex_unlock(&g_wait_mu);
}
#endif

/* ---- Sync scheme invoke (Host ↔ Xu worker). Not slot/file shaped. ---- */
enum { INV_IDLE = 0, INV_REQ = 1, INV_BUSY = 2, INV_RESP = 3 };

#ifdef _WIN32
static CRITICAL_SECTION g_inv_cs;
static CONDITION_VARIABLE g_inv_cv;
static LONG g_inv_init = 0;
static void inv_init(void) {
  if (InterlockedCompareExchange(&g_inv_init, 1, 0) == 0) {
    InitializeCriticalSection(&g_inv_cs);
    InitializeConditionVariable(&g_inv_cv);
    InterlockedExchange(&g_inv_init, 2);
  } else {
    while (g_inv_init != 2) Sleep(0);
  }
}
static void inv_lock(void) { inv_init(); EnterCriticalSection(&g_inv_cs); }
static void inv_unlock(void) { LeaveCriticalSection(&g_inv_cs); }
static void inv_signal(void) {
  inv_init();
  WakeAllConditionVariable(&g_inv_cv);
}
static void inv_wait(DWORD ms) {
  SleepConditionVariableCS(&g_inv_cv, &g_inv_cs, ms == 0 ? INFINITE : ms);
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

static xu_ui_host_kick_fn g_host_kick = NULL;

void xu_ui_host_set_kick(xu_ui_host_kick_fn fn) { g_host_kick = fn; }

void xu_ui_host_kick(void) {
  if (g_host_kick) g_host_kick();
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

void xu_ui_mem_append(const char *name, const char *body, int add_nl) {
  const char *key = slot_key(name);
  const char *b = body ? body : "";
  unsigned blen;
  XuUiSlot *s;
  unsigned nlen;
  size_t bytes;
  char *nbuf;
  if (!key || !cstr_len_u32(b, &blen) || !payload_len_allowed(blen)) return;
  lock_w();
  s = alloc_slot_unlocked(key);
  if (!s) {
    unlock_w();
    return;
  }
  if (!u32_add3_checked(s->len, blen, add_nl ? 1u : 0u, &nlen) ||
      !payload_len_allowed(nlen) ||
      !alloc_bytes_for_u32(nlen, &bytes)) {
    unlock_w();
    return;
  }
  nbuf = (char *)malloc(bytes);
  if (!nbuf) {
    unlock_w();
    return;
  }
  if (s->len && s->body) memcpy(nbuf, s->body, s->len);
  if (blen) memcpy(nbuf + s->len, b, blen);
  if (add_nl) nbuf[s->len + blen] = '\n';
  nbuf[nlen] = 0;
  free(s->body);
  s->body = nbuf;
  s->len = nlen;
  unlock_w();
  wake_waiters();
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
    /* Reclaim the table entry as well as its body.  Keeping used=1 forever
     * made 128 transient slot names exhaust the mailbox even after callers
     * had explicitly cleared them. */
    s->name[0] = '\0';
    s->used = 0;
  }
  unlock_w();
  wake_waiters();
}

int xu_ui_mem_wait_nonempty(const char *name, int timeout_ms) {
  const char *key = slot_key(name);
  if (!key || !key[0]) return -1;
  if (timeout_ms < 0) timeout_ms = 0;
  if (slot_nonempty(key)) return 1;
  if (timeout_ms == 0) return 0;

  /* IMPORTANT: never take the slot rwlock while holding g_wait_mu/CS.
   * Writers do lock_w → unlock_w → wake(wait_mu). Taking rwlock under wait_mu
   * deadlocks the invoke path (permanent hang on button click). */

#ifdef _WIN32
  {
    DWORD start = GetTickCount();
    wait_init();
    for (;;) {
      DWORD elapsed, remain, slice;
      if (slot_nonempty(key)) return 1;
      elapsed = GetTickCount() - start;
      if (elapsed >= (DWORD)timeout_ms) return slot_nonempty(key) ? 1 : 0;
      remain = (DWORD)timeout_ms - elapsed;
      /* Full remain: writers broadcast. Capping at 50ms added up to ~50ms invoke lag. */
      slice = remain;
      EnterCriticalSection(&g_wait_cs);
      SleepConditionVariableCS(&g_wait_cv, &g_wait_cs, slice);
      LeaveCriticalSection(&g_wait_cs);
    }
  }
#else
  {
    struct timeval tv0;
    struct timespec deadline;
    gettimeofday(&tv0, NULL);
    deadline.tv_sec = tv0.tv_sec + timeout_ms / 1000;
    deadline.tv_nsec = (long)tv0.tv_usec * 1000L + (long)(timeout_ms % 1000) * 1000000L;
    if (deadline.tv_nsec >= 1000000000L) {
      deadline.tv_sec += 1;
      deadline.tv_nsec -= 1000000000L;
    }
    for (;;) {
      struct timeval now;
      struct timespec slice_dl;
      long long remain_ms;
      if (slot_nonempty(key)) return 1;
      gettimeofday(&now, NULL);
      remain_ms = ((long long)deadline.tv_sec - (long long)now.tv_sec) * 1000LL +
                  ((long long)deadline.tv_nsec / 1000000LL - (long long)now.tv_usec / 1000LL);
      if (remain_ms <= 0) return slot_nonempty(key) ? 1 : 0;
      /* Wait until deadline (writers broadcast); no 50ms poll lag. */
      slice_dl = deadline;
      pthread_mutex_lock(&g_wait_mu);
      pthread_cond_timedwait(&g_wait_cv, &g_wait_mu, &slice_dl);
      pthread_mutex_unlock(&g_wait_mu);
    }
  }
#endif
}

int xu_ui_mem_wait_ne(const char *name, const char *old_body, int timeout_ms) {
  const char *key = slot_key(name);
  if (!key || !key[0]) return -1;
  if (timeout_ms < 0) timeout_ms = 0;
  if (!slot_body_eq(key, old_body)) return 1;
  if (timeout_ms == 0) return 0;

#ifdef _WIN32
  {
    DWORD start = GetTickCount();
    wait_init();
    for (;;) {
      DWORD elapsed, remain, slice;
      if (!slot_body_eq(key, old_body)) return 1;
      elapsed = GetTickCount() - start;
      if (elapsed >= (DWORD)timeout_ms) return slot_body_eq(key, old_body) ? 0 : 1;
      remain = (DWORD)timeout_ms - elapsed;
      slice = remain;
      EnterCriticalSection(&g_wait_cs);
      SleepConditionVariableCS(&g_wait_cv, &g_wait_cs, slice);
      LeaveCriticalSection(&g_wait_cs);
    }
  }
#else
  {
    struct timeval tv0;
    struct timespec deadline;
    gettimeofday(&tv0, NULL);
    deadline.tv_sec = tv0.tv_sec + timeout_ms / 1000;
    deadline.tv_nsec = (long)tv0.tv_usec * 1000L + (long)(timeout_ms % 1000) * 1000000L;
    if (deadline.tv_nsec >= 1000000000L) {
      deadline.tv_sec += 1;
      deadline.tv_nsec -= 1000000000L;
    }
    for (;;) {
      struct timeval now;
      long long remain_ms;
      if (!slot_body_eq(key, old_body)) return 1;
      gettimeofday(&now, NULL);
      remain_ms = ((long long)deadline.tv_sec - (long long)now.tv_sec) * 1000LL +
                  ((long long)deadline.tv_nsec / 1000000LL - (long long)now.tv_usec / 1000LL);
      if (remain_ms <= 0) return slot_body_eq(key, old_body) ? 0 : 1;
      pthread_mutex_lock(&g_wait_mu);
      pthread_cond_timedwait(&g_wait_cv, &g_wait_mu, &deadline);
      pthread_mutex_unlock(&g_wait_mu);
    }
  }
#endif
}

int xu_ui_mem_wait_ipc(int timeout_ms) {
  /* Invoke-only park. Shell events are drained on a separate Xu thread and
   * must NOT wake this wait — otherwise the invoke loop busy-spins while the
   * page floods progress/moved lines into xu_ui_shell_event.txt. */
  if (timeout_ms < 0) timeout_ms = 0;
  if (invoke_pending()) return 1;
  if (slot_nonempty("xu_ui_ipc_req.txt")) return 1;
  if (timeout_ms == 0) return 0;

#ifdef _WIN32
  {
    DWORD start = GetTickCount();
    wait_init();
    for (;;) {
      DWORD elapsed, remain, slice;
      if (invoke_pending()) return 1;
      if (slot_nonempty("xu_ui_ipc_req.txt")) return 1;
      elapsed = GetTickCount() - start;
      if (elapsed >= (DWORD)timeout_ms) {
        if (invoke_pending()) return 1;
        if (slot_nonempty("xu_ui_ipc_req.txt")) return 1;
        return 0;
      }
      remain = (DWORD)timeout_ms - elapsed;
      slice = remain;
      EnterCriticalSection(&g_wait_cs);
      SleepConditionVariableCS(&g_wait_cv, &g_wait_cs, slice);
      LeaveCriticalSection(&g_wait_cs);
    }
  }
#else
  {
    struct timeval tv0;
    struct timespec deadline;
    gettimeofday(&tv0, NULL);
    deadline.tv_sec = tv0.tv_sec + timeout_ms / 1000;
    deadline.tv_nsec = (long)tv0.tv_usec * 1000L + (long)(timeout_ms % 1000) * 1000000L;
    if (deadline.tv_nsec >= 1000000000L) {
      deadline.tv_sec += 1;
      deadline.tv_nsec -= 1000000000L;
    }
    for (;;) {
      struct timeval now;
      long long remain_ms;
      if (invoke_pending()) return 1;
      if (slot_nonempty("xu_ui_ipc_req.txt")) return 1;
      gettimeofday(&now, NULL);
      remain_ms = ((long long)deadline.tv_sec - (long long)now.tv_sec) * 1000LL +
                  ((long long)deadline.tv_nsec / 1000000LL - (long long)now.tv_usec / 1000LL);
      if (remain_ms <= 0) {
        if (invoke_pending()) return 1;
        if (slot_nonempty("xu_ui_ipc_req.txt")) return 1;
        return 0;
      }
      pthread_mutex_lock(&g_wait_mu);
      pthread_cond_timedwait(&g_wait_cv, &g_wait_mu, &deadline);
      pthread_mutex_unlock(&g_wait_mu);
    }
  }
#endif
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

int xu_ui_mem_try_write(const char *path_z, const void *data, unsigned data_len, unsigned *out_n) {
  const char *key = mem_path_key(path_z);
  int ms;
  if (!xu_ui_mem_is_path(path_z)) return 0;
  /* A syntactically virtual but invalid/empty/overlong slot is still handled
   * by the mailbox.  Returning 0 here would make the Xu runtime fall through
   * to a real filesystem open on a path that was meant to stay in-process. */
  if (!key) {
    if (out_n) *out_n = 0;
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

int xu_ui_mem_try_read_len(const char *path_z, unsigned *out_len) {
  const char *key = mem_path_key(path_z);
  XuUiSlot *s;
  if (!xu_ui_mem_is_path(path_z)) return 0;
  if (!key) {
    if (out_len) *out_len = 0;
    return 1;
  }
  if (key[0] == '_' && key[1] == '_' && strcmp(key, "__invoke_take") == 0) {
    return invoke_try_take_len(out_len);
  }
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
  if (key[0] == '_' && key[1] == '_' && strcmp(key, "__invoke_take") == 0) {
    return invoke_try_take_copy(out, cap);
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
