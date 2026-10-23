#include "xu_pack_assets.h"

#include <string.h>

/* Strong defs come from pack www/icon blob .o; weak empties from xu_pack_assets_weak.c. */
extern const XuWwwFile xu_pack_www_files[];
extern const unsigned xu_pack_www_files_count;
extern const unsigned char xu_pack_icon_png[];
extern const unsigned int xu_pack_icon_png_len;
extern const unsigned char xu_pack_icon_ico[];
extern const unsigned int xu_pack_icon_ico_len;

int xu_pack_has_www(void) {
  return xu_pack_www_files_count > 0 && xu_pack_www_files != 0 &&
         xu_pack_www_files[0].path != 0;
}

int xu_pack_has_icon(void) { return xu_pack_icon_png_len > 0 && xu_pack_icon_png != 0; }

int xu_pack_icon(const unsigned char **data, unsigned *len) {
  if (!xu_pack_has_icon()) return 0;
  if (data) *data = xu_pack_icon_png;
  if (len) *len = xu_pack_icon_png_len;
  return 1;
}

int xu_pack_get_icon_ico(const unsigned char **data, unsigned *len) {
  if (!(xu_pack_icon_ico_len > 0 && xu_pack_icon_ico != 0)) return 0;
  if (data) *data = xu_pack_icon_ico;
  if (len) *len = xu_pack_icon_ico_len;
  return 1;
}

static int looks_like_desktop_icon(const char *p) {
  size_t n;
  if (!p || !p[0]) return 0;
  n = strlen(p);
  if (n >= 17 && strcmp(p + n - 17, "xu_app_logo.png") == 0) return 1;
  if (n >= 17 && strcmp(p + n - 17, "xu_app_icon.png") == 0) return 1;
  if (strstr(p, "brand/xu_app_logo") != 0) return 1;
  if (strstr(p, "brand\\xu_app_logo") != 0) return 1;
  if (strstr(p, "brand/xu_app_icon") != 0) return 1;
  if (strstr(p, "brand\\xu_app_icon") != 0) return 1;
  if (strcmp(p, "brand/icon.png") == 0 || strcmp(p, "brand\\icon.png") == 0) return 1;
  return 0;
}

static int find_www_exact(const char *p, const unsigned char **data, unsigned *len) {
  unsigned i;
  if (!p || !p[0] || !xu_pack_has_www()) return 0;
  for (i = 0; i < xu_pack_www_files_count; i++) {
    const char *fp = xu_pack_www_files[i].path;
    if (!fp) continue;
    if (strcmp(fp, p) == 0) {
      if (data) *data = xu_pack_www_files[i].data;
      if (len) *len = xu_pack_www_files[i].len;
      return 1;
    }
  }
  return 0;
}
const unsigned char *xu_pack_asset_ptr(const char *relative_path, unsigned *len) {
  const unsigned char *data = 0; unsigned size = 0;
  if (find_www_exact(relative_path, &data, &size)) { if (len) *len = size; return data; }
  if (len) *len = 0;
  return 0;
}

static const char *skip_slashes(const char *p) {
  if (!p) return "";
  while (*p == '/' || *p == '\\') p++;
  return p;
}

int xu_pack_find_www(const char *rel, const unsigned char **data, unsigned *len) {
  const char *p = skip_slashes(rel);
  if (!p[0] || strcmp(p, "index.html") == 0) p = "index.html";
  if (strcmp(p, "favicon.ico") == 0) {
    if (find_www_exact("brand/xu_classic.svg", data, len)) return 1;
    if (find_www_exact("brand/xu_classic.png", data, len)) return 1;
    if (find_www_exact("brand/xu_app_logo.png", data, len)) return 1;
    p = "brand/xu_app_icon.png";
  }
  if (find_www_exact(p, data, len)) return 1;
  if (looks_like_desktop_icon(p)) return xu_pack_icon(data, len);
  return 0;
}

XuPackSlice xu_pack_www_slice(const char *rel) {
  XuPackSlice s = {0, 0};
  const unsigned char *p = 0;
  unsigned n = 0;
  if (xu_pack_find_www(rel, &p, &n)) {
    s.data = p;
    s.len = n;
  }
  return s;
}

XuPackSlice xu_pack_icon_slice(void) {
  XuPackSlice s = {0, 0};
  const unsigned char *p = 0;
  unsigned n = 0;
  if (xu_pack_icon(&p, &n)) {
    s.data = p;
    s.len = n;
  }
  return s;
}

XuPackSlice xu_pack_path_slice(const char *path) {
  XuPackSlice s = {0, 0};
  const unsigned char *p = 0;
  unsigned n = 0;
  if (xu_pack_file_for_path(path, &p, &n)) {
    s.data = p;
    s.len = n;
  }
  return s;
}

int xu_pack_file_for_path(const char *path, const unsigned char **data, unsigned *len) {
  const char *p;
  const char *slash;
  if (!path || !path[0]) return 0;
  if (xu_pack_find_www(path, data, len)) return 1;
  p = path;
  /* last path component */
  slash = strrchr(p, '/');
  if (!slash) slash = strrchr(p, '\\');
  if (slash && slash[1] && xu_pack_find_www(slash + 1, data, len)) return 1;
  /* trailing brand/file */
  slash = strstr(p, "brand/");
  if (slash && xu_pack_find_www(slash, data, len)) return 1;
  slash = strstr(p, "brand\\");
  if (slash && xu_pack_find_www("brand/xu_app_logo.png", data, len)) return 1;
  if (looks_like_desktop_icon(p)) return xu_pack_icon(data, len);
  return 0;
}

const unsigned char *xu_pack_www_ptr(const char *rel, unsigned *len) {
  const unsigned char *p = 0;
  unsigned n = 0;
  if (!xu_pack_find_www(rel, &p, &n)) {
    if (len) *len = 0;
    return 0;
  }
  if (len) *len = n;
  return p;
}

const unsigned char *xu_pack_icon_ptr(unsigned *len) {
  const unsigned char *p = 0;
  unsigned n = 0;
  if (!xu_pack_icon(&p, &n)) {
    if (len) *len = 0;
    return 0;
  }
  if (len) *len = n;
  return p;
}

const unsigned char *xu_pack_path_ptr(const char *path, unsigned *len) {
  const unsigned char *p = 0;
  unsigned n = 0;
  if (!xu_pack_file_for_path(path, &p, &n)) {
    if (len) *len = 0;
    return 0;
  }
  if (len) *len = n;
  return p;
}
