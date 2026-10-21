// Weak empty defaults for unpackaged host links.
// MUST stay in a separate .c from xu_pack_assets.c — if weak count==0 lives in
// the same TU as xu_pack_has_www / find_www, GCC constant-folds them to "always
// empty" and the strong www blob from the pack is ignored at runtime.
#include "xu_pack_assets.h"

// Some oneexe builds use CXX for .c inputs as well. GCC requires explicit
// external storage on weak const definitions in that mode.
#ifdef __cplusplus
extern "C" {
#define XU_PACK_WEAK_DEFAULT extern __attribute__((weak))
#else
#define XU_PACK_WEAK_DEFAULT __attribute__((weak))
#endif

XU_PACK_WEAK_DEFAULT const XuWwwFile xu_pack_www_files[] = {{0, 0, 0}};
XU_PACK_WEAK_DEFAULT const unsigned xu_pack_www_files_count = 0;
XU_PACK_WEAK_DEFAULT const unsigned char xu_pack_icon_png[] = {0};
XU_PACK_WEAK_DEFAULT const unsigned int xu_pack_icon_png_len = 0;
XU_PACK_WEAK_DEFAULT const unsigned char xu_pack_icon_ico[] = {0};
XU_PACK_WEAK_DEFAULT const unsigned int xu_pack_icon_ico_len = 0;
XU_PACK_WEAK_DEFAULT const unsigned char xu_pack_webview2_loader[] = {0};
XU_PACK_WEAK_DEFAULT const unsigned int xu_pack_webview2_loader_len = 0;

#undef XU_PACK_WEAK_DEFAULT
#ifdef __cplusplus
}
#endif
