package org.xulang.phone;
import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import org.json.JSONArray;

public final class MainActivity extends Activity {
    static { System.loadLibrary("xuphone"); }
    private static native void start();
    private static native void resize(double w,double h,double scale);
    private static native void insets(double top,double bottom,double left,double right,double ime);
    private static native void reducedMotion(boolean on);
    private static native void input(int kind,double x,double y,int buttons);
    private static native void active(boolean on);
    private static native String poll();
    private static native boolean back();
    private void backRequested() { if(!back())moveTaskToBack(true); }
    @Override public void onBackPressed() { backRequested(); }
    private static native boolean dark();
    private static native boolean overlay();
    private Boolean overlayMode;
    private WebView web;
    private FrameLayout root;
    private Boolean darkMode;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private boolean running, evaluating;
    private final Runnable tick=new Runnable() {
        public void run() {
            if(!running)return;
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
        web.setBackgroundColor(android.graphics.Color.TRANSPARENT);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.getSettings().setBlockNetworkLoads(true);
        web.addJavascriptInterface(new Bridge(),"XuPhone");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request) { return true; }
        });
        root=new FrameLayout(this);
        root.setBackgroundColor(0xfff6f3ef);
        root.addView(web,new FrameLayout.LayoutParams(-1,-1));
        root.setOnApplyWindowInsetsListener((view,wi)->{
            float density=getResources().getDisplayMetrics().density;
            if(density<=0.0f)density=1.0f;
            if(android.os.Build.VERSION.SDK_INT>=30) {
                android.graphics.Insets safe=wi.getInsets(android.view.WindowInsets.Type.systemBars()
                    | android.view.WindowInsets.Type.displayCutout());
                android.graphics.Insets ime=wi.getInsets(android.view.WindowInsets.Type.ime());
                insets(safe.top/density,safe.bottom/density,safe.left/density,safe.right/density,ime.bottom/density);
                return android.view.WindowInsets.CONSUMED;
            }
            android.view.DisplayCutout cutout=android.os.Build.VERSION.SDK_INT>=28?wi.getDisplayCutout():null;
            int top=Math.max(wi.getStableInsetTop(),cutout!=null?cutout.getSafeInsetTop():0);
            int bottom=Math.max(wi.getStableInsetBottom(),cutout!=null?cutout.getSafeInsetBottom():0);
            int left=Math.max(wi.getStableInsetLeft(),cutout!=null?cutout.getSafeInsetLeft():0);
            int right=Math.max(wi.getStableInsetRight(),cutout!=null?cutout.getSafeInsetRight():0);
            int sysBottom=wi.getSystemWindowInsetBottom();
            int imePx=sysBottom>bottom?sysBottom:0;
            insets(top/density,bottom/density,left/density,right/density,imePx/density);
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
