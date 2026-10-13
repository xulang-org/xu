// In-memory pack blobs (www + brand icon). Provided by pack *_blob.o when
// oneexe-linked; weak defaults here so unpackaged host links still work.
// Hosts serve xu:// from these bytes — never extract www/icon to TEMP.
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

typedef struct XuWwwFile {
  const char *path;
  const unsigned char *data;
  unsigned len;
} XuWwwFile;

/* Strong in pack blob .o; weak empties in xu_pack_assets_weak.c (separate TU). */
extern const XuWwwFile xu_pack_www_files[];
extern const unsigned xu_pack_www_files_count;
extern const unsigned char xu_pack_icon_png[];
extern const unsigned int xu_pack_icon_png_len;
/* Windows tray prefers a real .ico blob (optional; pack embeds when available). */
extern const unsigned char xu_pack_icon_ico[];
extern const unsigned int xu_pack_icon_ico_len;

typedef struct XuPackSlice {
  const unsigned char *data;
  unsigned len;
} XuPackSlice;

int xu_pack_has_www(void);
int xu_pack_has_icon(void);
/* rel: "index.html", "/app.css", "brand/xu_classic.svg", "brand/xu_app_logo.png". 1 = found. */
int xu_pack_find_www(const char *rel, const unsigned char **data, unsigned *len);
int xu_pack_icon(const unsigned char **data, unsigned *len);
int xu_pack_get_icon_ico(const unsigned char **data, unsigned *len);
/* Disk path or xu:// route → packed bytes (icon or www). */
int xu_pack_file_for_path(const char *path, const unsigned char **data, unsigned *len);
XuPackSlice xu_pack_www_slice(const char *rel);
XuPackSlice xu_pack_icon_slice(void);
XuPackSlice xu_pack_path_slice(const char *path);
/* Pointer + length; easier FFI than returning a struct. */
const unsigned char *xu_pack_www_ptr(const char *rel, unsigned *len);
const unsigned char *xu_pack_icon_ptr(unsigned *len);
const unsigned char *xu_pack_path_ptr(const char *path, unsigned *len);

#ifdef __cplusplus
}
#endif
