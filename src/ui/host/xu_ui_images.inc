// Internal implementation, included once by xu_ui_mem.cc after the canvas registry.
// Registry mutations use g_lock. Bitmap references/budget can be released without
// that lock, including while the registry drops its last user reference.
#include "xu_ui_images.h"
#include <new>
#include <stddef.h>
#ifndef _WIN32
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

// stb_image is compiled once, without file I/O or unrelated image formats.
// Its allocations are bounded globally, including simultaneous decoders and
// realloc's temporary overlap. Native bitmap storage has its own 64 MiB budget.
static const size_t IMAGE_DECODE_MAX_BYTES = 128u * 1024u * 1024u;
static std::atomic<size_t> g_image_decode_bytes{0};
struct alignas(max_align_t) XuImageAllocation { size_t bytes; };
static void *image_decode_alloc(size_t bytes) {
  if (bytes > IMAGE_DECODE_MAX_BYTES - sizeof(XuImageAllocation)) return NULL;
  size_t total = bytes + sizeof(XuImageAllocation), used = g_image_decode_bytes.load(std::memory_order_relaxed);
  do { if (total > IMAGE_DECODE_MAX_BYTES - used) return NULL; }
  while (!g_image_decode_bytes.compare_exchange_weak(used, used + total, std::memory_order_relaxed));
  auto *allocation = (XuImageAllocation *)malloc(total);
  if (!allocation) { g_image_decode_bytes.fetch_sub(total, std::memory_order_relaxed); return NULL; }
  allocation->bytes = total; return allocation + 1;
}
static void image_decode_free(void *data) {
  if (!data) return;
  auto *allocation = (XuImageAllocation *)data - 1;
  g_image_decode_bytes.fetch_sub(allocation->bytes, std::memory_order_relaxed); free(allocation);
}
static void *image_decode_realloc(void *data, size_t bytes) {
  if (!bytes) { image_decode_free(data); return NULL; }
  void *next = image_decode_alloc(bytes); if (!next) return NULL;
  if (data) {
    size_t previous = ((XuImageAllocation *)data - 1)->bytes - sizeof(XuImageAllocation);
    memcpy(next, data, previous < bytes ? previous : bytes); image_decode_free(data);
  }
  return next;
}
#define STB_IMAGE_STATIC
#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_PNG
#define STBI_ONLY_JPEG
#define STBI_NO_STDIO
#define STBI_NO_HDR
#define STBI_NO_LINEAR
#define STBI_NO_FAILURE_STRINGS
#define STBI_MAX_DIMENSIONS XU_UI_IMAGE_MAX_DIMENSION
#define STBI_MALLOC(size) image_decode_alloc(size)
#define STBI_REALLOC(data, size) image_decode_realloc(data, size)
#define STBI_FREE(data) image_decode_free(data)
#if defined(__aarch64__) && !defined(_MSC_VER)
#define STBI_NEON
#endif
#include "third_party/stb/stb_image.h"

