// Same-process command consumption shared by the native desktop shells.
#pragma once
#include "xu_ui_mem.h"
#include <stdio.h>
#include <stdlib.h>
#include <string>

static inline std::string xu_ui_take_commands(const char *tmp) {
  unsigned len = 0;
  char *body = xu_ui_mem_take("xu_ui_cmd.txt", &len);
  if (body) {
    std::string result(body, len);
    free(body);
    return result;
  }
  // Explicit file mode is a development compatibility path. Read the complete
  // bounded file before clearing it; the production mailbox above is atomic.
  if (!tmp || !tmp[0] || std::string(tmp) == ":xu:" || std::string(tmp) == ":mem:") return {};
  std::string path = std::string(tmp) + "/xu_ui_cmd.txt";
  FILE *f = fopen(path.c_str(), "rb");
  if (!f) return {};
  std::string result;
  char chunk[8192];
  size_t n;
  while ((n = fread(chunk, 1, sizeof(chunk), f)) != 0) {
    if (n > XU_UI_MEM_MAX_PAYLOAD - result.size()) {
      fclose(f);
      return {}; // Leave an oversized/incomplete file intact.
    }
    result.append(chunk, n);
  }
  bool ok = !ferror(f);
  fclose(f);
  if (!ok) return {};
  f = fopen(path.c_str(), "wb");
  if (!f) return {};
  fclose(f);
  return result;
}

#include "xu_ui_windows.h"
#include "xu_ui_requests.h"
/* Decode only canonical nonzero decimal identities. command points inside raw. */
static inline bool xu_ui_scoped_command(const char *raw,unsigned *identity,const char **command) {
  if(!raw || strncmp(raw,"window\t",7))return false;
  const char *first=strchr(raw+7,'\t');if(!first)return false;
  const char *second=strchr(first+1,'\t');if(!second || !second[1])return false;
  std::string a(raw+7,first-(raw+7)),b(first+1,second-first-1);uint64_t id=0,gen=0;
  if(!xu_request_id(a.c_str(),&id) || !xu_request_id(b.c_str(),&gen) || id>0x7fffffffu || gen>UINT32_MAX)return false;
  identity[0]=(unsigned)id;identity[1]=(unsigned)gen;*command=second+1;return true;
}
