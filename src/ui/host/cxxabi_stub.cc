// MinGW PE static link often leaves __cxa_pure_virtual undefined (call → NULL → AV).
#include <windows.h>
#include <stdlib.h>

extern "C" void __cxa_pure_virtual(void) {
  // Log only — MessageBox here made every bad COM call look like a "UI popup".
  OutputDebugStringA("Xu: C++ pure virtual call (link/ABI)\n");
  ExitProcess(199);
}
