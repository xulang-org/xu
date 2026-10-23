#include "xu_ui_files.h"
#include <memory>
#include <unordered_map>
#if GTK_CHECK_VERSION(4, 10, 0)
struct XuGtkFileRequest {
  uint64_t id;unsigned kind;bool multiple;
  GtkFileDialog *dialog=gtk_file_dialog_new();
  GCancellable *cancel=g_cancellable_new();
  ~XuGtkFileRequest(){g_object_unref(dialog);g_object_unref(cancel);}
};
using XuGtkFileRef=std::shared_ptr<XuGtkFileRequest>;
static std::unordered_map<uint64_t,XuGtkFileRef> g_file_requests;
static bool desktop_files_idle(){return g_file_requests.empty();}
static void desktop_files_poll(){
  xu_ui_request_poll();std::vector<XuGtkFileRef> pending;
  for(auto &entry:g_file_requests)pending.push_back(entry.second);
  for(auto &op:pending)if(!xu_ui_request_alive(op->id))g_cancellable_cancel(op->cancel);
}
static void desktop_file_done(GObject *,GAsyncResult *result,gpointer data){
  std::unique_ptr<XuGtkFileRef> holder((XuGtkFileRef *)data);auto op=*holder;
  GError *error=NULL;GFile *file=NULL;GListModel *files=NULL;
  if(op->kind==XU_REQUEST_SAVE_FILE)file=gtk_file_dialog_save_finish(op->dialog,result,&error);
  else if(op->kind==XU_REQUEST_SELECT_FOLDERS){
    if(op->multiple)files=gtk_file_dialog_select_multiple_folders_finish(op->dialog,result,&error);
    else file=gtk_file_dialog_select_folder_finish(op->dialog,result,&error);
  }else if(op->multiple)files=gtk_file_dialog_open_multiple_finish(op->dialog,result,&error);
  else file=gtk_file_dialog_open_finish(op->dialog,result,&error);
  unsigned status=XU_REQUEST_FAILED;std::string value;std::vector<std::string> paths;
  if(file || files){
    unsigned count=files?g_list_model_get_n_items(files):1;bool valid=count && count<=XU_UI_FILE_MAX_PATHS;
    for(unsigned i=0;valid && i<count;++i){
      auto *item=files?G_FILE(g_list_model_get_item(files,i)):G_FILE(g_object_ref(file));
      char *path=item?g_file_get_path(item):NULL;
      if(path)paths.emplace_back(path);else valid=false;
      g_free(path);if(item)g_object_unref(item);
    }
    if(valid && xu_file_result(paths,&value))status=XU_REQUEST_COMPLETED;
  }else if(error && (g_error_matches(error,G_IO_ERROR,G_IO_ERROR_CANCELLED) ||
    g_error_matches(error,GTK_DIALOG_ERROR,GTK_DIALOG_ERROR_DISMISSED) || g_error_matches(error,GTK_DIALOG_ERROR,GTK_DIALOG_ERROR_CANCELLED)))status=XU_REQUEST_CANCELLED;
  if(error)g_error_free(error);if(file)g_object_unref(file);if(files)g_object_unref(files);
  g_file_requests.erase(op->id);xu_ui_request_complete(op->id,status,value.data(),value.size());
}
static bool desktop_files(const char *command,unsigned canvas,unsigned generation,GtkWindow *parent){
  uint64_t id=0;unsigned kind=0;XuUiFileOptions options;
  if(!xu_file_take(command,canvas,generation,&id,&kind,&options))return false;
  if(!kind || !xu_ui_request_alive(id))return true;
  if(g_file_requests.size()>=XU_UI_FILE_MAX_ACTIVE || (!options.directory.empty() && !g_path_is_absolute(options.directory.c_str()))){xu_ui_request_complete(id,XU_REQUEST_FAILED,"",0);return true;}
  auto op=std::make_shared<XuGtkFileRequest>();op->id=id;op->kind=kind;op->multiple=options.multiple;
  if(!options.title.empty())gtk_file_dialog_set_title(op->dialog,options.title.c_str());
  gtk_file_dialog_set_modal(op->dialog,TRUE);
  if(!options.directory.empty()){GFile *folder=g_file_new_for_path(options.directory.c_str());gtk_file_dialog_set_initial_folder(op->dialog,folder);g_object_unref(folder);}
  if(!options.name.empty())gtk_file_dialog_set_initial_name(op->dialog,options.name.c_str());
  if(!options.filters.empty()){
    GListStore *filters=g_list_store_new(GTK_TYPE_FILE_FILTER);
    for(auto &entry:options.filters){
      GtkFileFilter *filter=gtk_file_filter_new();gtk_file_filter_set_name(filter,entry.label.c_str());
      for(auto &extension:entry.extensions){auto pattern=extension=="*"?"*":"*."+extension;gtk_file_filter_add_pattern(filter,pattern.c_str());}
      g_list_store_append(filters,filter);if(!gtk_file_dialog_get_default_filter(op->dialog))gtk_file_dialog_set_default_filter(op->dialog,filter);g_object_unref(filter);
    }
    gtk_file_dialog_set_filters(op->dialog,G_LIST_MODEL(filters));g_object_unref(filters);
  }
  g_file_requests.emplace(id,op);auto *holder=new XuGtkFileRef(op);
  if(kind==XU_REQUEST_SAVE_FILE)gtk_file_dialog_save(op->dialog,parent,op->cancel,desktop_file_done,holder);
  else if(kind==XU_REQUEST_SELECT_FOLDERS){
    if(options.multiple)gtk_file_dialog_select_multiple_folders(op->dialog,parent,op->cancel,desktop_file_done,holder);
    else gtk_file_dialog_select_folder(op->dialog,parent,op->cancel,desktop_file_done,holder);
  }else if(options.multiple)gtk_file_dialog_open_multiple(op->dialog,parent,op->cancel,desktop_file_done,holder);
  else gtk_file_dialog_open(op->dialog,parent,op->cancel,desktop_file_done,holder);
  return true;
}
#else
static bool desktop_files_idle(){return true;}
static void desktop_files_poll(){xu_ui_request_poll();}
static bool desktop_files(const char *command,unsigned canvas,unsigned generation,GtkWindow *){
  uint64_t id=0;unsigned kind=0;XuUiFileOptions options;
  if(!xu_file_take(command,canvas,generation,&id,&kind,&options))return false;
  if(kind)xu_ui_request_complete(id,XU_REQUEST_UNSUPPORTED,"",0);
  return true;
}
#endif
