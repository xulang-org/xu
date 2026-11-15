#include <jni.h>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include "phone/phone.h"

static JavaVM *g_vm = nullptr;
static std::mutex g_host_mutex;
static jobject g_activity = nullptr;
static jmethodID g_clip_read = nullptr;
static jmethodID g_clip_write = nullptr;

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *) {
  g_vm = vm;
  return JNI_VERSION_1_6;
}

static JNIEnv *current_env(bool *attached) {
  *attached = false;
  if (!g_vm) return nullptr;
  JNIEnv *env = nullptr;
  jint st = g_vm->GetEnv((void **)&env, JNI_VERSION_1_6);
  if (st == JNI_OK) return env;
  if (st == JNI_EDETACHED && g_vm->AttachCurrentThread(&env, nullptr) == JNI_OK) {
    *attached = true;
    return env;
  }
  return nullptr;
}

static int android_clipboard_read(char *out, unsigned cap, unsigned *out_len) {
  if (!out_len) return 0;
  bool attached = false;
  JNIEnv *env = current_env(&attached);
  jobject act = nullptr;
  jmethodID mid = nullptr;
  {
    std::lock_guard<std::mutex> lock(g_host_mutex);
    if (env && g_activity && g_clip_read) {
      act = env->NewLocalRef(g_activity);
      mid = g_clip_read;
    }
  }
  int rc = 0;
  if (env && act && mid) {
    jbyteArray arr = (jbyteArray)env->CallObjectMethod(act, mid);
    if (env->ExceptionCheck()) {
      env->ExceptionClear();
    } else if (arr) {
      jsize len = env->GetArrayLength(arr);
      if (len >= 0 && (unsigned)len <= cap) {
        if (len > 0 && out) env->GetByteArrayRegion(arr, 0, len, reinterpret_cast<jbyte *>(out));
        *out_len = (unsigned)len;
        rc = 1;
      }
      env->DeleteLocalRef(arr);
    }
  }
  if (env && act) env->DeleteLocalRef(act);
  if (attached && g_vm) g_vm->DetachCurrentThread();
  return rc;
}

static int android_clipboard_write(const char *utf8, unsigned len) {
  bool attached = false;
  JNIEnv *env = current_env(&attached);
  jobject act = nullptr;
  jmethodID mid = nullptr;
  {
    std::lock_guard<std::mutex> lock(g_host_mutex);
    if (env && g_activity && g_clip_write) {
      act = env->NewLocalRef(g_activity);
      mid = g_clip_write;
    }
  }
  int rc = 0;
  if (env && act && mid) {
    jbyteArray arr = env->NewByteArray((jsize)len);
    if (arr) {
      if (len > 0 && utf8) env->SetByteArrayRegion(arr, 0, (jsize)len, reinterpret_cast<const jbyte *>(utf8));
      jboolean ok = env->CallBooleanMethod(act, mid, arr);
      if (env->ExceptionCheck()) env->ExceptionClear();
      else rc = ok ? 1 : 0;
      env->DeleteLocalRef(arr);
    } else if (env->ExceptionCheck()) {
      env->ExceptionClear();
    }
  }
  if (env && act) env->DeleteLocalRef(act);
  if (attached && g_vm) g_vm->DetachCurrentThread();
  return rc;
}

static std::string copy_utf8(JNIEnv *env, jbyteArray arr) {
  if (!arr) return {};
  jsize len = env->GetArrayLength(arr);
  if (len <= 0) return {};
  std::string out((size_t)len, '\0');
  env->GetByteArrayRegion(arr, 0, len, reinterpret_cast<jbyte *>(&out[0]));
  return out;
}

extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_start(JNIEnv *,jclass) { xu_phone_start("android"); }
extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_resize(JNIEnv *,jclass,jdouble w,jdouble h,jdouble scale) { xu_phone_resize(w,h,scale); }
extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_insets(JNIEnv *,jclass,jdouble top,jdouble bottom,jdouble left,jdouble right,jdouble ime) { xu_phone_insets(top,bottom,left,right,ime); }
extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_reducedMotion(JNIEnv *,jclass,jboolean on) { xu_phone_reduced_motion(on?1:0); }
extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_input(JNIEnv *,jclass,jint kind,jdouble x,jdouble y,jint buttons) { xu_phone_input(kind,x,y,buttons); }
extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_key(JNIEnv *,jclass,jint kind,jint key,jint repeat,jint modifiers) { xu_phone_key(kind,key,repeat,modifiers); }
extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_active(JNIEnv *,jclass,jboolean on) { xu_phone_active(on); }
extern "C" JNIEXPORT jstring JNICALL Java_org_xulang_phone_MainActivity_poll(JNIEnv *env,jclass) {
  char *frame=xu_phone_poll();if(!frame)return nullptr;
  jstring result=env->NewStringUTF(frame);free(frame);return result;
}

extern "C" JNIEXPORT jstring JNICALL Java_org_xulang_phone_MainActivity_textInputState(JNIEnv *env,jclass) {
  char *state=xu_phone_text_input_state();if(!state)return nullptr;
  jstring result=env->NewStringUTF(state);free(state);return result;
}

