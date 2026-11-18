#ifndef XU_PHONE_GAME_H
#define XU_PHONE_GAME_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct XuPhoneGame XuPhoneGame;
enum { XU_GAME_READY = 0, XU_GAME_DONE = 1, XU_GAME_FAILED = -1 };

/* All calls belong to the creating SDL application thread. Each call returns
 * at a frame boundary; the Xu stack and its local owners live until shutdown.
 * Allocation failure leaves *out null. Once entered, *out owns even a failed
 * application's context and must be destroyed. Creation can already be DONE.
 * Destroy accepts only a completed game; stop first to unwind a suspended main.
 * A wrong-thread/reentrant call fails without resuming or freeing the owner. */
int xu_phone_game_create(XuPhoneGame **out);
int xu_phone_game_step(XuPhoneGame *game);
int xu_phone_game_stop(XuPhoneGame *game);
int xu_phone_game_destroy(XuPhoneGame *game);
long xu_phone_game_exit_status(const XuPhoneGame *game);
const char *xu_phone_game_error(void);
#ifdef __ANDROID__
long xu_phone_game_run_android(int (*pump)(void));
#endif

#ifdef __cplusplus
}
#endif
#endif