struct XuUiBitmap {
  std::atomic<unsigned> references{1};
  uint64_t id;
  unsigned width, height, bytes, revision;
  unsigned char *pixels;
};
enum { IMAGE_RESERVED = 1, IMAGE_UPLOADING = 2, IMAGE_LIVE = 3 };
struct XuImageSlot {
  uint64_t id;
  unsigned canvas, generation, state;
  long long reservation_deadline;
  XuUiBitmap *bitmap;
};
static XuImageSlot g_images[XU_UI_IMAGE_MAX_COUNT];
static uint64_t g_image_id = 0;
static std::atomic<unsigned> g_image_bytes{0};
static_assert((XU_UI_IMAGE_MAX_COUNT & (XU_UI_IMAGE_MAX_COUNT - 1u)) == 0, "image slots must be a power of two");
static long long image_now(void) {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
    std::chrono::steady_clock::now().time_since_epoch()).count();
}
static XuImageSlot *image_slot(uint64_t id) {
  if (!id) return NULL;
  auto *slot = &g_images[id & (XU_UI_IMAGE_MAX_COUNT - 1u)];
  return slot->id == id ? slot : NULL;
}
static bool image_target(unsigned canvas, unsigned generation, unsigned *actual) {
  if (!canvas || canvas > 0x7fffffffu || (!generation && canvas != 1)) return false;
  for (const auto &c : g_canvases) {
    if (c.canvas_id == canvas && (!generation || c.generation == generation)) { *actual = c.generation; return true; }
  }
  if (!generation && canvas == 1 && !g_canvas_started) { *actual = 0; return true; }
  return false;
}
static bool image_binding_alive(const XuImageSlot &slot) {
  // Only resources admitted before registration can remain unbound. Canvas 1
  // adopts them on first open; close then removes the adopted resource.
  if (!slot.generation && slot.canvas == 1) return true;
  unsigned actual = 0;
  return image_target(slot.canvas, slot.generation, &actual);
}
static bool image_owner(const XuImageSlot &slot, unsigned canvas, unsigned generation) {
  return slot.canvas == canvas && (slot.generation == generation || (!generation && canvas == 1));
}
void xu_ui_bitmap_retain(XuUiBitmap *bitmap) {
  if (bitmap) bitmap->references.fetch_add(1, std::memory_order_relaxed);
}
void xu_ui_bitmap_release(XuUiBitmap *bitmap) {
  if (bitmap && bitmap->references.fetch_sub(1, std::memory_order_acq_rel) == 1) {
    g_image_bytes.fetch_sub(bitmap->bytes, std::memory_order_relaxed);
    free(bitmap->pixels); delete bitmap;
  }
}
unsigned xu_ui_image_live_bytes(void) { return g_image_bytes.load(std::memory_order_relaxed); }
const unsigned char *xu_ui_bitmap_pixels(const XuUiBitmap *bitmap, unsigned *width, unsigned *height) {
  if (width) *width = bitmap ? bitmap->width : 0;
  if (height) *height = bitmap ? bitmap->height : 0;
  return bitmap ? bitmap->pixels : NULL;
}
static bool image_size(unsigned width, unsigned height, unsigned stride, unsigned length, unsigned *bytes) {
  if (!width || !height || width > XU_UI_IMAGE_MAX_DIMENSION || height > XU_UI_IMAGE_MAX_DIMENSION || stride < width * 4u) return false;
  uint64_t dense = (uint64_t)width * height * 4u, source = (uint64_t)stride * height;
  if (dense > XU_UI_IMAGE_MAX_BYTES || source > XU_UI_MEM_MAX_PAYLOAD || source != length) return false;
  *bytes = (unsigned)dense; return true;
}
static XuUiBitmap *image_allocate(uint64_t id, unsigned width, unsigned height, bool clear=false) {
  unsigned bytes=0;
  if(!image_size(width,height,width*4u,width*height*4u,&bytes)) return NULL;
  unsigned used = g_image_bytes.load(std::memory_order_relaxed);
  do {
    if (bytes > XU_UI_IMAGE_MAX_BYTES - used) return NULL;
  } while (!g_image_bytes.compare_exchange_weak(used, used + bytes, std::memory_order_relaxed));
  auto *bitmap = new(std::nothrow) XuUiBitmap;
  unsigned char *pixels = (unsigned char *)malloc(bytes);
  if (!bitmap || !pixels) { delete bitmap; free(pixels); g_image_bytes.fetch_sub(bytes, std::memory_order_relaxed); return NULL; }
  bitmap->id = id; bitmap->width = width; bitmap->height = height; bitmap->bytes = bytes; bitmap->revision = 1; bitmap->pixels = pixels;
  if(clear) memset(pixels,0,bytes);
  return bitmap;
}
static XuUiBitmap *image_copy_rgba(uint64_t id, unsigned width, unsigned height, unsigned stride,
                                    const void *data, unsigned length) {
  unsigned bytes=0;
  if(!data || !image_size(width,height,stride,length,&bytes)) return NULL;
  auto *bitmap=image_allocate(id,width,height);
  if(!bitmap) return NULL;
  auto *pixels=bitmap->pixels;
  const auto *rgba = (const unsigned char *)data;
  for (unsigned y = 0; y < height; ++y) {
    const unsigned char *source = rgba + (size_t)y * stride;
    unsigned char *target = pixels + (size_t)y * width * 4u;
    for (unsigned x = 0; x < width; ++x) {
      unsigned a = source[x * 4 + 3];
      target[x * 4] = (unsigned char)((source[x * 4 + 2] * a + 127u) / 255u);
      target[x * 4 + 1] = (unsigned char)((source[x * 4 + 1] * a + 127u) / 255u);
      target[x * 4 + 2] = (unsigned char)((source[x * 4] * a + 127u) / 255u);
      target[x * 4 + 3] = (unsigned char)a;
    }
  }
  return bitmap;
}
uint64_t xu_ui_image_reserve(void) {
  lock_w();
  long long now = image_now();
  for (auto &slot : g_images) if (slot.state == IMAGE_RESERVED && slot.reservation_deadline <= now) slot = {};
  uint64_t id = 0;
  for (unsigned i = 0; i < XU_UI_IMAGE_MAX_COUNT && g_image_id < INT64_MAX; ++i) {
    uint64_t candidate = ++g_image_id;
    auto &slot = g_images[candidate & (XU_UI_IMAGE_MAX_COUNT - 1u)];
    if (slot.id) continue;
    slot.id = candidate; slot.state = IMAGE_RESERVED; slot.reservation_deadline = now + 10000;
    id = candidate; break;
  }
  unlock_w(); return id;
}
void xu_ui_image_abandon(uint64_t id) {
  lock_w(); auto *slot = image_slot(id);
  if (slot && slot->state != IMAGE_LIVE) *slot = {};
  unlock_w();
}
static bool image_begin_upload(uint64_t id, unsigned canvas, unsigned generation) {
  unsigned actual = 0;
  lock_w(); auto *slot = image_slot(id);
  if (!slot || slot->state != IMAGE_RESERVED || !image_target(canvas, generation, &actual)) { unlock_w(); return false; }
  slot->canvas = canvas; slot->generation = actual; slot->state = IMAGE_UPLOADING;
  unlock_w(); return true;
}
static int image_finish_upload(uint64_t id, XuUiBitmap *bitmap) {
  lock_w(); auto *slot = image_slot(id);
  bool accepted = bitmap && slot && slot->state == IMAGE_UPLOADING && image_binding_alive(*slot);
  if (accepted) { slot->bitmap = bitmap; slot->state = IMAGE_LIVE; }
  else if (slot && slot->state == IMAGE_UPLOADING) {
    slot->state = IMAGE_RESERVED; slot->canvas = slot->generation = 0; slot->reservation_deadline = image_now() + 10000;
  }
  unlock_w();
  if (!accepted) xu_ui_bitmap_release(bitmap);
  return accepted ? 1 : 0;
}
int xu_ui_image_create_rgba(uint64_t id, unsigned canvas, unsigned generation, unsigned width, unsigned height,
                            unsigned stride, const void *rgba, unsigned length) {
  unsigned bytes = 0;
  if (!rgba || !image_size(width, height, stride, length, &bytes) || !image_begin_upload(id, canvas, generation)) return 0;
  return image_finish_upload(id, image_copy_rgba(id, width, height, stride, rgba, length));
}
static XuUiBitmap *image_decode_bitmap(uint64_t id, const void *data, unsigned length) {
  int width = 0, height = 0, channels = 0;
  unsigned bytes = 0;
  auto *encoded = (const unsigned char *)data;
  XuUiBitmap *bitmap = NULL;
  if (stbi_info_from_memory(encoded, (int)length, &width, &height, &channels) && width > 0 && height > 0 &&
      (uint64_t)width * height * 4 <= XU_UI_IMAGE_MAX_BYTES &&
      image_size((unsigned)width, (unsigned)height, (unsigned)width * 4, (unsigned)width * height * 4, &bytes) &&
      bytes <= XU_UI_IMAGE_MAX_BYTES - g_image_bytes.load(std::memory_order_relaxed)) {
    int decoded_width = 0, decoded_height = 0;
    auto *rgba = stbi_load_from_memory(encoded, (int)length, &decoded_width, &decoded_height, &channels, 4);
    if (rgba && decoded_width == width && decoded_height == height)
      bitmap = image_copy_rgba(id, (unsigned)width, (unsigned)height, (unsigned)width * 4, rgba, bytes);
    stbi_image_free(rgba);
  }
  return bitmap;
}
int xu_ui_image_create_encoded(uint64_t id, unsigned canvas, unsigned generation, const void *data, unsigned length) {
  if (!data || !length || length > XU_UI_MEM_MAX_PAYLOAD || !image_begin_upload(id, canvas, generation)) return 0;
  return image_finish_upload(id, image_decode_bitmap(id, data, length));
}
int xu_ui_image_load_file(uint64_t id, unsigned canvas, unsigned generation, const char *path, unsigned length) {
  if (!path || !length || length > 4096 || !xdf_utf8((const unsigned char *)path, length) ||
      !image_begin_upload(id, canvas, generation)) return 0;
  XuUiBitmap *bitmap = NULL; unsigned char *data = NULL; unsigned size = 0, received = 0;
  std::string name(path, length);
#ifdef _WIN32
  int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, name.c_str(), (int)length, NULL, 0);
  std::wstring wide((size_t)count, L'\0');
  if (count) MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, name.c_str(), (int)length, &wide[0], count);
  HANDLE file = count ? CreateFileW(wide.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                                    NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL) : INVALID_HANDLE_VALUE;
  LARGE_INTEGER file_size = {};
  if (file != INVALID_HANDLE_VALUE && GetFileType(file) == FILE_TYPE_DISK && GetFileSizeEx(file, &file_size) &&
      file_size.QuadPart > 0 && file_size.QuadPart <= XU_UI_MEM_MAX_PAYLOAD) size = (unsigned)file_size.QuadPart;
  if (size) data = (unsigned char *)image_decode_alloc(size);
  while (data && received < size) {
    DWORD read = 0;
    if (!ReadFile(file, data + received, size - received, &read, NULL) || !read) break;
    received += read;
  }
  if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
