// Private XACP file sink. All names are generated integers; directory handles
// pin the validated directories across concurrent path replacement. No path
// from a control request reaches these filesystem operations.
#include <deque>
#include <map>
#include <mutex>
#ifndef _WIN32
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

static std::atomic<uint64_t> g_xacp_generation{1};
static std::mutex g_xacp_files_mutex;
static std::string xacp_directory() {
#ifdef _WIN32
  return ""; // POSIX private-directory semantics are required by this sink.
#else
  const char *runtime = getenv("XDG_RUNTIME_DIR");
  const char *tmp = getenv("TMPDIR");
  std::string base = runtime && *runtime ? std::string(runtime) + "/xacp" :
    std::string(tmp && *tmp ? tmp : "/tmp") + "/xacp-" + std::to_string(getuid());
  if (base.empty() || base[0] != '/') return "";
  return base + "/" + std::to_string(getpid());
#endif
}

#ifndef _WIN32
struct XacpFiles {
  int directory = -1;
  std::deque<std::string> names;
};
static std::map<uint64_t, XacpFiles> g_xacp_files;
static dev_t g_xacp_directory_device;
static ino_t g_xacp_directory_inode;
static bool g_xacp_directory_valid = false;

static void xacp_remove_empty_directory() {
  if (!g_xacp_directory_valid) return;
  auto directory = xacp_directory(); struct stat info;
  if (!directory.empty() && !lstat(directory.c_str(), &info) && S_ISDIR(info.st_mode) &&
      info.st_dev == g_xacp_directory_device && info.st_ino == g_xacp_directory_inode &&
      !rmdir(directory.c_str())) g_xacp_directory_valid = false;
}

struct XacpExitCleanup {
  ~XacpExitCleanup() {
    // Embedded hosts may exit through libc without closing their listeners.
    // Never wait for a writer during process shutdown.
    if (!g_xacp_files_mutex.try_lock()) return;
    for (auto &entry : g_xacp_files) {
      for (const auto &name : entry.second.names) unlinkat(entry.second.directory, name.c_str(), 0);
      close(entry.second.directory);
    }
    g_xacp_files.clear(); xacp_remove_empty_directory(); g_xacp_files_mutex.unlock();
  }
};
static XacpExitCleanup g_xacp_exit_cleanup;

