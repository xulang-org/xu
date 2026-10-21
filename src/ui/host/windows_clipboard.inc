// System clipboard calls can wait for a delayed external renderer. A single
// bounded worker serializes them without retaining a shell/window/plugin pointer.
#include <deque>
static void desktop_clipboard_perform(uint64_t id,unsigned kind,const std::string &text,HWND owner) {
  if(!xu_ui_request_alive(id))return;
  unsigned status=XU_REQUEST_FAILED; std::string result;
  if(!OpenClipboard(owner)) { xu_ui_request_complete(id,status,"clipboard busy",14); return; }
  struct Close { bool open=true;void release(){if(open){CloseClipboard();open=false;}}~Close(){release();} } close;
  if(kind==XU_REQUEST_CLIPBOARD_WRITE) {
    int count=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text.data(),(int)text.size(),NULL,0);
    // Empty text still owns one terminating UTF-16 code unit.
    if(count || text.empty()) {
      HGLOBAL memory=GlobalAlloc(GMEM_MOVEABLE,((size_t)count+1)*sizeof(wchar_t));
      if(memory) {
        auto *out=(wchar_t *)GlobalLock(memory);
        if(out) {
          bool valid=!count || MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text.data(),(int)text.size(),out,count)==count;
          out[count]=0;GlobalUnlock(memory);
          if(valid && xu_ui_request_alive(id) && EmptyClipboard() && SetClipboardData(CF_UNICODETEXT,memory)) { memory=NULL;status=XU_REQUEST_COMPLETED; }
        }
        if(memory)GlobalFree(memory);
      }
    }
  } else if(!IsClipboardFormatAvailable(CF_UNICODETEXT))status=XU_REQUEST_COMPLETED;
  else {
    HGLOBAL memory=GetClipboardData(CF_UNICODETEXT);
    SIZE_T bytes=memory?GlobalSize(memory):0;
    // Bound external storage before scanning or converting it. At most 65536
    // UTF-16 units can possibly produce an accepted UTF-8 result.
    if(bytes && bytes<=((size_t)XU_UI_REQUEST_MAX_TEXT+1)*sizeof(wchar_t) && !(bytes%sizeof(wchar_t))) {
      auto *data=(const wchar_t *)GlobalLock(memory);
      if(data) {
        size_t count=0,capacity=bytes/sizeof(wchar_t);while(count<capacity && data[count])++count;
        if(count<capacity) {
          int n=count?WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,data,(int)count,NULL,0,NULL,NULL):0;
          if((!count || n>0) && n<=(int)XU_UI_REQUEST_MAX_TEXT) {
            result.resize(n);
            if(!n || WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,data,(int)count,result.data(),n,NULL,NULL)==n)status=XU_REQUEST_COMPLETED;
          }
        }
        GlobalUnlock(memory);
      }
    }
  }
  close.release();xu_ui_request_complete(id,status,result.data(),(unsigned)result.size());return;
}

struct XuClipboardJob { uint64_t id;unsigned kind;std::string text; };
struct XuClipboardQueue {
  SRWLOCK lock=SRWLOCK_INIT;
  std::deque<XuClipboardJob> jobs;
  bool running=false;
};
static XuClipboardQueue &clipboard_queue() {
  // Process-lifetime scheduler, also valid if a host returns while an OS call is
  // still blocked. No static destructor races a late callback during CRT exit.
  static auto *queue=new XuClipboardQueue;return *queue;
}
static DWORD WINAPI clipboard_worker(void *) {
  auto &queue=clipboard_queue();
  HWND owner=CreateWindowExW(0,L"STATIC",L"Xu clipboard",0,0,0,0,0,HWND_MESSAGE,NULL,GetModuleHandleW(NULL),NULL);
  for(;;) {
    AcquireSRWLockExclusive(&queue.lock);
    if(queue.jobs.empty()) {
      // No toolkit/OS call may run under the admission lock used by the UI.
      ReleaseSRWLockExclusive(&queue.lock);
      if(owner)DestroyWindow(owner);
      AcquireSRWLockExclusive(&queue.lock);
      if(queue.jobs.empty()){queue.running=false;ReleaseSRWLockExclusive(&queue.lock);return 0;}
      ReleaseSRWLockExclusive(&queue.lock);
      owner=CreateWindowExW(0,L"STATIC",L"Xu clipboard",0,0,0,0,0,HWND_MESSAGE,NULL,GetModuleHandleW(NULL),NULL);
      continue;
    }
    auto job=std::move(queue.jobs.front());queue.jobs.pop_front();ReleaseSRWLockExclusive(&queue.lock);
    try {
      if(owner)desktop_clipboard_perform(job.id,job.kind,job.text,owner);
      else xu_ui_request_complete(job.id,XU_REQUEST_FAILED,"",0);
    } catch(...) { xu_ui_request_complete(job.id,XU_REQUEST_FAILED,"",0); }
  }
}
static bool desktop_clipboard(const char *command,unsigned canvas,unsigned generation) {
  uint64_t id=0;unsigned kind=0;std::string text;
  if(!xu_request_clipboard_take(command,canvas,generation,&id,&kind,&text))return false;
  if(!kind || !xu_ui_request_alive(id))return true;
  auto &queue=clipboard_queue();bool accepted=false;
  AcquireSRWLockExclusive(&queue.lock);
  if(queue.jobs.size()<XU_UI_REQUEST_MAX_PENDING) {
    try { queue.jobs.push_back({id,kind,std::move(text)});accepted=true; } catch(...) {}
    if(accepted && !queue.running) {
      HANDLE thread=CreateThread(NULL,0,clipboard_worker,NULL,0,NULL);
      if(thread){queue.running=true;CloseHandle(thread);}
      else {queue.jobs.pop_back();accepted=false;}
    }
  }
  ReleaseSRWLockExclusive(&queue.lock);
  if(!accepted)xu_ui_request_complete(id,XU_REQUEST_FAILED,"clipboard worker capacity",25);
  return true;
}
static bool desktop_clipboard_idle() {
  auto &queue=clipboard_queue();AcquireSRWLockShared(&queue.lock);
  bool idle=!queue.running && queue.jobs.empty();ReleaseSRWLockShared(&queue.lock);return idle;
}
