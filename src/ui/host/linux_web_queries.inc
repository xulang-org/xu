struct XuNativeQuery {
 std::shared_ptr<XuPluginLife> life;uint64_t id;unsigned kind;GCancellable *cancel=g_cancellable_new();bool done=false;
 ~XuNativeQuery(){g_object_unref(cancel);}
};
static void native_queries_close(XuWebViewPlugin *p){for(auto &job:p->queries)g_cancellable_cancel(job->cancel);p->queries.clear();}
static void native_queries_poll(XuWebViewPlugin *p){for(auto it=p->queries.begin();it!=p->queries.end();){auto job=*it;if(!xu_ui_request_alive(job->id))g_cancellable_cancel(job->cancel);if(job->done)it=p->queries.erase(it);else ++it;}}
static void native_query_done(const std::shared_ptr<XuNativeQuery> &job,bool ok,const std::string &value){job->done=true;if(job->life->plugin)xu_web_native_complete(job->id,ok,value);}
static bool native_web_request(XuWebViewPlugin *p,const char *command){
 uint64_t id=0;unsigned kind=0;std::string value;if(!xu_web_native_take(command,p->host.canvas_id,p->host.canvas_generation,&id,&kind,&value))return false;if(!kind)return true;
 if(p->queries.size()>=XU_UI_REQUEST_MAX_PENDING){xu_web_native_complete(id,false,"native query capacity exceeded");return true;}
 if(!p->web){xu_web_native_complete(id,false,"WebView is not ready");return true;}
 auto job=std::make_shared<XuNativeQuery>();job->life=p->life;job->id=id;job->kind=kind;p->queries.push_back(job);auto *context=new std::shared_ptr<XuNativeQuery>(job);
 if(kind==8||kind==9){auto script=kind==9?"(function(){return window.find("+xu_web_json(value)+")?1:0;})()":value;
  webkit_web_view_evaluate_javascript(p->web,script.c_str(),-1,NULL,NULL,job->cancel,+[](GObject *source,GAsyncResult *result,gpointer data){auto job=*(std::shared_ptr<XuNativeQuery> *)data;delete (std::shared_ptr<XuNativeQuery> *)data;
   GError *error=NULL;auto *value=webkit_web_view_evaluate_javascript_finish(WEBKIT_WEB_VIEW(source),result,&error);std::string text;
   if(value){GBytes *bytes=jsc_value_to_string_as_bytes(value);gsize size=0;auto *raw=(const char *)g_bytes_get_data(bytes,&size);text.assign(raw,size);g_bytes_unref(bytes);g_object_unref(value);}
   if(error){text=error->message;g_error_free(error);native_query_done(job,false,text);}else native_query_done(job,true,text);
  },context);return true;
 }
 auto *session=webkit_web_view_get_network_session(p->web);auto *cookies=webkit_network_session_get_cookie_manager(session);
 if(kind==10){webkit_cookie_manager_get_all_cookies(cookies,job->cancel,+[](GObject *source,GAsyncResult *result,gpointer data){auto job=*(std::shared_ptr<XuNativeQuery> *)data;delete (std::shared_ptr<XuNativeQuery> *)data;
  GError *error=NULL;GList *list=webkit_cookie_manager_get_all_cookies_finish(WEBKIT_COOKIE_MANAGER(source),result,&error);std::string out;
  for(GList *at=list;at;at=at->next){auto *cookie=(SoupCookie *)at->data;if(!out.empty())out+='\n';out+=std::string(soup_cookie_get_name(cookie))+"="+soup_cookie_get_value(cookie)+";domain="+soup_cookie_get_domain(cookie)+";path="+soup_cookie_get_path(cookie);if(out.size()>65536)break;}
  g_list_free_full(list,(GDestroyNotify)soup_cookie_free);bool ok=error==NULL;if(error){out=error->message;g_error_free(error);}native_query_done(job,ok,out);
 },context);return true;}
 if(kind==12){auto *manager=webkit_network_session_get_website_data_manager(session);webkit_website_data_manager_clear(manager,WEBKIT_WEBSITE_DATA_COOKIES,0,job->cancel,+[](GObject *source,GAsyncResult *result,gpointer data){auto job=*(std::shared_ptr<XuNativeQuery> *)data;delete (std::shared_ptr<XuNativeQuery> *)data;
  GError *error=NULL;bool ok=webkit_website_data_manager_clear_finish(WEBKIT_WEBSITE_DATA_MANAGER(source),result,&error);std::string text=error?error->message:"";if(error)g_error_free(error);native_query_done(job,ok,text);
 },context);return true;}
 std::string name,text,domain;if(!xu_web_cookie_fields(value,&name,&text,&domain)){delete context;native_query_done(job,false,"invalid cookie fields");return true;}
 auto *cookie=soup_cookie_new(name.c_str(),text.c_str(),domain.c_str(),"/",-1);if(!cookie){delete context;native_query_done(job,false,"invalid cookie fields");return true;}
 webkit_cookie_manager_add_cookie(cookies,cookie,job->cancel,+[](GObject *source,GAsyncResult *result,gpointer data){auto job=*(std::shared_ptr<XuNativeQuery> *)data;delete (std::shared_ptr<XuNativeQuery> *)data;
  GError *error=NULL;bool ok=webkit_cookie_manager_add_cookie_finish(WEBKIT_COOKIE_MANAGER(source),result,&error);std::string text=error?error->message:"";if(error)g_error_free(error);native_query_done(job,ok,text);
 },context);soup_cookie_free(cookie);return true;
}