#else
  // Nonblocking open plus regular-file validation excludes FIFOs/devices from
  // this bounded image loader without altering the standard read_file API.
  int file = open(name.c_str(), O_RDONLY | O_CLOEXEC | O_NONBLOCK);
  struct stat status = {};
  if (file >= 0 && !fstat(file, &status) && S_ISREG(status.st_mode) && status.st_size > 0 &&
      (uint64_t)status.st_size <= XU_UI_MEM_MAX_PAYLOAD) size = (unsigned)status.st_size;
  if (size) data = (unsigned char *)image_decode_alloc(size);
  while (data && received < size) {
    ssize_t read = ::read(file, data + received, size - received);
    if (read < 0 && errno == EINTR) continue;
    if (read <= 0) break;
    received += (unsigned)read;
  }
  if (file >= 0) close(file);
#endif
  if (data && received == size) bitmap = image_decode_bitmap(id, data, size);
  image_decode_free(data);
  return image_finish_upload(id, bitmap);
}
int xu_ui_image_update_rgba(uint64_t id, unsigned canvas, unsigned generation, unsigned width, unsigned height,
                            unsigned stride, const void *rgba, unsigned length) {
  unsigned bytes = 0;
  if (!rgba || !image_size(width, height, stride, length, &bytes)) return 0;
  lock_w(); auto *slot = image_slot(id);
  bool valid = slot && slot->state == IMAGE_LIVE && image_owner(*slot, canvas, generation) && image_binding_alive(*slot) &&
               slot->bitmap->width == width && slot->bitmap->height == height && slot->bitmap->revision < UINT32_MAX;
  unlock_w(); if (!valid) return 0;
  auto *bitmap = image_copy_rgba(id, width, height, stride, rgba, length); if (!bitmap) return 0;
  lock_w(); slot = image_slot(id); XuUiBitmap *previous = NULL;
  valid = slot && slot->state == IMAGE_LIVE && image_owner(*slot, canvas, generation) && image_binding_alive(*slot) &&
          slot->bitmap->width == width && slot->bitmap->height == height && slot->bitmap->revision < UINT32_MAX;
  if (valid) { previous = slot->bitmap; bitmap->revision = previous->revision + 1; slot->bitmap = bitmap; }
  unlock_w();
  xu_ui_bitmap_release(valid ? previous : bitmap); return valid ? 1 : 0;
}
int xu_ui_image_dispose(uint64_t id, unsigned canvas, unsigned generation) {
  lock_w(); auto *slot = image_slot(id); XuUiBitmap *bitmap = NULL;
  bool valid = slot && slot->state != IMAGE_RESERVED && image_owner(*slot, canvas, generation);
  if (valid) { bitmap = slot->bitmap; *slot = {}; }
  unlock_w(); xu_ui_bitmap_release(bitmap); return valid ? 1 : 0;
}
int xu_ui_image_info(uint64_t id, unsigned *width, unsigned *height, unsigned *generation) {
  if (width) *width = 0; if (height) *height = 0; if (generation) *generation = 0;
  lock_r(); auto *slot = image_slot(id); bool valid = slot && slot->state == IMAGE_LIVE;
  if (valid) { if (width) *width = slot->bitmap->width; if (height) *height = slot->bitmap->height; if (generation) *generation = slot->generation; }
  unlock_r(); return valid ? 1 : 0;
}
static void image_adopt_canvas(unsigned canvas, unsigned generation) {
  if (canvas == 1) for (auto &slot : g_images) if (slot.canvas == 1 && !slot.generation) slot.generation = generation;
}
static void image_close_canvas(unsigned canvas, unsigned generation) {
  for (auto &slot : g_images) if (slot.canvas == canvas && slot.generation == generation) {
    auto *bitmap = slot.bitmap; slot = {}; xu_ui_bitmap_release(bitmap);
  }
}
static XuUiBitmap *image_snapshot(uint64_t id, unsigned canvas, unsigned generation) {
  auto *slot = image_slot(id);
  if (!slot || slot->state != IMAGE_LIVE || slot->canvas != canvas || slot->generation != generation) return NULL;
  xu_ui_bitmap_retain(slot->bitmap); return slot->bitmap;
}
static int image_upload(const void *data, unsigned length) {
  if (!data || length < 40 || length > XU_UI_IMAGE_MAX_BYTES + 40u) return 0;
  auto *p = (const unsigned char *)data;
  if (memcmp(p, "XUI1", 4) || xdf_u16(p + 4) != 1 || xdf_u32(p + 36)) return 0;
  unsigned format = xdf_u16(p + 6), canvas = xdf_u32(p + 16), generation = xdf_u32(p + 20);
  uint64_t id = (uint64_t)xdf_u32(p + 8) | ((uint64_t)xdf_u32(p + 12) << 32);
  if (!id || id > INT64_MAX) return 0;
  unsigned width = xdf_u32(p + 24), height = xdf_u32(p + 28), stride = xdf_u32(p + 32);
  if (format == 1 && !width && !height && !stride) return xu_ui_image_create_encoded(id, canvas, generation, p + 40, length - 40);
  if (format == 3 && !width && !height && !stride) return xu_ui_image_load_file(id, canvas, generation, (const char *)p + 40, length - 40);
  if (format == 0) return xu_ui_image_create_rgba(id, canvas, generation, width, height, stride, p + 40, length - 40);
  if (format == 2) return xu_ui_image_update_rgba(id, canvas, generation, width, height, stride, p + 40, length - 40);
  return 0;
}
