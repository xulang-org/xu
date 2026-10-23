#include "xu_ui_screens.h"
static bool desktop_screens(const char *command,unsigned id,unsigned generation,GtkWindow *window){
 uint64_t request=0;if(!xu_screen_take(command,id,generation,&request))return false;
 GdkDisplay *display=gtk_widget_get_display(GTK_WIDGET(window));GListModel *monitors=display?gdk_display_get_monitors(display):NULL;
 auto *surface=gtk_native_get_surface(GTK_NATIVE(window));auto *current=surface?gdk_display_get_monitor_at_surface(display,surface):NULL;
 unsigned count=monitors?g_list_model_get_n_items(monitors):0;std::string out="XUS1\n";
 if(!count||count>64){xu_ui_request_complete(request,XU_REQUEST_FAILED,"display list unavailable",24);return true;}
 for(unsigned i=0;i<count;++i){auto *monitor=GDK_MONITOR(g_list_model_get_item(monitors,i));GdkRectangle bounds;gdk_monitor_get_geometry(monitor,&bounds);
  const char *connector=gdk_monitor_get_connector(monitor),*model=gdk_monitor_get_model(monitor);std::string identity=std::to_string(i)+":"+(connector?connector:"");
  double scale=gdk_monitor_get_scale_factor(monitor);
  // GTK4/Wayland does not expose a portable work area or primary designation.
  xu_screen_append(out,identity,model?model:"Display",monitor==current?2:0,bounds.x,bounds.y,bounds.width,bounds.height,bounds.x,bounds.y,bounds.width,bounds.height,scale,scale);g_object_unref(monitor);
 }
 xu_ui_request_complete(request,XU_REQUEST_COMPLETED,out.data(),(unsigned)out.size());return true;
}
