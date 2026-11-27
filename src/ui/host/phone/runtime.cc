#include "phone.h"
#ifndef XU_PHONE_GAME
#include "../xu_ui_mem.h"
#endif
#include <atomic>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <limits.h>
#include <mutex>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>
#ifdef __APPLE__
#include <crt_externs.h>
#include <dirent.h>
#include <sys/event.h>
#include <sys/sysctl.h>
#else
#include <sys/epoll.h>
#include <sys/eventfd.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <sys/utsname.h>
#endif
#ifdef __ANDROID__
#include <android/log.h>
#endif

extern "C" void xu_app_start(int, char **, char **);
extern "C" [[noreturn]] void xu_phone_finish(long);
extern char **environ;
#ifndef XU_PHONE_GAME
extern "C" void xu_draw_text_init();
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
#else
extern "C" void xu_phone_game_mapped(void *, size_t);
extern "C" void xu_phone_game_unmapped(void *, size_t);
#endif
#ifdef __ANDROID__
#ifdef XU_PHONE_GAME
#define XU_ANDROID_LOG_TAG "XuGame"
#else
#define XU_ANDROID_LOG_TAG "XuPhone"
#endif
static void android_log_stdio(int fd, const void *buf, ssize_t count) {
  if ((fd != 1 && fd != 2) || count <= 0 || !buf) return;
  static thread_local char line[512];
  static thread_local size_t used = 0;
  static thread_local int last_fd = 1;
  auto flush = [](int stream) {
    if (!used) return;
    line[used] = 0;
    __android_log_print(stream == 2 ? ANDROID_LOG_ERROR : ANDROID_LOG_INFO, XU_ANDROID_LOG_TAG, "%s", line);
    used = 0;
  };
  if (used && last_fd != fd) flush(last_fd);
  last_fd = fd;
  const char *p = static_cast<const char *>(buf);
  for (ssize_t i = 0; i < count; ++i) {
    if (p[i] == '\n') {
      line[used] = 0;
      __android_log_print(fd == 2 ? ANDROID_LOG_ERROR : ANDROID_LOG_INFO, XU_ANDROID_LOG_TAG, "%s", line);
      used = 0;
    } else {
      line[used++] = p[i];
      if (used == sizeof(line) - 1) flush(fd);
    }
  }
}
#endif
// No private iOS system-call instructions. The runtime's Unix ABI is translated
// to public libc APIs here; unsupported services fail with -ENOSYS.
extern "C" long xu_phone_syscall(long nr, long a, long b, long c, long d, long e, long f) {
  long result = -1;
#ifdef __APPLE__
  switch (nr) {
    case -12: result = clock_gettime(CLOCK_MONOTONIC, (timespec *)a); break;
    case 1: xu_phone_finish(a);
    case 3: result = read((int)a, (void *)b, (size_t)c); break;
    case 4: result = write((int)a, (const void *)b, (size_t)c); break;
    case 5: result = open((const char *)a, (int)b, (mode_t)c); break;
    case 6: result = close((int)a); break;
    case 10: result = unlink((const char *)a); break;
    case 12: result = chdir((const char *)a); break;
    case 15: result = chmod((const char *)a, (mode_t)b); break;
    case 20: result = getpid(); break;
    case 24: result = getuid(); break;
    case 25: result = geteuid(); break;
    case 29: result = recvfrom((int)a, (void *)b, (size_t)c, (int)d, (struct sockaddr *)e, (socklen_t *)f); break;
    case 30: result = accept((int)a, (struct sockaddr *)b, (socklen_t *)c); break;
    case 31: result = getpeername((int)a, (struct sockaddr *)b, (socklen_t *)c); break;
    case 32: result = getsockname((int)a, (struct sockaddr *)b, (socklen_t *)c); break;
    case 37: result = kill((pid_t)a, (int)b); break;
    case 39: result = getppid(); break;
    case 43: result = getegid(); break;
    case 47: result = getgid(); break;
    case 57: result = symlink((const char *)a, (const char *)b); break;
    case 58: result = readlink((const char *)a, (char *)b, (size_t)c); break;
    case 73: result = munmap((void *)a, (size_t)b);
#ifdef XU_PHONE_GAME
      if (!result) xu_phone_game_unmapped((void *)a, (size_t)b);
#endif
      break;
    case 74: result = mprotect((void *)a, (size_t)b, (int)c); break;
    case 90: result = dup2((int)a, (int)b); break;
    case 92: result = fcntl((int)a, (int)b, c); break;
    case 93: { // Runtime select-based sleep, a timeval in the fifth argument.
      auto *tv = (timeval *)e;
      if (!tv) return -EINVAL;
      timespec ts{tv->tv_sec, tv->tv_usec * 1000};
      result = nanosleep(&ts, nullptr); break;
    }
    case 97: result = socket((int)a, (int)b, (int)c); break;
    case 98: result = connect((int)a, (const struct sockaddr *)b, (socklen_t)c); break;
    case 104: result = bind((int)a, (const struct sockaddr *)b, (socklen_t)c); break;
    case 105: result = setsockopt((int)a, (int)b, (int)c, (const void *)d, (socklen_t)e); break;
    case 106: result = listen((int)a, (int)b); break;
    case 116: result = gettimeofday((timeval *)a, nullptr); break;
    case 118: result = getsockopt((int)a, (int)b, (int)c, (void *)d, (socklen_t *)e); break;
    case 128: result = rename((const char *)a, (const char *)b); break;
    case 131: result = flock((int)a, (int)b); break;
    case 133: result = sendto((int)a, (const void *)b, (size_t)c, (int)d, (const struct sockaddr *)e, (socklen_t)f); break;
    case 134: result = shutdown((int)a, (int)b); break;
    case 136: result = mkdir((const char *)a, (mode_t)b); break;
    case 137: result = rmdir((const char *)a); break;
    case 197: { void *p = mmap((void *)a, (size_t)b, (int)c, (int)d, (int)e, (off_t)f);
#ifdef XU_PHONE_GAME
      if (p != MAP_FAILED) xu_phone_game_mapped(p, (size_t)b);
#endif
      return p == MAP_FAILED ? -errno : (long)p; }
    case 199: result = lseek((int)a, (off_t)b, (int)c); break;
    case 202: result = sysctl((int *)a, (u_int)b, (void *)c, (size_t *)d, (void *)e, (size_t)f); break;
    case 230: result = poll((struct pollfd *)a, (nfds_t)b, (int)c); break;
    case 338: result = stat((const char *)a, (struct stat *)b); break;
    case 344: {
      int fd = (int)a;
      char *buf = (char *)b;
      size_t bufsize = (size_t)c;
      int64_t *basep = (int64_t *)d;
      if (!buf || !basep) return -EFAULT;
      int dup_fd = dup(fd);
      if (dup_fd < 0) return -errno;
      DIR *dir = fdopendir(dup_fd);
      if (!dir) { int err = errno; close(dup_fd); return -err; }
      rewinddir(dir);
      int64_t skip = *basep;
      int64_t idx = 0;
      size_t used = 0;
      struct dirent *ent = nullptr;
      while ((ent = readdir(dir)) != nullptr) {
        if (idx < skip) { ++idx; continue; }
        size_t nlen = strlen(ent->d_name);
        if (nlen > 1023) nlen = 1023;
        size_t rec = (21 + nlen + 1 + 7) & ~size_t(7);
        if (used + rec > bufsize) {
          if (used == 0) { closedir(dir); return -EINVAL; }
          break;
        }
        char *out = buf + used;
        memset(out, 0, rec);
        uint64_t ino = (uint64_t)ent->d_ino;
        uint64_t seekoff = (uint64_t)(idx + 1);
        uint16_t rlen16 = (uint16_t)rec;
        uint16_t nlen16 = (uint16_t)nlen;
        memcpy(out + 0, &ino, 8);
        memcpy(out + 8, &seekoff, 8);
        memcpy(out + 16, &rlen16, 2);
        memcpy(out + 18, &nlen16, 2);
        out[20] = (char)ent->d_type;
        memcpy(out + 21, ent->d_name, nlen);
        used += rec;
        ++idx;
      }
      *basep = idx;
      closedir(dir);
      return (long)used;
    }
    case 362: result = kqueue(); break;
    case 363: result = kevent((int)a, (const struct kevent *)b, (int)c, (struct kevent *)d, (int)e, (const struct timespec *)f); break;
    case 500: {
      if (!a || (size_t)b > 256) return -EIO;
      arc4random_buf((void *)a, (size_t)b);
      return 0;
    }
    default: return -ENOSYS;
  }
#else
  switch (nr) {
    case 17: {
      if (!a || !b) return -EFAULT;
      if (!getcwd((char *)a, (size_t)b)) return -errno;
      return (long)(strlen((char *)a) + 1);
    }
    case 19: result = eventfd((unsigned int)a, (int)b); break;
    case 20: result = epoll_create1((int)a); break;
    case 21: result = epoll_ctl((int)a, (int)b, (int)c, (struct epoll_event *)d); break;
    case 22: result = epoll_pwait((int)a, (struct epoll_event *)b, (int)c, (int)d, (const sigset_t *)e); break;
    case 24: result = c ? dup3((int)a, (int)b, (int)c) : dup2((int)a, (int)b); break;
    case 25: result = fcntl((int)a, (int)b, c); break;
    case 29: result = ioctl((int)a, (unsigned long)b, c); break;
    case 32: result = flock((int)a, (int)b); break;
    case 34: result = mkdirat((int)a, (const char *)b, (mode_t)c); break;
    case 35: result = unlinkat((int)a, (const char *)b, (int)c); break;
    case 36: result = symlinkat((const char *)a, (int)b, (const char *)c); break;
    case 38: result = renameat((int)a, (const char *)b, (int)c, (const char *)d); break;
    case 49: result = chdir((const char *)a); break;
    case 53: result = fchmodat((int)a, (const char *)b, (mode_t)c, (int)d); break;
    case 56: result = openat((int)a, (const char *)b, (int)c, (mode_t)d); break;
    case 57: result = close((int)a); break;
    case 59: result = pipe2((int *)a, (int)b); break;
    case 61: result = syscall(SYS_getdents64, (int)a, (void *)b, (size_t)c); break;
    case 62: result = lseek((int)a, (off_t)b, (int)c); break;
    case 63: result = read((int)a, (void *)b, (size_t)c); break;
    case 64:
      result = write((int)a, (const void *)b, (size_t)c);
#ifdef __ANDROID__
      if (result > 0) android_log_stdio((int)a, (const void *)b, result);
#endif
      break;
    case 73: result = ppoll((struct pollfd *)a, (nfds_t)b, (const struct timespec *)c, (const sigset_t *)d); break;
    case 78: result = readlinkat((int)a, (const char *)b, (char *)c, (size_t)d); break;
    case 79: result = fstatat((int)a, (const char *)b, (struct stat *)c, (int)d); break;
    case 93: case 94: xu_phone_finish(a);
    case 101: result = nanosleep((const timespec *)a, (timespec *)b); break;
    case 113: result = clock_gettime((clockid_t)a, (timespec *)b); break;
    case 129: result = kill((pid_t)a, (int)b); break;
    case 160: result = uname((struct utsname *)a); break;
    case 172: result = getpid(); break;
    case 173: result = getppid(); break;
    case 174: result = getuid(); break;
    case 175: result = geteuid(); break;
    case 176: result = getgid(); break;
    case 177: result = getegid(); break;
    case 198: result = socket((int)a, (int)b, (int)c); break;
    case 200: result = bind((int)a, (const struct sockaddr *)b, (socklen_t)c); break;
    case 201: result = listen((int)a, (int)b); break;
    case 202: result = accept((int)a, (struct sockaddr *)b, (socklen_t *)c); break;
    case 203: result = connect((int)a, (const struct sockaddr *)b, (socklen_t)c); break;
    case 204: result = getsockname((int)a, (struct sockaddr *)b, (socklen_t *)c); break;
    case 205: result = getpeername((int)a, (struct sockaddr *)b, (socklen_t *)c); break;
    case 206: result = sendto((int)a, (const void *)b, (size_t)c, (int)d, (const struct sockaddr *)e, (socklen_t)f); break;
    case 207: result = recvfrom((int)a, (void *)b, (size_t)c, (int)d, (struct sockaddr *)e, (socklen_t *)f); break;
    case 208: result = setsockopt((int)a, (int)b, (int)c, (const void *)d, (socklen_t)e); break;
    case 209: result = getsockopt((int)a, (int)b, (int)c, (void *)d, (socklen_t *)e); break;
    case 210: result = shutdown((int)a, (int)b); break;
    case 215: result = munmap((void *)a, (size_t)b);
#ifdef XU_PHONE_GAME
      if (!result) xu_phone_game_unmapped((void *)a, (size_t)b);
#endif
      break;
    case 222: { void *p = mmap((void *)a, (size_t)b, (int)c, (int)d, (int)e, (off_t)f);
#ifdef XU_PHONE_GAME
      if (p != MAP_FAILED) xu_phone_game_mapped(p, (size_t)b);
#endif
      return p == MAP_FAILED ? -errno : (long)p; }
    case 226: result = mprotect((void *)a, (size_t)b, (int)c); break;
    case 276: result = e ? -ENOSYS : renameat((int)a, (const char *)b, (int)c, (const char *)d); break;
    case 278: {
      if (!a && b) return -EFAULT;
      long r = syscall(SYS_getrandom, (void *)a, (size_t)b, (unsigned int)c);
      if (r >= 0) return r;
      if (errno != ENOSYS) return -errno;
      int ufd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
      if (ufd < 0) return -errno;
      ssize_t rd = read(ufd, (void *)a, (size_t)b);
      int saved = errno;
      close(ufd);
      return rd < 0 ? -saved : (long)rd;
    }
    default: return -ENOSYS;
  }
#endif
  return result == -1 ? -errno : result;
}
#ifndef XU_PHONE_GAME
static std::mutex wake_mu;
static std::condition_variable wake_cv;
static std::atomic<uint64_t> wake_seq{0};
static std::atomic<int64_t> last_wake_ms{0};

