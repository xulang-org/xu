#include "xu_ui_screens.h"
static bool desktop_screens(const char *command,unsigned id,unsigned generation,HWND window){
 uint64_t request=0;if(!xu_screen_take(command,id,generation,&request))return false;
 typedef HRESULT (WINAPI *MonitorDpi)(HMONITOR,int,UINT *,UINT *);
 HMODULE library=LoadLibraryW(L"shcore.dll");auto dpi=library?(MonitorDpi)GetProcAddress(library,"GetDpiForMonitor"):NULL;
 struct State{std::string out="XUS1\n";HMONITOR current=NULL;MonitorDpi dpi=NULL;unsigned count=0;bool failed=false;}state;state.current=MonitorFromWindow(window,MONITOR_DEFAULTTONEAREST);state.dpi=dpi;
 BOOL ok=EnumDisplayMonitors(NULL,NULL,+[](HMONITOR monitor,HDC,LPRECT,LPARAM context)->BOOL{auto &s=*(State *)context;
  if(++s.count>64){s.failed=true;return FALSE;}MONITORINFOEXW info={};info.cbSize=sizeof(info);if(!GetMonitorInfoW(monitor,&info)){s.failed=true;return FALSE;}
  UINT dx=96,dy=96;if(s.dpi && FAILED(s.dpi(monitor,0,&dx,&dy)))dx=dy=96;
  char name[128]={};WideCharToMultiByte(CP_UTF8,0,info.szDevice,-1,name,sizeof(name),NULL,NULL);
  auto r=info.rcMonitor,w=info.rcWork;unsigned flags=16|8|4|((info.dwFlags&MONITORINFOF_PRIMARY)?1:0)|(monitor==s.current?2:0);
  xu_screen_append(s.out,name,name,flags,r.left,r.top,r.right-r.left,r.bottom-r.top,w.left,w.top,w.right-w.left,w.bottom-w.top,dx/96.0,dy/96.0);return TRUE;
 },(LPARAM)&state);
 if(library)FreeLibrary(library);if(!ok||state.failed||!state.count)xu_ui_request_complete(request,XU_REQUEST_FAILED,"display list unavailable",24);
 else xu_ui_request_complete(request,XU_REQUEST_COMPLETED,state.out.data(),(unsigned)state.out.size());return true;
}
