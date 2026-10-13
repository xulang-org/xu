// Force MinGW libstdc++ std::string COMDAT into the PE.
// Without this, some packs leave _M_constructILb1EE as an abs-0 symbol and
// the first std::string use jumps to NULL (VEH 0xC0000005 at 0x0).
#include <string>

extern "C" void xu_force_cxx_string_syms(void) {
  std::string a("xu");
  std::string b(a);
  std::string c(a, 0, a.size());
  std::wstring w(L"xu");
  std::wstring w2(w);
  volatile size_t n = a.size() + b.size() + c.size() + w.size() + w2.size();
  (void)n;
}
