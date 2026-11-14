#include <jni.h>
#include <cstdlib>
#include "phone/phone.h"
extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_start(JNIEnv *,jclass) { xu_phone_start("android"); }
extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_resize(JNIEnv *,jclass,jdouble w,jdouble h,jdouble scale) { xu_phone_resize(w,h,scale); }
extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_insets(JNIEnv *,jclass,jdouble top,jdouble bottom,jdouble left,jdouble right,jdouble ime) { xu_phone_insets(top,bottom,left,right,ime); }
extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_reducedMotion(JNIEnv *,jclass,jboolean on) { xu_phone_reduced_motion(on?1:0); }
extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_input(JNIEnv *,jclass,jint kind,jdouble x,jdouble y,jint buttons) { xu_phone_input(kind,x,y,buttons); }
extern "C" JNIEXPORT void JNICALL Java_org_xulang_phone_MainActivity_active(JNIEnv *,jclass,jboolean on) { xu_phone_active(on); }
extern "C" JNIEXPORT jstring JNICALL Java_org_xulang_phone_MainActivity_poll(JNIEnv *env,jclass) {
  char *frame=xu_phone_poll();if(!frame)return nullptr;
  jstring result=env->NewStringUTF(frame);free(frame);return result;
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