static int64_t steady_now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

extern "C" void xu_phone_wake() {
  last_wake_ms.store(steady_now_ms(), std::memory_order_relaxed);
  {
    std::lock_guard<std::mutex> lk(wake_mu);
    wake_seq.fetch_add(1, std::memory_order_release);
  }
  wake_cv.notify_all();
}

extern "C" int xu_ui_host_run_cooperative(const char *, int (*pump)(void *, int (*)(void)),
                                           void *context, int (*yield_task)(void)) {
  xu_ui_mem_set_task_pump(pump, context, yield_task);
  xu_ui_host_set_kick(xu_phone_wake);
  last_wake_ms.store(steady_now_ms(), std::memory_order_relaxed);
  while (!stopped.load()) {
    uint64_t seen = wake_seq.load(std::memory_order_acquire);
    if (active.load() && pump && yield_task) pump(context, yield_task);
    if (stopped.load()) break;
    if (wake_seq.load(std::memory_order_acquire) != seen) continue;
    int64_t now_ms = steady_now_ms();
    bool recent = (now_ms - last_wake_ms.load(std::memory_order_relaxed)) < 250;
    int wait_ms = !active.load() ? 500 : (recent ? 8 : 100);
    std::unique_lock<std::mutex> lk(wake_mu);
    wake_cv.wait_for(lk, std::chrono::milliseconds(wait_ms), [&] {
      return stopped.load() || wake_seq.load(std::memory_order_acquire) != seen;
    });
  }
  xu_ui_host_set_kick(nullptr);
  xu_ui_mem_set_task_pump(nullptr, nullptr, nullptr);
  return 0;
}
extern "C" void xu_phone_active(int value) {
  if (!value) xu_phone_input(77, 0, 0, 0);
  active.store(value != 0);
  xu_ui_mem_append("xu_ui_shell_event.txt", value ? "focused" : "blurred", 1);
  xu_phone_wake();
}
extern "C" void xu_phone_stop() {
  xu_ui_mem_append("xu_ui_shell_event.txt", "exit", 1);
  stopped.store(true);
  xu_phone_wake();
}
static char **clone_environ(char **src) {
  size_t count = 0;
  if (src) {
    while (src[count]) ++count;
  }
  char **copy = static_cast<char **>(std::calloc(count + 1, sizeof(char *)));
  if (!copy) return nullptr;
  for (size_t i = 0; i < count; ++i) {
    size_t len = std::strlen(src[i]) + 1;
    copy[i] = static_cast<char *>(std::malloc(len));
    if (!copy[i]) {
      for (size_t j = 0; j < i; ++j) std::free(copy[j]);
      std::free(copy);
      return nullptr;
    }
    std::memcpy(copy[i], src[i], len);
  }
  copy[count] = nullptr;
  return copy;
}
static void free_environ(char **envp) {
  if (!envp) return;
  for (size_t i = 0; envp[i]; ++i) std::free(envp[i]);
  std::free(envp);
}
static void *worker(void *) {
  char name[] = "XuPhone";
  char *args[] = {name, nullptr};
#ifdef __APPLE__
  char **raw_env = *_NSGetEnviron();
#else
  char **raw_env = environ;
#endif
  char **env = clone_environ(raw_env);
  xu_app_start(1, args, env ? env : raw_env);
  free_environ(env);
  return nullptr;
}
extern "C" void xu_phone_set_paths(const char *data_root, const char *resource_root) {
  if (data_root && *data_root) {
    setenv("XU_PHONE_DATA_ROOT", data_root, 1);
#ifndef XU_PHONE_GAME
    xu_ui_mem_set("phone_data_root", data_root);
#endif
  }
  if (resource_root && *resource_root) {
    setenv("XU_PHONE_RESOURCE_ROOT", resource_root, 1);
#ifndef XU_PHONE_GAME
    xu_ui_mem_set("phone_resource_root", resource_root);
#endif
  }
}
extern "C" void xu_phone_set_network_env(const char *dns_servers, const char *ca_bundle_path) {
  if (dns_servers && *dns_servers) {
    setenv("XU_DNS_SERVER", dns_servers, 1);
#ifndef XU_PHONE_GAME
    xu_ui_mem_set("phone_dns_servers", dns_servers);
#endif
  }
  if (ca_bundle_path && *ca_bundle_path) {
    setenv("SSL_CERT_FILE", ca_bundle_path, 1);
#ifndef XU_PHONE_GAME
    xu_ui_mem_set("phone_ca_bundle", ca_bundle_path);
#endif
  }
}
extern "C" void xu_phone_start(const char *platform) {
  if (started.exchange(true)) { xu_phone_redraw(); return; }
  setenv("XU_UI_PACK", "1", 1);
  setenv("XU_UI_WWW", ":mem:", 1);
  setenv("XU_PHONE_OS", platform, 1);
  unsetenv("XU_UI_TMP");
  xu_draw_text_init();
  pthread_attr_t attr;
  bool has_attr = pthread_attr_init(&attr) == 0;
  if (has_attr) {
    size_t stack_sz = 4u * 1024u * 1024u;
#ifdef PTHREAD_STACK_MIN
    if (stack_sz < static_cast<size_t>(PTHREAD_STACK_MIN)) stack_sz = static_cast<size_t>(PTHREAD_STACK_MIN);
#endif
    pthread_attr_setstacksize(&attr, stack_sz);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
  }
  pthread_t thread;
  int rc = pthread_create(&thread, has_attr ? &attr : nullptr, worker, nullptr);
  if (has_attr) pthread_attr_destroy(&attr);
  if (rc != 0) abort();
  if (!has_attr) pthread_detach(thread);
}
#endif
