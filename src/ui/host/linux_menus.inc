#include "xu_ui_menu.h"
#include <map>
#include <memory>
struct XuGtkMenu {GtkWindow *window=NULL;GtkWidget *bar=NULL;GtkEventController *shortcuts=NULL;GSimpleActionGroup *group=NULL;unsigned id=0,generation=0;std::string wire;std::vector<XuMenuEntry> entries;};
static std::map<GtkWindow *,std::unique_ptr<XuGtkMenu>> g_structured_menus;
static void native_menu_close(GtkWindow *window){auto it=g_structured_menus.find(window);if(it==g_structured_menus.end())return;auto &s=*it->second;
 if(s.bar)gtk_box_remove(GTK_BOX(gtk_widget_get_parent(s.bar)),s.bar);if(s.shortcuts)gtk_widget_remove_controller(GTK_WIDGET(window),s.shortcuts);
 gtk_widget_insert_action_group(GTK_WIDGET(window),"xum",NULL);if(s.group)g_object_unref(s.group);g_structured_menus.erase(it);}
static GMenu *native_menu_level(XuGtkMenu &s,int parent){GMenu *menu=g_menu_new(),*section=g_menu_new();
 for(size_t i=0;i<s.entries.size();++i){auto &e=s.entries[i];if(e.parent!=parent)continue;
  if(e.kind==3){if(g_menu_model_get_n_items(G_MENU_MODEL(section)))g_menu_append_section(menu,NULL,G_MENU_MODEL(section));g_object_unref(section);section=g_menu_new();}
  else if(e.kind==2){GMenu *child=native_menu_level(s,(int)i);auto *item=g_menu_item_new_submenu(e.label.c_str(),G_MENU_MODEL(child));std::string action="xum.a"+std::to_string(i);g_menu_item_set_detailed_action(item,action.c_str());g_menu_append_item(section,item);g_object_unref(item);g_object_unref(child);}
  else{std::string name="xum.a"+std::to_string(i);g_menu_append(section,e.label.c_str(),name.c_str());}
 }
 if(parent<0){ // GtkPopoverMenuBar requires submenus at its root, not sections.
  g_object_unref(menu);return section;
 }
 if(g_menu_model_get_n_items(G_MENU_MODEL(section)))g_menu_append_section(menu,NULL,G_MENU_MODEL(section));g_object_unref(section);return menu;
}
static bool native_menu_install(GtkWindow *window,GtkWidget *box,unsigned id,unsigned generation){
 auto body=xu_menu_read(id,generation);if(body.empty())return false;auto old=g_structured_menus.find(window);if(old!=g_structured_menus.end()&&old->second->wire==body)return true;
 std::vector<XuMenuEntry> entries;if(!xu_menu_parse(body,&entries))return false;if(entries.empty()){native_menu_close(window);gtk_application_window_set_show_menubar(GTK_APPLICATION_WINDOW(window),TRUE);return false;}
 auto state=std::unique_ptr<XuGtkMenu>(new XuGtkMenu());state->window=window;state->id=id;state->generation=generation;state->wire=body;state->entries=std::move(entries);
 state->group=g_simple_action_group_new();state->shortcuts=gtk_shortcut_controller_new();gtk_shortcut_controller_set_scope(GTK_SHORTCUT_CONTROLLER(state->shortcuts),GTK_SHORTCUT_SCOPE_MANAGED);
 for(size_t i=0;i<state->entries.size();++i){auto &e=state->entries[i];if(e.kind==3)continue;std::string name="a"+std::to_string(i);
  auto *action=g_simple_action_new_stateful(name.c_str(),NULL,g_variant_new_boolean((e.flags&2)!=0));
  if(e.kind!=4){g_object_unref(action);action=g_simple_action_new(name.c_str(),NULL);}g_simple_action_set_enabled(action,(e.flags&1)!=0);
  g_object_set_data(G_OBJECT(action),"xu-menu-index",GUINT_TO_POINTER((guint)i));
  g_signal_connect(action,"activate",G_CALLBACK(+[](GSimpleAction *action,GVariant *,gpointer data){auto &s=*(XuGtkMenu *)data;unsigned i=GPOINTER_TO_UINT(g_object_get_data(G_OBJECT(action),"xu-menu-index"));
   if(i<s.entries.size()&&(s.entries[i].kind==1||s.entries[i].kind==4)&&(s.entries[i].flags&1))xu_ui_window_event(s.id,s.generation,("menu_clicked\t"+s.entries[i].id).c_str());}),state.get());
  g_action_map_add_action(G_ACTION_MAP(state->group),G_ACTION(action));g_object_unref(action);
  if(e.key&&(e.flags&1)){int mods=e.mods;if(mods&16)mods=(mods&~16)|2;GdkModifierType mask=(GdkModifierType)(((mods&1)?GDK_SHIFT_MASK:0)|((mods&2)?GDK_CONTROL_MASK:0)|((mods&4)?GDK_ALT_MASK:0)|((mods&8)?GDK_SUPER_MASK:0));
   guint key=e.key>=288?GDK_KEY_F1+e.key-288:(guint)g_ascii_tolower(e.key);std::string detailed="xum."+name;
   auto *shortcut=gtk_shortcut_new(gtk_keyval_trigger_new(key,mask),gtk_named_action_new(detailed.c_str()));gtk_shortcut_controller_add_shortcut(GTK_SHORTCUT_CONTROLLER(state->shortcuts),shortcut);}
 }
 GMenu *model=native_menu_level(*state,-1);state->bar=gtk_popover_menu_bar_new_from_model(G_MENU_MODEL(model));g_object_unref(model);
 native_menu_close(window);gtk_widget_insert_action_group(GTK_WIDGET(window),"xum",G_ACTION_GROUP(state->group));gtk_widget_add_controller(GTK_WIDGET(window),state->shortcuts);
 gtk_box_prepend(GTK_BOX(box),state->bar);gtk_application_window_set_show_menubar(GTK_APPLICATION_WINDOW(window),FALSE);g_structured_menus[window]=std::move(state);return true;
}
