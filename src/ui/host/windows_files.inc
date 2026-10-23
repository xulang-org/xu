// One STA per active dialog (globally bounded to eight). UI-owned HWND leases
// defer parent destruction until that STA exits; no content/arena pointer crosses.
#include "xu_ui_files.h"
#include <memory>
#include <unordered_map>
struct XuWinFileRequest {
  uint64_t id;unsigned window,canvas,generation,kind;HWND owner;
  HANDLE thread=NULL;DWORD thread_id=0;
  XuUiFileOptions options;
  std::vector<std::wstring> labels,specs;
  std::vector<COMDLG_FILTERSPEC> filters;
  ~XuWinFileRequest(){if(thread)CloseHandle(thread);}
};
using XuWinFileRef=std::shared_ptr<XuWinFileRequest>;
static std::unordered_map<uint64_t,XuWinFileRef> g_file_requests;
static bool xu_file_wide(const std::string &text,std::wstring *out){
  if(text.empty()){out->clear();return true;}
  int count=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text.data(),text.size(),NULL,0);
  if(count<=0)return false;out->resize(count);
  return MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text.data(),text.size(),out->data(),count)==count;
}
static bool desktop_file_configure(const XuWinFileRef &op,IFileDialog *dialog){
  auto &options=op->options;DWORD flags=0;
  if(FAILED(dialog->GetOptions(&flags)))return false;
  flags&=~(FOS_PICKFOLDERS|FOS_ALLOWMULTISELECT);
  flags|=FOS_FORCEFILESYSTEM|FOS_PATHMUSTEXIST|FOS_NOCHANGEDIR;
  if(op->kind==XU_REQUEST_SAVE_FILE)flags|=FOS_OVERWRITEPROMPT;
  else {flags|=FOS_FILEMUSTEXIST;if(options.multiple)flags|=FOS_ALLOWMULTISELECT;if(op->kind==XU_REQUEST_SELECT_FOLDERS)flags|=FOS_PICKFOLDERS;}
  if(FAILED(dialog->SetOptions(flags)))return false;
  std::wstring text;
  if(!options.title.empty() && (!xu_file_wide(options.title,&text) || FAILED(dialog->SetTitle(text.c_str()))))return false;
  if(!options.name.empty() && (!xu_file_wide(options.name,&text) || FAILED(dialog->SetFileName(text.c_str()))))return false;
  if(!options.directory.empty()){
    if(!xu_file_wide(options.directory,&text) || PathIsRelativeW(text.c_str()))return false;
    IShellItem *folder=NULL;HRESULT hr=SHCreateItemFromParsingName(text.c_str(),NULL,IID_PPV_ARGS(&folder));
    if(FAILED(hr))return false;hr=dialog->SetFolder(folder);folder->Release();if(FAILED(hr))return false;
  }
  for(auto &filter:options.filters){
    std::wstring label,pattern;
    if(!xu_file_wide(filter.label,&label))return false;
    for(auto &extension:filter.extensions){std::wstring ext;if(!xu_file_wide(extension,&ext))return false;if(!pattern.empty())pattern+=L';';pattern+=extension=="*"?L"*.*":L"*."+ext;}
    op->labels.push_back(std::move(label));op->specs.push_back(std::move(pattern));
  }
  for(unsigned i=0;i<op->labels.size();++i)op->filters.push_back({op->labels[i].c_str(),op->specs[i].c_str()});
  if(!op->filters.empty() && (FAILED(dialog->SetFileTypes(op->filters.size(),op->filters.data())) || FAILED(dialog->SetFileTypeIndex(1))))return false;
  return true;
}
static bool desktop_file_path(IShellItem *item,std::vector<std::string> *paths){
  if(!item)return false;PWSTR value=NULL;HRESULT hr=item->GetDisplayName(SIGDN_FILESYSPATH,&value);
  if(FAILED(hr) || !value)return false;
  size_t length=0;while(length<=32768 && value[length])++length;
  int count=length && length<=32768?WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,value,length,NULL,0,NULL,NULL):0;
  bool valid=count>0 && count<=(int)XU_UI_REQUEST_MAX_TEXT/2;
  if(valid){std::string path(count,'\0');valid=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,value,length,path.data(),count,NULL,NULL)==count;if(valid)paths->push_back(std::move(path));}
  CoTaskMemFree(value);return valid;
}
struct XuWinFilePoll { uint64_t id;IFileDialog *dialog; };
static VOID CALLBACK desktop_file_cancel_timer(HWND window,UINT,UINT_PTR,DWORD){
  auto *state=(XuWinFilePoll *)GetWindowLongPtrW(window,GWLP_USERDATA);
  if(state && !xu_ui_request_alive(state->id))state->dialog->Close(HRESULT_FROM_WIN32(ERROR_CANCELLED));
}
static DWORD WINAPI desktop_file_worker(void *data){
  std::unique_ptr<XuWinFileRef> holder((XuWinFileRef *)data);auto op=*holder;
  unsigned status=XU_REQUEST_FAILED;std::string value;IFileDialog *dialog=NULL;HWND monitor=NULL;bool com=false;
  try {
    HRESULT hr=CoInitializeEx(NULL,COINIT_APARTMENTTHREADED|COINIT_DISABLE_OLE1DDE);com=SUCCEEDED(hr);
    if(com && xu_ui_request_alive(op->id))hr=CoCreateInstance(op->kind==XU_REQUEST_SAVE_FILE?CLSID_FileSaveDialog:CLSID_FileOpenDialog,NULL,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&dialog));
    if(com && dialog && desktop_file_configure(op,dialog) && xu_ui_request_alive(op->id)){
      monitor=CreateWindowExW(0,L"STATIC",L"Xu file request",0,0,0,0,0,HWND_MESSAGE,NULL,GetModuleHandleW(NULL),NULL);
      XuWinFilePoll state={op->id,dialog};
      if(monitor)SetWindowLongPtrW(monitor,GWLP_USERDATA,(LONG_PTR)&state);
      if(monitor && SetTimer(monitor,1,50,desktop_file_cancel_timer)){
        if(xu_ui_request_alive(op->id))hr=dialog->Show(op->owner);else hr=HRESULT_FROM_WIN32(ERROR_CANCELLED);
        KillTimer(monitor,1);SetWindowLongPtrW(monitor,GWLP_USERDATA,0);
        if(hr==HRESULT_FROM_WIN32(ERROR_CANCELLED))status=XU_REQUEST_CANCELLED;
        else if(SUCCEEDED(hr) && xu_ui_request_alive(op->id)){
          std::vector<std::string> paths;bool valid=false;
          if(op->kind==XU_REQUEST_SAVE_FILE){IShellItem *item=NULL;if(SUCCEEDED(dialog->GetResult(&item))){valid=desktop_file_path(item,&paths);item->Release();}}
          else{
            IFileOpenDialog *open=NULL;IShellItemArray *items=NULL;
            if(SUCCEEDED(dialog->QueryInterface(IID_PPV_ARGS(&open)))){
              if(SUCCEEDED(open->GetResults(&items))){DWORD count=0;valid=SUCCEEDED(items->GetCount(&count)) && count && count<=XU_UI_FILE_MAX_PATHS;
                for(DWORD i=0;valid && i<count;++i){IShellItem *item=NULL;valid=SUCCEEDED(items->GetItemAt(i,&item)) && desktop_file_path(item,&paths);if(item)item->Release();}items->Release();}open->Release();
            }
          }
          if(valid && xu_file_result(paths,&value))status=XU_REQUEST_COMPLETED;
        }
      }
    }else if(hr==REGDB_E_CLASSNOTREG || hr==E_NOTIMPL)status=XU_REQUEST_UNSUPPORTED;
  }catch(...){status=XU_REQUEST_FAILED;value.clear();}
  if(monitor){KillTimer(monitor,1);SetWindowLongPtrW(monitor,GWLP_USERDATA,0);DestroyWindow(monitor);}
  if(dialog)dialog->Release();if(com)CoUninitialize();
  xu_ui_request_complete(op->id,status,value.data(),value.size());return 0;
}
static void desktop_files_poll(){
  xu_ui_request_poll();std::vector<XuWinFileRef> pending;for(auto &entry:g_file_requests)pending.push_back(entry.second);
  for(auto &op:pending){
    if(op->thread){if(WaitForSingleObject(op->thread,0)==WAIT_OBJECT_0)g_file_requests.erase(op->id);}
    else if(!xu_ui_request_alive(op->id))g_file_requests.erase(op->id);
  }
  pending.clear();for(auto &entry:g_file_requests)if(!entry.second->thread)pending.push_back(entry.second);
  for(auto &op:pending){
    bool busy=false;for(auto &entry:g_file_requests)if(entry.first!=op->id && entry.second->window==op->window && entry.second->thread)busy=true;
    if(busy)continue;
    unsigned meta[6];
    if(!IsWindow(op->owner) || GetWindowThreadProcessId(op->owner,NULL)!=GetCurrentThreadId() || !xu_ui_window_info(op->window,op->generation,meta,NULL,0)){
      g_file_requests.erase(op->id);xu_ui_request_complete(op->id,XU_REQUEST_CANCELLED,"",0);continue;
    }
    auto *holder=new XuWinFileRef(op);op->thread=CreateThread(NULL,0,desktop_file_worker,holder,0,&op->thread_id);
    if(!op->thread){delete holder;g_file_requests.erase(op->id);xu_ui_request_complete(op->id,XU_REQUEST_FAILED,"",0);}
  }
}
static bool desktop_files_owner_idle(unsigned window,unsigned generation){
  for(auto &entry:g_file_requests)if(entry.second->window==window && entry.second->generation==generation)return false;return true;
}
static bool desktop_files_idle(){return g_file_requests.empty();}
static void desktop_files_close_owner(unsigned window,unsigned generation){
  std::vector<uint64_t> ids;for(auto &entry:g_file_requests)if(entry.second->window==window && entry.second->generation==generation)ids.push_back(entry.first);
  for(auto id:ids)xu_ui_request_cancel(id);desktop_files_poll();
}
static bool desktop_files(const char *command,unsigned canvas,unsigned generation,HWND parent){
  uint64_t id=0;unsigned kind=0;XuUiFileOptions options;
  if(!xu_file_take(command,canvas,generation,&id,&kind,&options))return false;
  if(!kind || !xu_ui_request_alive(id))return true;
  if(g_file_requests.size()>=XU_UI_FILE_MAX_ACTIVE){xu_ui_request_complete(id,XU_REQUEST_FAILED,"",0);return true;}
  auto op=std::make_shared<XuWinFileRequest>();op->id=id;op->window=canvas;op->canvas=canvas;op->generation=generation;op->kind=kind;op->owner=parent;op->options=std::move(options);
  g_file_requests.emplace(id,op);desktop_files_poll();return true;
}
