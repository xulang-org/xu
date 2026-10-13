#include "xu_ui_mem.h"

#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

static void read_expect_missing(const char *name) {
  char out[16] = "sentinel";
  assert(xu_ui_mem_get(name, out, sizeof(out)) == -1);
  assert(out[0] == '\0');
}

int main() {
  unsigned out = 99;
  unsigned len = 99;

  static_assert(XU_UI_MEM_MAX_PAYLOAD < (unsigned)INT_MAX,
                "xu_ui_mem_get's int result must remain representable");

  /* Short and empty virtual paths are handled by the mailbox, but must not
   * create an empty-name slot or fall through to a real filesystem open. */
  assert(!xu_ui_mem_is_path(":"));
  assert(!xu_ui_mem_is_path(":xu"));
  assert(xu_ui_mem_is_path(":xu:"));
  assert(xu_ui_mem_try_write(":xu:", "x", 1, &out) == 1);
  assert(out == 0);
  read_expect_missing("");
  assert(xu_ui_mem_wait_nonempty("", 0) == -1);

  xu_ui_mem_set_n("", "x", 1);
  read_expect_missing("");

  /* Exactly the documented name limit is valid. */
  char exact_name[XU_UI_MEM_MAX_NAME + 1u];
  memset(exact_name, 'n', XU_UI_MEM_MAX_NAME);
  exact_name[XU_UI_MEM_MAX_NAME] = '\0';
  xu_ui_mem_set(exact_name, "ok");
  char exact_out[8] = {0};
  assert(xu_ui_mem_get(exact_name, exact_out, sizeof(exact_out)) == 2);
  assert(strcmp(exact_out, "ok") == 0);
  xu_ui_mem_clear(exact_name);

  /* Names that differ only after the old fixed buffer must not alias. */
  char long_a[XU_UI_MEM_MAX_NAME + 2u];
  char long_b[XU_UI_MEM_MAX_NAME + 2u];
  memset(long_a, 'x', XU_UI_MEM_MAX_NAME);
  memset(long_b, 'x', XU_UI_MEM_MAX_NAME);
  long_a[XU_UI_MEM_MAX_NAME] = 'a';
  long_b[XU_UI_MEM_MAX_NAME] = 'b';
  long_a[XU_UI_MEM_MAX_NAME + 1u] = '\0';
  long_b[XU_UI_MEM_MAX_NAME + 1u] = '\0';
  xu_ui_mem_set(long_a, "a");
  xu_ui_mem_set(long_b, "b");
  read_expect_missing(long_a);
  read_expect_missing(long_b);
  char long_path[5u + sizeof(long_a)];
  memcpy(long_path, ":xu:/", 5u);
  memcpy(long_path + 5u, long_a, sizeof(long_a));
  out = 99;
  assert(xu_ui_mem_try_write(long_path, "x", 1, &out) == 1);
  assert(out == 0);
  char invalid_read[9] = "sentinel";
  assert(xu_ui_mem_try_read_copy(long_path, invalid_read,
                                 sizeof(invalid_read)) == 1);
  assert(invalid_read[0] == '\0');

  /* A non-zero byte count must never make a null source look like data. */
  assert(xu_ui_mem_try_write(":xu:/boundary", nullptr, 1, &out) == 1);
  assert(out == 0);
  assert(xu_ui_mem_try_read_len(":xu:/boundary", &len) == 1);
  assert(len == 0);

  xu_ui_mem_set_n("boundary", nullptr, UINT_MAX);
  len = 99;
  assert(xu_ui_mem_try_read_len(":xu:/boundary", &len) == 1);
  assert(len == 0);

  /* The same validation must short-circuit hostile maximum lengths before
   * any size arithmetic or allocation is attempted. */
  out = 99;
  assert(xu_ui_mem_try_write(":xu:/boundary", nullptr, UINT_MAX, &out) == 1);
  assert(out == 0);
  len = 99;
  assert(xu_ui_mem_try_read_len(":xu:/boundary", &len) == 1);
  assert(len == 0);

  const char body[] = "ok";
  assert(xu_ui_mem_try_write(":xu:/boundary", body, 2, &out) == 1);
  assert(out == 2);
  len = 0;
  assert(xu_ui_mem_try_read_len(":xu:/boundary", &len) == 1);
  assert(len == 2);

  /* Oversized writes are rejected before malloc/memcpy and report zero bytes
   * accepted.  The previous value must remain intact. */
  const char keep[] = "keep";
  assert(xu_ui_mem_try_write(":xu:/boundary", keep, 4, &out) == 1);
  assert(out == 4);
  assert(xu_ui_mem_try_write(":xu:/boundary", keep,
                             XU_UI_MEM_MAX_PAYLOAD + 1u, &out) == 1);
  assert(out == 0);
  len = 0;
  assert(xu_ui_mem_try_read_len(":xu:/boundary", &len) == 1);
  assert(len == 4);
  char keep_out[8] = {0};
  assert(xu_ui_mem_get("boundary", keep_out, sizeof(keep_out)) == 4);
  assert(strcmp(keep_out, keep) == 0);

  /* The explicit setter has no return value, but it must apply the same
   * limit and leave the previous body untouched. */
  xu_ui_mem_set_n("boundary", keep, XU_UI_MEM_MAX_PAYLOAD + 1u);
  assert(xu_ui_mem_get("boundary", keep_out, sizeof(keep_out)) == 4);
  assert(strcmp(keep_out, keep) == 0);

  xu_ui_mem_clear("boundary");

  /* Clearing a slot must reclaim its table entry, not just its body.  This
   * loop intentionally creates more names than the fixed table can hold. */
  char transient[32];
  for (unsigned i = 0; i < 160u; ++i) {
    int written = snprintf(transient, sizeof(transient), "transient_%u", i);
    assert(written > 0 && (size_t)written < sizeof(transient));
    xu_ui_mem_set(transient, "x");
    xu_ui_mem_clear(transient);
  }
  xu_ui_mem_set("reclaimed_after_clear", "ok");
  assert(xu_ui_mem_get("reclaimed_after_clear", exact_out,
                       sizeof(exact_out)) == 2);
  xu_ui_mem_clear("reclaimed_after_clear");
  return 0;
}
