#include "phone.h"
#include "../xu_ui_mem.h"
#include <atomic>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <pthread.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>
#ifdef __APPLE__
#include <crt_externs.h>
#endif

extern "C" void xu_draw_text_init();
extern "C" void xu_app_start(int, char **, char **);
extern char **environ;
static std::atomic<bool> started{false}, stopped{false}, active{true};
static thread_local void *state;
extern "C" void *xu_phone_state() {
  state = calloc(1, 65536);
  if (!state) abort();
  return state;
}
extern "C" [[noreturn]] void xu_phone_finish(long status) {
  fprintf(stderr, "Xu Phone worker finished: %ld\n", status);
  free(state); state = nullptr;
  pthread_exit(nullptr);
}
// No private iOS system-call instructions. The runtime's Unix ABI is translated
// to public libc APIs here; unsupported services fail with -ENOSYS.
extern "C" long xu_phone_syscall(long nr, long a, long b, long c, long d, long e, long f) {
  (void)f;
  long result = -1;
#ifdef __APPLE__
  switch (nr) {
    case -12: result = clock_gettime(CLOCK_MONOTONIC, (timespec *)a); break;
    case 1: xu_phone_finish(a);
    case 3: result = read((int)a, (void *)b, c); break;
    case 4: result = write((int)a, (void *)b, c); break;
    case 5: result = open((char *)a, (int)b, (mode_t)c); break;
    case 6: result = close((int)a); break;
    case 12: result = chdir((char *)a); break;
    case 20: result = getpid(); break;
    case 73: result = munmap((void *)a, b); break;
    case 93: { // Runtime select-based sleep, a timeval in the fifth argument.
      auto *tv = (timeval *)e;
      if (!tv) return -EINVAL;
      timespec ts{tv->tv_sec, tv->tv_usec * 1000};
      result = nanosleep(&ts, nullptr); break;
    }
    case 116: result = gettimeofday((timeval *)a, nullptr); break;
    case 197: { void *p = mmap((void *)a, b, (int)c, (int)d, (int)e, 0);
      return p == MAP_FAILED ? -errno : (long)p; }
    case 199: result = lseek((int)a, b, (int)c); break;
    case 338: result = stat((char *)a, (struct stat *)b); break;
    default: return -ENOSYS;
  }
#else
  switch (nr) {
    case 56: result = openat((int)a, (char *)b, (int)c, (mode_t)d); break;
    case 57: result = close((int)a); break;
    case 62: result = lseek((int)a, b, (int)c); break;
    case 63: result = read((int)a, (void *)b, c); break;
    case 64: result = write((int)a, (void *)b, c); break;
    case 93: case 94: xu_phone_finish(a);
    case 101: result = nanosleep((timespec *)a, (timespec *)b); break;
    case 113: result = clock_gettime((clockid_t)a, (timespec *)b); break;
    case 172: result = getpid(); break;
    case 215: result = munmap((void *)a, b); break;
    case 222: { void *p = mmap((void *)a, b, (int)c, (int)d, (int)e, 0);
      return p == MAP_FAILED ? -errno : (long)p; }
    default: return -ENOSYS;
  }
#endif
  return result == -1 ? -errno : result;
}
extern "C" int xu_ui_host_run_cooperative(const char *, int (*pump)(void *, int (*)(void)),
                                           void *context, int (*yield_task)(void)) {
  xu_ui_mem_set_task_pump(pump, context, yield_task);
  while (!stopped.load()) {
    if (active.load() && pump && yield_task) pump(context, yield_task);
    timespec delay{0, active.load() ? 1000000L : 16000000L};
    nanosleep(&delay, nullptr);
  }
  xu_ui_mem_set_task_pump(nullptr, nullptr, nullptr);
  return 0;
}
extern "C" void xu_phone_active(int value) {
  if (!value) xu_phone_input(77, 0, 0, 0);
  active.store(value != 0);
  xu_ui_mem_append("xu_ui_shell_event.txt", value ? "focused" : "blurred", 1);
}
extern "C" void xu_phone_stop() {
  xu_ui_mem_append("xu_ui_shell_event.txt", "exit", 1);
  stopped.store(true);
}
static void *worker(void *) {
  char name[] = "XuPhone";
  char *args[] = {name, nullptr};
#ifdef __APPLE__
  char **env = *_NSGetEnviron();
#else
  char **env = environ;
#endif
  xu_app_start(1, args, env);
  return nullptr;
}
extern "C" void xu_phone_start(const char *platform) {
  if (started.exchange(true)) { xu_phone_redraw(); return; }
  setenv("XU_UI_PACK", "1", 1);
  setenv("XU_UI_WWW", ":mem:", 1);
  setenv("XU_PHONE_OS", platform, 1);
  unsetenv("XU_UI_TMP");
  xu_draw_text_init();
  pthread_t thread;
  if (pthread_create(&thread, nullptr, worker, nullptr) != 0) abort();
  pthread_detach(thread);
}
