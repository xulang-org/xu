package org.xulang.phone;
import android.app.Activity;
import android.content.Context;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.InputType;
import android.text.Selection;
import android.text.SpannableStringBuilder;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.inputmethod.BaseInputConnection;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;
import android.view.inputmethod.InputMethodManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import java.nio.charset.StandardCharsets;
import org.json.JSONArray;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    static { System.loadLibrary("xuphone"); }
    private static native void start();
    private static native void resize(double w,double h,double scale);
    private static native void insets(double top,double bottom,double left,double right,double ime);
    private static native void reducedMotion(boolean on);
    private static native void input(int kind,double x,double y,int buttons);
    private static native void key(int kind,int key,int repeat,int modifiers);
    private static native void active(boolean on);
    private static native String poll();
    private static native String textInputState();
    private static native int textInputCommit(long id,long rev,byte[] utf8);
    private static native int textInputCompose(long id,long rev,byte[] utf8,int anchor16,int focus16);
    private static native int textInputFinishComposing(long id,long rev);
    private static native int textInputComposeRegion(long id,long rev,int start16,int end16);
    private static native int textInputReplace(long id,long rev,int start16,int end16,byte[] utf8);
    private static native int textInputSelect(long id,long rev,int anchor16,int focus16);
    private static native int textInputDeleteSurrounding(long id,long rev,int before16,int after16);
    private static native int textInputErase(long id,long rev,int backward);
    private static native int textInputMove(long id,long rev,int backward,int extend);
    private static native int textInputStop(long id);
    private static native boolean back();
    private void backRequested() { if(!back())moveTaskToBack(true); }
    @Override public void onBackPressed() { backRequested(); }
    private static native boolean dark();
    private static native boolean overlay();
    private Boolean overlayMode;
    private WebView web;
    private FrameLayout root;
    private XuInputView inputView;
    private Boolean darkMode;
    private boolean imeVisible;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private boolean running, evaluating;

    private final class XuInputConnection extends BaseInputConnection {
        private final XuInputView view;
        XuInputConnection(XuInputView v) { super(v,true); this.view=v; }
        @Override public Editable getEditable() { return view.editable; }
        @Override public boolean beginBatchEdit() {
            view.batchDepth++;
            return true;
        }
        @Override public boolean endBatchEdit() {
            if(view.batchDepth>0)view.batchDepth--;
            if(view.batchDepth==0)view.notifyImmSelection();
            return true;
        }
        @Override public boolean commitText(CharSequence text,int newCursorPosition) {
            if(!view.sessionActive)return false;
            String s=text!=null?text.toString():"";
            int insertStart=view.compStart>=0?view.compStart:Math.min(view.selStart,view.selEnd);
            textInputCommit(view.sessionId,0,s.getBytes(StandardCharsets.UTF_8));
            view.refreshFromHost(true);
            if(newCursorPosition!=1) {
                int len=view.displayText.length();
                int target=newCursorPosition>0?(insertStart+s.length()+newCursorPosition-1):(insertStart+newCursorPosition);
                target=Math.max(0,Math.min(len,target));
                textInputSelect(view.sessionId,0,target,target);
                view.refreshFromHost(true);
            }
            return true;
        }
        @Override public boolean setComposingText(CharSequence text,int newCursorPosition) {
            if(!view.sessionActive)return false;
            String s=text!=null?text.toString():"";
            int anchor16=s.length(), focus16=s.length();
            if(newCursorPosition<=0) { anchor16=0; focus16=0; }
            int insertStart=view.compStart>=0?view.compStart:Math.min(view.selStart,view.selEnd);
            textInputCompose(view.sessionId,0,s.getBytes(StandardCharsets.UTF_8),anchor16,focus16);
            view.refreshFromHost(true);
            if(newCursorPosition<0 || newCursorPosition>1) {
                int len=view.displayText.length();
                int target=newCursorPosition>0?(insertStart+s.length()+newCursorPosition-1):(insertStart+newCursorPosition);
                target=Math.max(0,Math.min(len,target));
                textInputSelect(view.sessionId,0,target,target);
                view.refreshFromHost(true);
            }
            return true;
        }
        @Override public boolean finishComposingText() {
            if(!view.sessionActive)return false;
            textInputFinishComposing(view.sessionId,0);
            view.refreshFromHost(true);
            return true;
        }
        @Override public boolean setComposingRegion(int start,int end) {
            if(!view.sessionActive)return false;
            textInputComposeRegion(view.sessionId,0,Math.max(0,start),Math.max(0,end));
            view.refreshFromHost(true);
            return true;
        }
        @Override public boolean setSelection(int start,int end) {
            if(!view.sessionActive)return false;
            textInputSelect(view.sessionId,0,Math.max(0,start),Math.max(0,end));
            view.refreshFromHost(true);
            return true;
        }
        @Override public boolean deleteSurroundingText(int beforeLength,int afterLength) {
            if(!view.sessionActive)return false;
            textInputDeleteSurrounding(view.sessionId,0,Math.max(0,beforeLength),Math.max(0,afterLength));
            view.refreshFromHost(true);
            return true;
        }
        @Override public boolean deleteSurroundingTextInCodePoints(int beforeLength,int afterLength) {
            if(!view.sessionActive)return false;
            int lo=Math.min(view.selStart,view.selEnd);
            int hi=Math.max(view.selStart,view.selEnd);
            String cur=view.displayText;
            int b16=0;
            if(beforeLength>0 && lo>0) {
                int cp=0,idx=lo;
                while(idx>0 && cp<beforeLength) {
                    idx=Character.offsetByCodePoints(cur,idx,-1);
                    cp++;
                }
                b16=lo-idx;
            }
            int a16=0;
            if(afterLength>0 && hi<cur.length()) {
                int cp=0,idx=hi;
                while(idx<cur.length() && cp<afterLength) {
                    idx=Character.offsetByCodePoints(cur,idx,1);
                    cp++;
                }
                a16=idx-hi;
            }
            textInputDeleteSurrounding(view.sessionId,0,b16,a16);
            view.refreshFromHost(true);
            return true;
        }
        @Override public boolean performEditorAction(int editorAction) {
            if(!view.sessionActive)return false;
            if(!view.multiline) {
                key(78,258,0,0);
                key(79,258,0,0);
                view.refreshFromHost(true);
                return true;
            }
            return super.performEditorAction(editorAction);
        }
        @Override public boolean sendKeyEvent(KeyEvent event) {
            if(view.handleKeyEvent(event))return true;
            return super.sendKeyEvent(event);
        }
    }

    private final class XuInputView extends View {
        final SpannableStringBuilder editable=new SpannableStringBuilder();
        boolean sessionActive;
        long sessionId;
        boolean multiline;
        boolean secureEntry;
        String displayText="";
        int selStart, selEnd;
        int compStart=-1, compEnd=-1;
        int batchDepth;
        private final BaseInputConnection spanHelper=new BaseInputConnection(this,false) {
            @Override public android.text.Editable getEditable() { return editable; }
        };
        XuInputView(Context ctx) {
            super(ctx);
            setFocusable(true);
            setFocusableInTouchMode(true);
        }
        @Override public boolean onCheckIsTextEditor() { return sessionActive; }
        @Override public boolean onTouchEvent(MotionEvent event) { return false; }
        @Override public InputConnection onCreateInputConnection(EditorInfo outAttrs) {
            if(!sessionActive)return null;
            outAttrs.inputType=InputType.TYPE_CLASS_TEXT
                | (multiline?InputType.TYPE_TEXT_FLAG_MULTI_LINE:0)
                | (secureEntry?InputType.TYPE_TEXT_VARIATION_PASSWORD:0);
            outAttrs.imeOptions=EditorInfo.IME_FLAG_NO_EXTRACT_UI
                | (multiline?EditorInfo.IME_ACTION_NONE:EditorInfo.IME_ACTION_DONE);
            outAttrs.initialSelStart=selStart;
            outAttrs.initialSelEnd=selEnd;
            return new XuInputConnection(this);
        }
        void notifyImmSelection() {
            InputMethodManager imm=(InputMethodManager)getSystemService(Context.INPUT_METHOD_SERVICE);
            if(imm!=null && sessionActive)imm.updateSelection(this,selStart,selEnd,compStart,compEnd);
        }
        void clearSession(boolean hideKeyboard) {
            boolean wasActive=sessionActive;
            sessionActive=false;
            sessionId=0;
            multiline=false;
            secureEntry=false;
            displayText="";
            selStart=0; selEnd=0;
            compStart=-1; compEnd=-1;
            editable.clear();
            if(wasActive) {
                InputMethodManager imm=(InputMethodManager)getSystemService(Context.INPUT_METHOD_SERVICE);
                if(imm!=null) {
                    if(hideKeyboard)imm.hideSoftInputFromWindow(getWindowToken(),0);
                    imm.restartInput(this);
                }
                clearFocus();
            }
        }
        void refreshFromHost(boolean fromIme) {
            String raw=textInputState();
            if(raw==null)return;
            try { applyHostJson(new JSONObject(raw),fromIme); } catch(Exception ignored) { }
        }
        void applyHostJson(JSONObject obj,boolean fromIme) {
            if(!obj.optBoolean("active",false)) {
                clearSession(true);
                return;
            }
            long nextId=obj.optLong("id",0);
            boolean nextMultiline=obj.optBoolean("multiline",false);
            boolean nextPassword=obj.optBoolean("password",false);
            boolean composing=obj.optBoolean("composing",false);
            String nextDisplay=obj.optString("display","");
            int len=nextDisplay.length();
            int a16=Math.max(0,Math.min(len,obj.optInt("display_anchor16",0)));
            int f16=Math.max(0,Math.min(len,obj.optInt("display_focus16",0)));
            int nextSelStart=Math.min(a16,f16);
            int nextSelEnd=Math.max(a16,f16);
            int nextCompStart=-1, nextCompEnd=-1;
            if(composing) {
                int s16=Math.max(0,Math.min(len,obj.optInt("start16",0)));
                String pre=obj.optString("preedit","");
                nextCompStart=s16;
                nextCompEnd=Math.min(len,s16+pre.length());
            }
            boolean newSession=!sessionActive || sessionId!=nextId;
            boolean textChanged=!displayText.equals(nextDisplay);
            boolean selChanged=selStart!=nextSelStart || selEnd!=nextSelEnd
                || compStart!=nextCompStart || compEnd!=nextCompEnd;
            sessionActive=true;
            sessionId=nextId;
            multiline=nextMultiline;
            secureEntry=nextPassword;
            displayText=nextDisplay;
            selStart=nextSelStart;
            selEnd=nextSelEnd;
            compStart=nextCompStart;
            compEnd=nextCompEnd;
            if(textChanged)editable.replace(0,editable.length(),displayText);
            Selection.setSelection(editable,selStart,selEnd);
            BaseInputConnection.removeComposingSpans(editable);
            if(nextCompStart>=0 && nextCompEnd>nextCompStart)spanHelper.setComposingRegion(nextCompStart,nextCompEnd);
            if(newSession) {
                requestFocus();
                long targetId=nextId;
                handler.post(()->{
                    if(sessionActive && sessionId==targetId) {
                        InputMethodManager imm=(InputMethodManager)getSystemService(Context.INPUT_METHOD_SERVICE);
                        if(imm!=null) {
                            imm.restartInput(this);
                            imm.showSoftInput(this,0);
                        }
                    }
                });
            } else if(!fromIme) {
                if(textChanged) {
                    InputMethodManager imm=(InputMethodManager)getSystemService(Context.INPUT_METHOD_SERVICE);
                    if(imm!=null)imm.restartInput(this);
                } else if(selChanged) {
                    notifyImmSelection();
                }
            } else if(batchDepth==0) {
                notifyImmSelection();
            }
        }
        boolean handleKeyEvent(KeyEvent event) {
            if(!sessionActive)return false;
            int code=event.getKeyCode();
            if(code==KeyEvent.KEYCODE_BACK)return false;
            int action=event.getAction();
            if(action==KeyEvent.ACTION_MULTIPLE && code==KeyEvent.KEYCODE_UNKNOWN) {
                String chars=event.getCharacters();
                if(chars!=null && !chars.isEmpty()) {
                    textInputCommit(sessionId,0,chars.getBytes(StandardCharsets.UTF_8));
                    refreshFromHost(true);
                    return true;
                }
                return false;
            }
            if(action==KeyEvent.ACTION_DOWN) {
                boolean shift=event.isShiftPressed();
                if(code==KeyEvent.KEYCODE_DEL) {
                    textInputErase(sessionId,0,1);
                    refreshFromHost(true);
                    return true;
                }
                if(code==KeyEvent.KEYCODE_FORWARD_DEL) {
                    textInputErase(sessionId,0,0);
                    refreshFromHost(true);
                    return true;
                }
                if(code==KeyEvent.KEYCODE_DPAD_LEFT) {
                    textInputMove(sessionId,0,1,shift?1:0);
                    refreshFromHost(true);
                    return true;
                }
                if(code==KeyEvent.KEYCODE_DPAD_RIGHT) {
                    textInputMove(sessionId,0,0,shift?1:0);
                    refreshFromHost(true);
                    return true;
                }
                if(code==KeyEvent.KEYCODE_MOVE_HOME) {
                    textInputSelect(sessionId,0,shift?selStart:0,0);
                    refreshFromHost(true);
                    return true;
                }
                if(code==KeyEvent.KEYCODE_MOVE_END) {
                    int n=displayText.length();
                    textInputSelect(sessionId,0,shift?selStart:n,n);
                    refreshFromHost(true);
                    return true;
                }
                if(code==KeyEvent.KEYCODE_ENTER || code==KeyEvent.KEYCODE_NUMPAD_ENTER) {
                    if(multiline) {
                        textInputCommit(sessionId,0,"\n".getBytes(StandardCharsets.UTF_8));
                        refreshFromHost(true);
                    } else {
                        key(78,258,event.getRepeatCount(),0);
                        key(79,258,0,0);
                    }
                    return true;
                }
                if(code==KeyEvent.KEYCODE_ESCAPE) {
                    return back();
                }
                int ch=event.getUnicodeChar();
                if(ch!=0 && (ch & KeyCharacterMap.COMBINING_ACCENT)==0 && !Character.isISOControl(ch)) {
                    String s=new String(Character.toChars(ch));
                    textInputCommit(sessionId,0,s.getBytes(StandardCharsets.UTF_8));
                    refreshFromHost(true);
                    return true;
                }
            }
            return false;
        }
        @Override public boolean onKeyDown(int keyCode,KeyEvent event) {
            if(handleKeyEvent(event))return true;
            return super.onKeyDown(keyCode,event);
        }
        @Override public boolean onKeyUp(int keyCode,KeyEvent event) {
            if(sessionActive && (keyCode==KeyEvent.KEYCODE_DEL || keyCode==KeyEvent.KEYCODE_FORWARD_DEL
                || keyCode==KeyEvent.KEYCODE_DPAD_LEFT || keyCode==KeyEvent.KEYCODE_DPAD_RIGHT
                || keyCode==KeyEvent.KEYCODE_ENTER || keyCode==KeyEvent.KEYCODE_NUMPAD_ENTER)) return true;
            return super.onKeyUp(keyCode,event);
        }
        @Override public boolean onKeyMultiple(int keyCode,int repeatCount,KeyEvent event) {
            if(handleKeyEvent(event))return true;
            return super.onKeyMultiple(keyCode,repeatCount,event);
        }
    }

    private final Runnable tick=new Runnable() {
        public void run() {
            if(!running)return;
            if(inputView!=null)inputView.refreshFromHost(false);
            boolean night=dark(), sheet=overlay();
            if(darkMode==null || darkMode!=night || overlayMode==null || overlayMode!=sheet) {
                darkMode=night; overlayMode=sheet;
                int background=night?0xff100e12:0xfff6f3ef;
                root.setBackgroundColor(background);
                if(android.os.Build.VERSION.SDK_INT>=30) {
                    int mask=android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                        | android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                    int appearance=night?0:mask;
                    android.view.WindowInsetsController ctrl=getWindow().getInsetsController();
                    if(ctrl!=null)ctrl.setSystemBarsAppearance(appearance,mask);
                } else {
                    android.view.View decor=getWindow().getDecorView();
                    int flags=decor.getSystemUiVisibility();
                    int light=android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
                        | android.view.View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
                    decor.setSystemUiVisibility(night?flags & ~light:flags | light);
                }
            }
            if(!evaluating) {
                String frame=poll();
                if(frame!=null) { evaluating=true; web.evaluateJavascript("xuFrame("+frame+")", value->evaluating=false); }
            }
            handler.postDelayed(this,16);
        }
    };
    public final class Bridge {
        @JavascriptInterface public void send(String message) {
            try {
                JSONArray v=new JSONArray(message);
                if(v.length()!=7)return;
                int kind=v.getInt(0);
                if(kind==1)start();
                else if(kind==0)resize(v.getDouble(4),v.getDouble(5),v.getDouble(6));
                else input(kind,v.getDouble(1),v.getDouble(2),v.getInt(3));
            } catch(Exception ignored) { }
        }
    }
    private void syncReducedMotion() {
        float scale=1.0f;
        try {
            scale=android.provider.Settings.Global.getFloat(getContentResolver(),
                android.provider.Settings.Global.ANIMATOR_DURATION_SCALE,1.0f);
        } catch(Exception ignored) { }
        reducedMotion(scale<=0.0f);
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        android.view.Window win=getWindow();
        win.setStatusBarColor(android.graphics.Color.TRANSPARENT);
        win.setNavigationBarColor(android.graphics.Color.TRANSPARENT);
        if(android.os.Build.VERSION.SDK_INT>=29) {
            win.setNavigationBarContrastEnforced(false);
        }
        if(android.os.Build.VERSION.SDK_INT>=30) {
            win.setDecorFitsSystemWindows(false);
        } else {
            android.view.View decor=win.getDecorView();
            decor.setSystemUiVisibility(decor.getSystemUiVisibility()
                | android.view.View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | android.view.View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | android.view.View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        }
        if(android.os.Build.VERSION.SDK_INT>=33) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,this::backRequested);
        }
        web=new WebView(this);
        web.setFocusable(false);
        web.setFocusableInTouchMode(false);
        web.setBackgroundColor(android.graphics.Color.TRANSPARENT);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.getSettings().setBlockNetworkLoads(true);
        web.addJavascriptInterface(new Bridge(),"XuPhone");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request) { return true; }
        });
        inputView=new XuInputView(this);
        root=new FrameLayout(this);
        root.setBackgroundColor(0xfff6f3ef);
        root.addView(inputView,new FrameLayout.LayoutParams(1,1));
        root.addView(web,new FrameLayout.LayoutParams(-1,-1));
        root.setOnApplyWindowInsetsListener((view,wi)->{
            float density=getResources().getDisplayMetrics().density;
            if(density<=0.0f)density=1.0f;
            if(android.os.Build.VERSION.SDK_INT>=30) {
                android.graphics.Insets safe=wi.getInsets(android.view.WindowInsets.Type.systemBars()
                    | android.view.WindowInsets.Type.displayCutout());
                android.graphics.Insets ime=wi.getInsets(android.view.WindowInsets.Type.ime());
                double imeDp=ime.bottom/density;
                boolean nowVisible=imeDp>0.0;
                if(imeVisible && !nowVisible && inputView!=null && inputView.sessionActive) {
                    textInputStop(inputView.sessionId);
                    inputView.clearSession(false);
                }
                imeVisible=nowVisible;
                insets(safe.top/density,safe.bottom/density,safe.left/density,safe.right/density,imeDp);
                return android.view.WindowInsets.CONSUMED;
            }
            android.view.DisplayCutout cutout=android.os.Build.VERSION.SDK_INT>=28?wi.getDisplayCutout():null;
            int top=Math.max(wi.getStableInsetTop(),cutout!=null?cutout.getSafeInsetTop():0);
            int bottom=Math.max(wi.getStableInsetBottom(),cutout!=null?cutout.getSafeInsetBottom():0);
            int left=Math.max(wi.getStableInsetLeft(),cutout!=null?cutout.getSafeInsetLeft():0);
            int right=Math.max(wi.getStableInsetRight(),cutout!=null?cutout.getSafeInsetRight():0);
            int sysBottom=wi.getSystemWindowInsetBottom();
            int imePx=sysBottom>bottom?sysBottom:0;
            double imeDp=imePx/density;
            boolean nowVisible=imeDp>0.0;
            if(imeVisible && !nowVisible && inputView!=null && inputView.sessionActive) {
                textInputStop(inputView.sessionId);
                inputView.clearSession(false);
            }
            imeVisible=nowVisible;
            insets(top/density,bottom/density,left/density,right/density,imeDp);
            return wi.consumeSystemWindowInsets();
        });
        setContentView(root);
        root.requestApplyInsets();
        syncReducedMotion();
        try(java.io.InputStream in=getAssets().open("canvas.html")) {
            java.io.ByteArrayOutputStream bytes=new java.io.ByteArrayOutputStream();
            byte[] chunk=new byte[8192];int n;while((n=in.read(chunk))!=-1)bytes.write(chunk,0,n);
            String html=bytes.toString("UTF-8");
            web.loadDataWithBaseURL("https://xu.invalid/",html,"text/html","UTF-8",null);
        } catch(java.io.IOException error) { throw new IllegalStateException(error); }
    }
    @Override public void onResume() { super.onResume(); web.onResume(); syncReducedMotion(); if(root!=null)root.requestApplyInsets(); active(true); running=true; handler.post(tick); }
    @Override public void onPause() { running=false; handler.removeCallbacks(tick); active(false); web.onPause(); super.onPause(); }
    @Override public void onDestroy() { running=false; handler.removeCallbacks(tick); web.removeJavascriptInterface("XuPhone"); web.destroy(); super.onDestroy(); }
}
