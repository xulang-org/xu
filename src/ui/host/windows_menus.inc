#include "xu_ui_menu.h"
#include <map>
#include <memory>
struct XuWinMenu {unsigned id=0,generation=0;HMENU menu=NULL;HACCEL accel=NULL;std::string wire;std::vector<XuMenuEntry> entries;};
static std::map<HWND,std::unique_ptr<XuWinMenu>> g_structured_menus;
static void native_menu_close(HWND window){auto it=g_structured_menus.find(window);if(it==g_structured_menus.end())return;
 if(IsWindow(window))SetMenu(window,NULL);if(it->second->menu)DestroyMenu(it->second->menu);if(it->second->accel)DestroyAcceleratorTable(it->second->accel);g_structured_menus.erase(it);}
static bool native_menu_present(HWND window){return g_structured_menus.find(window)!=g_structured_menus.end();}
static bool native_menu_command(HWND window,UINT command){auto it=g_structured_menus.find(window);if(it==g_structured_menus.end()||command<30000||command>=30256)return false;
 auto &state=*it->second;unsigned index=command-30000;if(index<state.entries.size()){auto &e=state.entries[index];if((e.kind==1||e.kind==4)&&(e.flags&1))xu_ui_window_event(state.id,state.generation,("menu_clicked\t"+e.id).c_str());}return true;}
static bool native_menu_install(HWND window,unsigned id,unsigned generation){
 auto body=xu_menu_read(id,generation);if(body.empty())return false;auto old=g_structured_menus.find(window);if(old!=g_structured_menus.end()&&old->second->wire==body)return true;
 std::vector<XuMenuEntry> entries;if(!xu_menu_parse(body,&entries))return false;
 if(entries.empty()){native_menu_close(window);if(id==1)g_menu_sig[0]=0;return false;}
 auto state=std::unique_ptr<XuWinMenu>(new XuWinMenu());state->id=id;state->generation=generation;state->entries=entries;state->wire=body;
 HMENU bar=CreateMenu();if(!bar)return false;std::vector<HMENU> menus(entries.size());std::vector<ACCEL> accelerators;
 for(size_t i=0;i<entries.size();++i){auto &e=entries[i];HMENU parent=e.parent<0?bar:menus[e.parent];
  if(!parent){DestroyMenu(bar);return false;}UINT flags=(e.flags&1)?MF_ENABLED:MF_GRAYED;if(e.flags&2)flags|=MF_CHECKED;
  wchar_t label[1200];utf8_to_wide(e.label.c_str(),label,1200);BOOL ok=FALSE;
  if(e.kind==2){menus[i]=CreatePopupMenu();if(menus[i])ok=AppendMenuW(parent,flags|MF_POPUP,(UINT_PTR)menus[i],label);}
  else if(e.kind==3)ok=AppendMenuW(parent,MF_SEPARATOR,0,NULL);
  else {ok=AppendMenuW(parent,flags|MF_STRING,30000+(UINT)i,label);
   if(e.key && (e.flags&1)){int mods=e.mods;if(mods&16)mods=(mods&~16)|2;BYTE f=FVIRTKEY;if(mods&1)f|=FSHIFT;if(mods&2)f|=FCONTROL;if(mods&4)f|=FALT;
    if(mods&8){DestroyMenu(bar);return false;}WORD key=(WORD)(e.key>=288?VK_F1+e.key-288:e.key>='a'&&e.key<='z'?e.key-32:e.key);accelerators.push_back(ACCEL{f,key,(WORD)(30000+i)});}
  }
  if(!ok){if(menus[i])DestroyMenu(menus[i]);DestroyMenu(bar);return false;}
 }
 state->menu=bar;if(!accelerators.empty())state->accel=CreateAcceleratorTableW(accelerators.data(),(int)accelerators.size());
 if(!accelerators.empty()&&!state->accel){DestroyMenu(bar);return false;}
 native_menu_close(window);SetMenu(window,bar);DrawMenuBar(window);g_structured_menus[window]=std::move(state);return true;
}
static bool native_menu_accel(MSG *message){HWND root=message->hwnd?GetAncestor(message->hwnd,GA_ROOT):NULL;auto it=g_structured_menus.find(root);
 return it!=g_structured_menus.end()&&it->second->accel&&TranslateAcceleratorW(root,it->second->accel,message);}
