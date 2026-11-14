#include <jni.h>
#include <cstdlib>
#include <string>
#include "phone/phone.h"

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
