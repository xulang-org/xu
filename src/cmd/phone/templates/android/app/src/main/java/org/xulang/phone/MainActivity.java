package org.xulang.phone;
import android.app.Activity;
import android.content.Context;
import android.content.res.Configuration;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.InputType;
import android.text.Selection;
import android.text.SpannableStringBuilder;
import android.view.Choreographer;
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
    private static native void stop();
    private static native void setPaths(String dataRoot,String resourceRoot);
    private static native void setNetworkEnv(String dnsServers,String caBundlePath);
    private static native void resize(double w,double h,double scale);
    private static native void insets(double top,double bottom,double left,double right,double ime);
    private static native void reducedMotion(boolean on);
    private static native void systemAppearance(boolean dark);
    private static native void fontScale(double scale);
    private static native void input(int kind,double x,double y,int buttons);
    private static native void inputEvent(int kind,double x,double y,int button,int buttons,int modifiers,int clickCount);
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
    @SuppressWarnings("deprecation")
    @Override public void onBackPressed() { backRequested(); }
    private static native boolean dark();
    private static native boolean overlay();
    private static native void attachHost(MainActivity activity);
    private static native void rendererReset();
    private static native int hapticTake();
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
            if(!view.multiline || view.returnKeyKind!=0) {
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
        int keyboardKind;
        int returnKeyKind;
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
            int inputClass=InputType.TYPE_CLASS_TEXT;
            if(keyboardKind==1) {
                inputClass=InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS;
            } else if(keyboardKind==2) {
                inputClass=InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI;
            } else if(keyboardKind==3) {
                inputClass=InputType.TYPE_CLASS_NUMBER;
            } else if(keyboardKind==4) {
                inputClass=InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL;
            } else if(keyboardKind==5) {
                inputClass=InputType.TYPE_CLASS_PHONE;
            }
            int type=inputClass;
            if(multiline && (type & InputType.TYPE_MASK_CLASS)==InputType.TYPE_CLASS_TEXT) {
                type |= InputType.TYPE_TEXT_FLAG_MULTI_LINE;
            }
            if(secureEntry) {
                if((type & InputType.TYPE_MASK_CLASS)==InputType.TYPE_CLASS_NUMBER) {
                    type |= InputType.TYPE_NUMBER_VARIATION_PASSWORD;
                } else {
                    type=(type & ~InputType.TYPE_MASK_VARIATION) | InputType.TYPE_TEXT_VARIATION_PASSWORD;
                }
            }
            outAttrs.inputType=type;
            int imeAction;
            if(returnKeyKind==1)imeAction=EditorInfo.IME_ACTION_DONE;
            else if(returnKeyKind==2)imeAction=EditorInfo.IME_ACTION_GO;
            else if(returnKeyKind==3)imeAction=EditorInfo.IME_ACTION_NEXT;
            else if(returnKeyKind==4)imeAction=EditorInfo.IME_ACTION_SEARCH;
            else if(returnKeyKind==5)imeAction=EditorInfo.IME_ACTION_SEND;
            else if(multiline)imeAction=EditorInfo.IME_ACTION_NONE;
            else if(keyboardKind==6)imeAction=EditorInfo.IME_ACTION_SEARCH;
            else imeAction=EditorInfo.IME_ACTION_DONE;
            outAttrs.imeOptions=EditorInfo.IME_FLAG_NO_EXTRACT_UI | imeAction;
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
            keyboardKind=0;
            returnKeyKind=0;
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
            int nextKeyboard=obj.optInt("keyboard",0);
            int nextReturnKey=obj.optInt("return_key",0);
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
            boolean traitsChanged=!newSession && (multiline!=nextMultiline || secureEntry!=nextPassword
                || keyboardKind!=nextKeyboard || returnKeyKind!=nextReturnKey);
            boolean textChanged=!displayText.equals(nextDisplay);
            boolean selChanged=selStart!=nextSelStart || selEnd!=nextSelEnd
                || compStart!=nextCompStart || compEnd!=nextCompEnd;
            sessionActive=true;
            sessionId=nextId;
            multiline=nextMultiline;
            secureEntry=nextPassword;
            keyboardKind=nextKeyboard;
            returnKeyKind=nextReturnKey;
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
                if(textChanged || traitsChanged) {
                    InputMethodManager imm=(InputMethodManager)getSystemService(Context.INPUT_METHOD_SERVICE);
                    if(imm!=null)imm.restartInput(this);
                } else if(selChanged) {
                    notifyImmSelection();
                }
            } else {
                if(traitsChanged) {
                    InputMethodManager imm=(InputMethodManager)getSystemService(Context.INPUT_METHOD_SERVICE);
                    if(imm!=null)imm.restartInput(this);
                }
                if(batchDepth==0)notifyImmSelection();
            }
        }
        @SuppressWarnings("deprecation")
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
                int mods=(shift?1:0)
                    |(event.isCtrlPressed()?2:0)
                    |(event.isAltPressed()?4:0)
                    |(event.isMetaPressed()?8:0);
                if(event.isCtrlPressed() || event.isMetaPressed()) {
                    int ascii=code==KeyEvent.KEYCODE_A?65:code==KeyEvent.KEYCODE_C?67:code==KeyEvent.KEYCODE_X?88:code==KeyEvent.KEYCODE_V?86:code==KeyEvent.KEYCODE_Z?90:code==KeyEvent.KEYCODE_Y?89:0;
                    if(ascii!=0) {
                        key(78,ascii,event.getRepeatCount(),mods);
                        key(79,ascii,0,mods);
                        refreshFromHost(true);
                        return true;
                    }
                }
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
                if(code==KeyEvent.KEYCODE_DPAD_UP || code==KeyEvent.KEYCODE_DPAD_DOWN) {
                    int k=code==KeyEvent.KEYCODE_DPAD_UP?263:264;
                    key(78,k,event.getRepeatCount(),mods);
                    key(79,k,0,mods);
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
                if((code==KeyEvent.KEYCODE_F10 && shift) || code==KeyEvent.KEYCODE_MENU) {
                    key(78,297,event.getRepeatCount(),1);
                    key(79,297,0,1);
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

    @SuppressWarnings("deprecation")
    private void applyLegacySystemBarAppearance(boolean night) {
        android.view.View decor=getWindow().getDecorView();
        int flags=decor.getSystemUiVisibility();
        int light=android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
            | android.view.View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
        decor.setSystemUiVisibility(night?flags & ~light:flags | light);
    }
    @SuppressWarnings("deprecation")
    private void applyLegacyEdgeToEdge(android.view.Window win) {
        win.setStatusBarColor(android.graphics.Color.TRANSPARENT);
        win.setNavigationBarColor(android.graphics.Color.TRANSPARENT);
        android.view.View decor=win.getDecorView();
        decor.setSystemUiVisibility(decor.getSystemUiVisibility()
            | android.view.View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            | android.view.View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
            | android.view.View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
    }
    @SuppressWarnings("deprecation")
    private android.view.WindowInsets applyLegacyInsets(android.view.WindowInsets wi,float density) {
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
    }
    private static boolean validResourceRelativePath(String path) {
        if(path==null || path.isEmpty() || path.length()>240 || path.equals("resources.index"))return false;
        String[] parts=path.split("/",-1);
        for(String part : parts) {
            if(part.isEmpty() || part.equals(".") || part.equals(".."))return false;
            for(int i=0;i<part.length();i++) {
                char c=part.charAt(i);
                boolean ok=(c>='A'&&c<='Z')||(c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='-'||c=='_'||c=='.';
                if(!ok)return false;
            }
        }
        return true;
    }
    @SuppressWarnings("deprecation")
    private static long legacyPackageVersion(android.content.pm.PackageInfo info) {
        return info.versionCode;
    }
    private String computeResourceStamp(byte[] indexBytes) {
        long verCode=0L;
        long updatedAt=0L;
        try {
            android.content.pm.PackageInfo info=getPackageManager().getPackageInfo(getPackageName(),0);
            verCode=android.os.Build.VERSION.SDK_INT>=28?info.getLongVersionCode():legacyPackageVersion(info);
            updatedAt=info.lastUpdateTime;
        } catch(Exception ignored) { }
        try {
            java.security.MessageDigest md=java.security.MessageDigest.getInstance("SHA-256");
            md.update(indexBytes);
            byte[] dig=md.digest();
            StringBuilder hex=new StringBuilder(dig.length*2);
            for(byte b : dig)hex.append(Character.forDigit((b>>4)&0xf,16)).append(Character.forDigit(b&0xf,16));
            return verCode+":"+updatedAt+":"+hex;
        } catch(Exception ignored) {
            return verCode+":"+updatedAt+":"+indexBytes.length;
        }
    }
    private void prepareHostPaths() {
        java.io.File dataDir=new java.io.File(getFilesDir(),"xu-data");
        java.io.File resDir=new java.io.File(getFilesDir(),"xu-resources");
        dataDir.mkdirs();
        resDir.mkdirs();
        try(java.io.InputStream idx=getAssets().open("resources/resources.index")) {
            java.io.ByteArrayOutputStream rawIdx=new java.io.ByteArrayOutputStream();
            byte[] chunk=new byte[4096];
            int rn;
            while((rn=idx.read(chunk))!=-1)rawIdx.write(chunk,0,rn);
            byte[] idxBytes=rawIdx.toByteArray();
            String stamp=computeResourceStamp(idxBytes);
            java.io.File stampFile=new java.io.File(resDir,".xu-stamp");
            String indexText=new String(idxBytes,StandardCharsets.UTF_8);
            String[] lines=indexText.split("\\r?\\n");
            boolean cacheHit=false;
            if(stampFile.isFile()) {
                try {
                    String existing=new String(java.nio.file.Files.readAllBytes(stampFile.toPath()),StandardCharsets.UTF_8).trim();
                    if(stamp.equals(existing)) {
                        cacheHit=true;
                        int checked=0;
                        for(String rawLine : lines) {
                            String rel=rawLine.trim();
                            if(rel.isEmpty())continue;
                            if(++checked>256 || !validResourceRelativePath(rel) || !new java.io.File(resDir,rel).isFile()) {
                                cacheHit=false;
                                break;
                            }
                        }
                    }
                } catch(Exception ignored) { cacheHit=false; }
            }
            if(!cacheHit) {
                int count=0;
                byte[] buf=new byte[8192];
                for(String rawLine : lines) {
                    String rel=rawLine.trim();
                    if(rel.isEmpty())continue;
                    if(++count>256 || !validResourceRelativePath(rel))break;
                    java.io.File outFile=new java.io.File(resDir,rel);
                    java.io.File parent=outFile.getParentFile();
                    if(parent!=null)parent.mkdirs();
                    try(java.io.InputStream in=getAssets().open("resources/"+rel);
                        java.io.FileOutputStream out=new java.io.FileOutputStream(outFile)) {
                        int n;
                        while((n=in.read(buf))!=-1)out.write(buf,0,n);
                    }
                }
                try(java.io.FileOutputStream sf=new java.io.FileOutputStream(stampFile)) {
                    sf.write(stamp.getBytes(StandardCharsets.UTF_8));
                }
            }
        } catch(java.io.IOException ignored) { }
        setPaths(dataDir.getAbsolutePath(),resDir.getAbsolutePath());
    }
    private void prepareNetworkEnv() {
        StringBuilder dns=new StringBuilder();
        try {
            android.net.ConnectivityManager cm=
                (android.net.ConnectivityManager)getSystemService(Context.CONNECTIVITY_SERVICE);
            if(cm!=null) {
                android.net.Network net=cm.getActiveNetwork();
                android.net.LinkProperties lp=net!=null?cm.getLinkProperties(net):null;
                if(lp!=null) {
                    java.util.List<java.net.InetAddress> addrs=lp.getDnsServers();
                    if(addrs!=null) {
                        java.util.HashSet<String> seen=new java.util.HashSet<>();
                        for(java.net.InetAddress addr : addrs) {
                            if(addr instanceof java.net.Inet4Address) {
                                String ip=addr.getHostAddress();
                                if(ip!=null && !ip.isEmpty() && seen.add(ip)) {
                                    if(dns.length()>0)dns.append(',');
                                    dns.append(ip);
                                }
                            }
                        }
                    }
                }
            }
        } catch(Throwable ignored) { }
        String caPath="";
        try {
            java.security.KeyStore ks=java.security.KeyStore.getInstance("AndroidCAStore");
            ks.load(null,null);
            String stamp=android.os.Build.FINGERPRINT+":"+ks.size();
            java.io.File caFile=new java.io.File(getCacheDir(),"xu-ca-bundle.pem");
            java.io.File stampFile=new java.io.File(getCacheDir(),".xu-ca-stamp");
            boolean hit=false;
            if(caFile.isFile() && caFile.length()>0 && stampFile.isFile()) {
                String existing=new String(java.nio.file.Files.readAllBytes(stampFile.toPath()),StandardCharsets.UTF_8).trim();
                if(stamp.equals(existing))hit=true;
            }
            if(!hit) {
                java.io.File tmpFile=new java.io.File(getCacheDir(),"xu-ca-bundle.pem.tmp");
                try(java.io.BufferedWriter w=new java.io.BufferedWriter(new java.io.OutputStreamWriter(
                        new java.io.FileOutputStream(tmpFile),StandardCharsets.US_ASCII))) {
                    java.util.Enumeration<String> aliases=ks.aliases();
                    while(aliases.hasMoreElements()) {
                        String alias=aliases.nextElement();
                        java.security.cert.Certificate cert=ks.getCertificate(alias);
                        if(cert instanceof java.security.cert.X509Certificate) {
                            String b64=android.util.Base64.encodeToString(cert.getEncoded(),android.util.Base64.DEFAULT);
                            w.write("-----BEGIN CERTIFICATE-----\n");
                            w.write(b64);
                            if(!b64.endsWith("\n"))w.write("\n");
                            w.write("-----END CERTIFICATE-----\n");
                        }
                    }
                }
                if(!tmpFile.renameTo(caFile)) {
                    try(java.io.FileInputStream in=new java.io.FileInputStream(tmpFile);
                        java.io.FileOutputStream out=new java.io.FileOutputStream(caFile)) {
                        byte[] buf=new byte[8192];
                        int n;
                        while((n=in.read(buf))!=-1)out.write(buf,0,n);
                    }
                    tmpFile.delete();
                }
                try(java.io.FileOutputStream sf=new java.io.FileOutputStream(stampFile)) {
                    sf.write(stamp.getBytes(StandardCharsets.UTF_8));
                }
            }
            if(caFile.isFile() && caFile.length()>0)caPath=caFile.getAbsolutePath();
        } catch(Throwable ignored) { }
        setNetworkEnv(dns.toString(),caPath);
    }
    private void syncSystemConfig(Configuration cfg) {
        if(cfg==null)return;
        boolean sysDark=(cfg.uiMode & Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES;
        systemAppearance(sysDark);
        fontScale(cfg.fontScale>0.0f?cfg.fontScale:1.0f);
    }
    private void runFrameTick() {
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
                applyLegacySystemBarAppearance(night);
            }
        }
        if(!evaluating) {
            String frame=poll();
            if(frame!=null) { evaluating=true; web.evaluateJavascript("xuFrame("+frame+")", value->evaluating=false); }
        }
        int haptic=hapticTake();
        if(haptic>0)performHaptic(haptic);
    }
    private final Choreographer.FrameCallback frameCallback=new Choreographer.FrameCallback() {
        @Override public void doFrame(long frameTimeNanos) {
            if(!running)return;
            runFrameTick();
            if(running)Choreographer.getInstance().postFrameCallback(this);
        }
    };
    public final class Bridge {
        @JavascriptInterface public void send(String message) {
            try {
                JSONArray v=new JSONArray(message);
                if(v.length()!=7 && v.length()!=10)return;
                int kind=v.getInt(0);
                if(kind==1)start();
                else if(kind==0)resize(v.getDouble(4),v.getDouble(5),v.getDouble(6));
                else if((kind==78 || kind==79) && v.length()==10)key(kind,v.getInt(7),v.getInt(9),v.getInt(8));
                else if(v.length()==10)inputEvent(kind,v.getDouble(1),v.getDouble(2),v.getInt(7),v.getInt(3),v.getInt(8),v.getInt(9));
                else input(kind,v.getDouble(1),v.getDouble(2),v.getInt(3));
            } catch(Exception ignored) { }
        }
    }
    private void performHaptic(int kind) {
        if(root==null)return;
        int code=android.view.HapticFeedbackConstants.CLOCK_TICK;
        if(kind==2) {
            code=android.view.HapticFeedbackConstants.VIRTUAL_KEY;
        } else if(kind==3) {
            code=android.os.Build.VERSION.SDK_INT>=30
                ? android.view.HapticFeedbackConstants.CONFIRM
                : android.view.HapticFeedbackConstants.VIRTUAL_KEY;
        } else if(kind==4) {
            code=android.os.Build.VERSION.SDK_INT>=30
                ? android.view.HapticFeedbackConstants.REJECT
                : android.view.HapticFeedbackConstants.LONG_PRESS;
        }
        root.performHapticFeedback(code,android.view.HapticFeedbackConstants.FLAG_IGNORE_VIEW_SETTING);
    }
    public byte[] hostClipboardRead() {
        try {
            android.content.ClipboardManager cm=
                (android.content.ClipboardManager)getSystemService(Context.CLIPBOARD_SERVICE);
            if(cm==null)return null;
            if(!cm.hasPrimaryClip())return new byte[0];
            android.content.ClipData clip=cm.getPrimaryClip();
            if(clip==null || clip.getItemCount()==0)return new byte[0];
            CharSequence seq=clip.getItemAt(0).coerceToText(this);
            if(seq==null)return new byte[0];
            return seq.toString().getBytes(StandardCharsets.UTF_8);
        } catch(Throwable ignored) {
            return null;
        }
    }
    public boolean hostClipboardWrite(byte[] utf8) {
        try {
            android.content.ClipboardManager cm=
                (android.content.ClipboardManager)getSystemService(Context.CLIPBOARD_SERVICE);
            if(cm==null)return false;
            String text=utf8!=null?new String(utf8,StandardCharsets.UTF_8):"";
            cm.setPrimaryClip(android.content.ClipData.newPlainText("xu",text));
            return true;
        } catch(Throwable ignored) {
            return false;
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
    @SuppressWarnings("deprecation")
    private void applyEdgeToEdge(android.view.Window win) {
        if(android.os.Build.VERSION.SDK_INT>=30) {
            win.setDecorFitsSystemWindows(false);
        } else {
            applyLegacyEdgeToEdge(win);
        }
    }
    private WebView buildWebView() {
        WebView w=new WebView(this);
        w.setFocusable(false);
        w.setFocusableInTouchMode(false);
        w.setBackgroundColor(android.graphics.Color.TRANSPARENT);
        w.getSettings().setJavaScriptEnabled(true);
        w.getSettings().setAllowFileAccess(false);
        w.getSettings().setAllowContentAccess(false);
        w.getSettings().setBlockNetworkLoads(true);
        w.addJavascriptInterface(new Bridge(),"XuPhone");
        w.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request) { return true; }
            @Override public boolean onRenderProcessGone(WebView view,android.webkit.RenderProcessGoneDetail detail) {
                evaluating=false;
                if(view==web && root!=null) {
                    root.removeView(web);
                    web.removeJavascriptInterface("XuPhone");
                    web.destroy();
                    web=buildWebView();
                    root.addView(web,new FrameLayout.LayoutParams(-1,-1));
                    rendererReset();
                    loadCanvasHtml();
                }
                return true;
            }
        });
        return w;
    }
    private void loadCanvasHtml() {
        if(web==null)return;
        try(java.io.InputStream in=getAssets().open("canvas.html")) {
            java.io.ByteArrayOutputStream bytes=new java.io.ByteArrayOutputStream();
            byte[] chunk=new byte[8192];int n;while((n=in.read(chunk))!=-1)bytes.write(chunk,0,n);
            String html=bytes.toString("UTF-8");
            web.loadDataWithBaseURL("https://xu.invalid/",html,"text/html","UTF-8",null);
        } catch(java.io.IOException error) { throw new IllegalStateException(error); }
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        android.view.Window win=getWindow();
        if(android.os.Build.VERSION.SDK_INT>=29) {
            win.setNavigationBarContrastEnforced(false);
        }
        applyEdgeToEdge(win);
        if(android.os.Build.VERSION.SDK_INT>=33) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,this::backRequested);
        }
        web=buildWebView();
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
            return applyLegacyInsets(wi,density);
        });
        setContentView(root);
        root.requestApplyInsets();
        prepareHostPaths();
        prepareNetworkEnv();
        attachHost(this);
        syncSystemConfig(getResources().getConfiguration());
        syncReducedMotion();
        loadCanvasHtml();
    }
    @Override public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        syncSystemConfig(newConfig);
        syncReducedMotion();
        if(root!=null)root.requestApplyInsets();
    }
    @Override public void onResume() { super.onResume(); web.onResume(); syncSystemConfig(getResources().getConfiguration()); syncReducedMotion(); if(root!=null)root.requestApplyInsets(); active(true); running=true; Choreographer.getInstance().postFrameCallback(frameCallback); }
    @Override public void onPause() { running=false; Choreographer.getInstance().removeFrameCallback(frameCallback); active(false); web.onPause(); super.onPause(); }
    @Override public void onDestroy() { running=false; Choreographer.getInstance().removeFrameCallback(frameCallback); active(false); attachHost(null); web.removeJavascriptInterface("XuPhone"); web.destroy(); super.onDestroy(); }
}