static int xacp_private_directory(int parent, const char *name) {
  if (mkdirat(parent, name, 0700) && errno != EEXIST) return -1;
  int fd = openat(parent, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  struct stat info;
  if (fd < 0) return -1;
  if (fstat(fd, &info) || !S_ISDIR(info.st_mode) || info.st_uid != getuid() || (info.st_mode & 07077)) {
    close(fd); return -1;
  }
  return fd;
}

static int xacp_open_directory() {
  const char *runtime = getenv("XDG_RUNTIME_DIR"), *tmp = getenv("TMPDIR");
  std::string base = runtime && *runtime ? runtime : tmp && *tmp ? tmp : "/tmp";
  if (base.empty() || base[0] != '/') return -1;
  int root = open(base.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (root < 0) return -1;
  std::string name = runtime && *runtime ? "xacp" : "xacp-" + std::to_string(getuid());
  int parent = xacp_private_directory(root, name.c_str()); close(root);
  if (parent < 0) return -1;
  int fd = xacp_private_directory(parent, std::to_string(getpid()).c_str()); close(parent);
  struct stat info;
  if (fd >= 0 && !fstat(fd, &info)) {
    g_xacp_directory_device = info.st_dev; g_xacp_directory_inode = info.st_ino; g_xacp_directory_valid = true;
  }
  return fd;
}
#endif

static bool xacp_file_name(const std::string &name) {
  if (name.compare(0, 5, "shot-")) return false;
  size_t i = 5, start = i;
  while (i < name.size() && name[i] >= '0' && name[i] <= '9') ++i;
  if (i == start || i == name.size() || name[i++] != '-') return false;
  start = i;
  while (i < name.size() && name[i] >= '0' && name[i] <= '9') ++i;
  return i > start && name.compare(i, std::string::npos, ".png") == 0;
}

static bool xacp_file_numbers(const char *key, const char *prefix, uint64_t *generation, uint64_t *id) {
  const char *start = key + strlen(prefix), *slash = strchr(start, '/');
  return slash && request_number(start, (unsigned)(slash-start), INT64_MAX, generation) && *generation &&
    request_number(slash+1, (unsigned)strlen(slash+1), INT64_MAX, id) && *id;
}

static bool xacp_write_file(const char *key, const void *data, unsigned length) {
#ifdef _WIN32
  return false;
#else
  uint64_t generation = 0, id = 0;
  if (!xacp_file_numbers(key, "__xacp_file/", &generation, &id) || !data || !length || length > 32u*1024u*1024u) return false;
  std::string name = "shot-" + std::to_string(generation) + "-" + std::to_string(id) + ".png";
  if (!xacp_file_name(name)) return false; // ^shot-[0-9]+-[0-9]+\.png$
  std::lock_guard<std::mutex> lock(g_xacp_files_mutex);
  int directory = xacp_open_directory();
  if (directory < 0) return false;
  auto previous = g_xacp_files.find(generation);
  if (previous != g_xacp_files.end()) {
    struct stat old_info, new_info;
    if (fstat(previous->second.directory, &old_info) || fstat(directory, &new_info) ||
        old_info.st_dev != new_info.st_dev || old_info.st_ino != new_info.st_ino) {
      close(directory); return false;
    }
  }
  int fd = openat(directory, name.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
  if (fd < 0) { close(directory); return false; }
  bool ok = fchmod(fd, 0600) == 0;
  size_t offset = 0;
  while (ok && offset < length) {
    ssize_t count = write(fd, (const char *)data + offset, length - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) ok = false;
    else offset += (size_t)count;
  }
  if (close(fd)) ok = false;
  if (!ok) { unlinkat(directory, name.c_str(), 0); close(directory); return false; }
  auto &files = g_xacp_files[generation];
  if (files.directory < 0) files.directory = directory;
  else close(directory);
  files.names.push_back(name);
  if (files.names.size() > 16) {
    if (unlinkat(files.directory, files.names.front().c_str(), 0) && errno != ENOENT) {
      unlinkat(files.directory, name.c_str(), 0); files.names.pop_back(); return false;
    }
    files.names.pop_front();
  }
  return true;
#endif
}

static void xacp_cleanup_files(const char *key) {
#ifndef _WIN32
  uint64_t generation = 0;
  if (!xu_request_id(key + strlen("__xacp_cleanup/"), &generation)) return;
  std::lock_guard<std::mutex> lock(g_xacp_files_mutex);
  auto found = g_xacp_files.find(generation);
  if (found != g_xacp_files.end()) {
    for (const auto &name : found->second.names) unlinkat(found->second.directory, name.c_str(), 0);
    close(found->second.directory); g_xacp_files.erase(found);
  }
  if (g_xacp_files.empty()) xacp_remove_empty_directory();
#endif
}

// A retained bitmap is copied while holding its resource lock. Converting
// premultiplied native pixels to straight RGBA never mutates the source.
static XuUiBitmap *xacp_bitmap(const char *key) {
  uint64_t values[3] = {}; const char *start = key + strlen("__image_rgba/");
  for (unsigned i = 0; i < 3; ++i) {
    const char *end = i == 2 ? start + strlen(start) : strchr(start, '/');
    if (!end || !request_number(start, (unsigned)(end-start), i ? UINT32_MAX : INT64_MAX, &values[i])) return NULL;
    start = end + (i < 2 ? 1 : 0);
  }
  lock_r(); auto *slot = image_slot(values[0]);
  auto *bitmap = slot && slot->state == IMAGE_LIVE && slot->canvas == values[1] &&
    (slot->generation == values[2] || (!values[2] && values[1] == 1)) ? slot->bitmap : NULL;
  if (bitmap) xu_ui_bitmap_retain(bitmap);
  unlock_r(); return bitmap;
}

static unsigned xacp_rgba_length(const char *key) {
  auto *bitmap = xacp_bitmap(key); unsigned size = bitmap ? bitmap->bytes : 0;
  xu_ui_bitmap_release(bitmap); return size;
}

static void xacp_rgba_copy(const char *key, void *output, unsigned capacity) {
  auto *bitmap = xacp_bitmap(key); auto *out = (unsigned char *)output;
  memset(out, 0, capacity);
  if (bitmap && capacity > bitmap->bytes) {
    for (unsigned i = 0; i < bitmap->bytes; i += 4) {
      unsigned alpha = bitmap->pixels[i+3]; out[i+3] = (unsigned char)alpha;
      for (unsigned c = 0; c < 3; ++c) out[i+c] = alpha ? (unsigned char)((bitmap->pixels[i+2-c]*255u + alpha/2u)/alpha) : 0;
    }
  }
  xu_ui_bitmap_release(bitmap);
}
