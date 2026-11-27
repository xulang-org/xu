/* Resource transport only. Application decoding and gameplay remain in Xu. */
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
static bool resource_name(const char *path) {
    size_t n=strlen(path), segment=0;
    if (!n || n>240) return false;
    for (size_t i=0;i<=n;++i) {
        unsigned char c=(unsigned char)path[i];
        if (!c || c=='/') {
            size_t start=i-segment;
            if (!segment || (segment==1 && path[start]=='.') ||
                (segment==2 && path[start]=='.' && path[start+1]=='.')) return false;
            segment=0;
        } else {
            if (!((c>='A' && c<='Z') || (c>='a' && c<='z') || (c>='0' && c<='9') || c=='.' || c=='_' || c=='-')) return false;
            ++segment;
        }
    }
    return true;
}
static bool prepare_resources(void) {
    char *data_root=SDL_GetPrefPath("xulang", "@BUNDLE_ID@");
    if (!data_root) return false;
    bool data_ok=setenv("XU_PHONE_DATA_ROOT",data_root,1)==0;
    SDL_free(data_root);
    if (!data_ok) return false;
#ifdef __ANDROID__
    char *root=SDL_GetPrefPath("xulang", "phone-game-resources");
    if (!root) return false;
    size_t length=0, total=0;
    char *index=SDL_LoadFile("resources/resources.index", &length);
    if (!index || length>65536 || memchr(index,0,length)) { SDL_free(index); SDL_free(root); return false; }
    unsigned count=0;
    char *next=index;
    bool ok=true;
    while (ok && *next) {
        char *path=next, *end=strchr(next,'\n');
        if (end) { *end=0; next=end+1; } else next+=strlen(next);
        if (!resource_name(path) || ++count>256) { ok=false; break; }
        char source[256], destination[4096];
        if (snprintf(source,sizeof(source),"resources/%s",path)>=(int)sizeof(source) ||
            snprintf(destination,sizeof(destination),"%s%s",root,path)>=(int)sizeof(destination)) { ok=false; break; }
        for (char *p=destination+strlen(root); *p; ++p) if (*p=='/') {
            *p=0; ok=SDL_CreateDirectory(destination); *p='/'; if (!ok) break;
        }
        size_t bytes=0;
        void *data=ok ? SDL_LoadFile(source,&bytes) : NULL;
        if (!data || bytes>16777216 || bytes>67108864-total) ok=false;
        if (ok) { total+=bytes; ok=SDL_SaveFile(destination,data,bytes); }
        SDL_free(data);
    }
    SDL_free(index);
    if (ok) ok=setenv("XU_PHONE_RESOURCE_ROOT",root,1)==0;
    SDL_free(root);
    return ok;
#else
    const char *base=SDL_GetBasePath();
    char root[4096];
    if (!base || snprintf(root,sizeof(root),"%sxu-resources",base)>=(int)sizeof(root)) return false;
    return setenv("XU_PHONE_RESOURCE_ROOT",root,1)==0;
#endif
}