extern "C" JNIEXPORT jint JNICALL Java_org_xulang_phone_MainActivity_textInputCommit(JNIEnv *env,jclass,jlong id,jlong rev,jbyteArray utf8) {
  std::string s=copy_utf8(env,utf8);
  return xu_phone_text_input_commit((uint64_t)id,(uint64_t)rev,s.data(),(unsigned)s.size());
}

extern "C" JNIEXPORT jint JNICALL Java_org_xulang_phone_MainActivity_textInputCompose(JNIEnv *env,jclass,jlong id,jlong rev,jbyteArray utf8,jint anchor16,jint focus16) {
  std::string s=copy_utf8(env,utf8);
  return xu_phone_text_input_compose((uint64_t)id,(uint64_t)rev,s.data(),(unsigned)s.size(),(unsigned)anchor16,(unsigned)focus16);
}

extern "C" JNIEXPORT jint JNICALL Java_org_xulang_phone_MainActivity_textInputFinishComposing(JNIEnv *,jclass,jlong id,jlong rev) {
  return xu_phone_text_input_finish_composing((uint64_t)id,(uint64_t)rev);
}

extern "C" JNIEXPORT jint JNICALL Java_org_xulang_phone_MainActivity_textInputComposeRegion(JNIEnv *,jclass,jlong id,jlong rev,jint start16,jint end16) {
  return xu_phone_text_input_compose_region((uint64_t)id,(uint64_t)rev,(unsigned)start16,(unsigned)end16);
}

extern "C" JNIEXPORT jint JNICALL Java_org_xulang_phone_MainActivity_textInputReplace(JNIEnv *env,jclass,jlong id,jlong rev,jint start16,jint end16,jbyteArray utf8) {
  std::string s=copy_utf8(env,utf8);
  return xu_phone_text_input_replace((uint64_t)id,(uint64_t)rev,(unsigned)start16,(unsigned)end16,s.data(),(unsigned)s.size());
}

extern "C" JNIEXPORT jint JNICALL Java_org_xulang_phone_MainActivity_textInputSelect(JNIEnv *,jclass,jlong id,jlong rev,jint anchor16,jint focus16) {
  return xu_phone_text_input_select((uint64_t)id,(uint64_t)rev,(unsigned)anchor16,(unsigned)focus16);
}

extern "C" JNIEXPORT jint JNICALL Java_org_xulang_phone_MainActivity_textInputDeleteSurrounding(JNIEnv *,jclass,jlong id,jlong rev,jint before16,jint after16) {
  return xu_phone_text_input_delete_surrounding((uint64_t)id,(uint64_t)rev,(unsigned)before16,(unsigned)after16);
}

extern "C" JNIEXPORT jint JNICALL Java_org_xulang_phone_MainActivity_textInputErase(JNIEnv *,jclass,jlong id,jlong rev,jint backward) {
  return xu_phone_text_input_erase((uint64_t)id,(uint64_t)rev,backward);
}

extern "C" JNIEXPORT jint JNICALL Java_org_xulang_phone_MainActivity_textInputMove(JNIEnv *,jclass,jlong id,jlong rev,jint backward,jint extend) {
  return xu_phone_text_input_move((uint64_t)id,(uint64_t)rev,backward,extend);
}

extern "C" JNIEXPORT jint JNICALL Java_org_xulang_phone_MainActivity_textInputStop(JNIEnv *,jclass,jlong id) {
  return xu_phone_text_input_stop((uint64_t)id);
}

extern "C" JNIEXPORT jboolean JNICALL Java_org_xulang_phone_MainActivity_back(JNIEnv *,jclass) {
  return xu_phone_back()?JNI_TRUE:JNI_FALSE;
}

extern "C" JNIEXPORT jboolean JNICALL Java_org_xulang_phone_MainActivity_dark(JNIEnv *,jclass) {
  return xu_phone_dark()?JNI_TRUE:JNI_FALSE;
}

extern "C" JNIEXPORT jboolean JNICALL Java_org_xulang_phone_MainActivity_overlay(JNIEnv *,jclass) {
  return xu_phone_overlay()?JNI_TRUE:JNI_FALSE;
}

extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_attachHost(JNIEnv *env,jclass cls,jobject activity) {
  std::lock_guard<std::mutex> lock(g_host_mutex);
  if (g_activity) { env->DeleteGlobalRef(g_activity); g_activity = nullptr; }
  g_clip_read = nullptr;
  g_clip_write = nullptr;
  if (activity) {
    g_activity = env->NewGlobalRef(activity);
    g_clip_read = env->GetMethodID(cls, "hostClipboardRead", "()[B");
    g_clip_write = env->GetMethodID(cls, "hostClipboardWrite", "([B)Z");
    if (env->ExceptionCheck()) { env->ExceptionClear(); g_clip_read = nullptr; g_clip_write = nullptr; }
    xu_phone_set_clipboard(android_clipboard_read, android_clipboard_write);
  } else {
    xu_phone_set_clipboard(nullptr, nullptr);
  }
}

extern "C" JNIEXPORT jint JNICALL Java_org_xulang_phone_MainActivity_hapticTake(JNIEnv *,jclass) {
  return xu_phone_haptic_take();
}
