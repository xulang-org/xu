package org.xulang.game;

import android.view.KeyEvent;

public final class MainActivity extends org.libsdl.app.SDLActivity {
    @Override
    public void onBackPressed() {
        if (nativeGetHintBoolean("SDL_ANDROID_TRAP_BACK_BUTTON", false)) {
            onNativeKeyDown(KeyEvent.KEYCODE_BACK);
            onNativeKeyUp(KeyEvent.KEYCODE_BACK);
            return;
        }
        super.onBackPressed();
    }
}
