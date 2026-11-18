#include "game.h"
#include <csetjmp>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <pthread.h>
#ifdef __ANDROID__
#include <setjmp.h>
#endif
#include <sys/mman.h>
#include <unistd.h>

#define XU_EXPORT __attribute__((used, visibility("default")))
#define XU_WEAK __attribute__((weak, noinline, visibility("default")))

struct alignas(16) Context {
    uint64_t registers[12], sp, floating[8], fpcr, fpsr, padding;
};
static_assert(offsetof(Context, sp) == 96 && offsetof(Context, floating) == 104 &&
              offsetof(Context, fpcr) == 168 && sizeof(Context) == 192, "context ABI");
extern "C" void xu_phone_game_switch(Context *, const Context *);
extern "C" void xu_app_start(int, char **, char **);
extern char **environ;

struct XuPhoneGame {
    Context host{}, application{};
    pthread_t owner;
    void *stack = nullptr, *state = nullptr;
    char **envp = nullptr;
    size_t stack_bytes = 0;
    bool running = false, done = false, stopping = false, suspended = false;
    long result = 0;
    std::map<uintptr_t, size_t> mappings;
};
static thread_local XuPhoneGame *current;
static thread_local char error_text[256];
#ifdef __ANDROID__
static thread_local int (*android_pump_fn)(void);
static thread_local bool android_mode;
static thread_local sigjmp_buf android_exit_env;
#endif

/* Snapshot host environ before Xu entry because drivers (e.g. SDL Vulkan) may call setenv and reallocate libc environ while Xu caches G_ENVP. */
static char **clone_environ(char **src) {
    size_t count = 0;
    if (src) {
        while (src[count]) ++count;
    }
    char **copy = static_cast<char **>(std::calloc(count + 1, sizeof(char *)));
    if (!copy) return nullptr;
    for (size_t i = 0; i < count; ++i) {
        size_t len = std::strlen(src[i]) + 1;
        copy[i] = static_cast<char *>(std::malloc(len));
        if (!copy[i]) {
            for (size_t j = 0; j < i; ++j) std::free(copy[j]);
            std::free(copy);
            return nullptr;
        }
        std::memcpy(copy[i], src[i], len);
    }
    copy[count] = nullptr;
    return copy;
}
static void free_environ(char **envp) {
    if (!envp) return;
    for (size_t i = 0; envp[i]; ++i) std::free(envp[i]);
    std::free(envp);
}
static bool release_mappings(XuPhoneGame *game) {
    bool failed = false;
    for (auto mapping : game->mappings)
        if (munmap(reinterpret_cast<void *>(mapping.first), mapping.second)) failed = true;
    game->mappings.clear();
    return !failed;
}
static int fail(const char *message) {
    std::snprintf(error_text, sizeof(error_text), "%s", message);
    return XU_GAME_FAILED;
}
extern "C" XU_EXPORT const char *xu_phone_game_error() { return error_text; }
static bool owned(const XuPhoneGame *game) {
    if (!game || !pthread_equal(game->owner, pthread_self())) {
        fail("Phone game call requires its creating application thread");
        return false;
    }
    if (current || game->running) {
        fail("Phone game callbacks cannot reenter an application");
        return false;
    }
    return true;
}
static int status(const XuPhoneGame *game) {
    if (!game->done) return XU_GAME_READY;
    if (game->result) return fail("Xu application returned a failure status");
    return XU_GAME_DONE;
}
extern "C" XU_EXPORT void *xu_phone_state() {
    if (!current || current->state) std::abort();
    current->state = std::calloc(1, 65536);
    if (!current->state) std::abort();
    return current->state;
}
extern "C" XU_EXPORT [[noreturn]] void xu_phone_finish(long result) {
    if (!current) std::abort();
    XuPhoneGame *game = current;
    game->result = result;
    game->done = true;
    game->suspended = false;
#ifdef __ANDROID__
    if (android_mode) siglongjmp(android_exit_env, 1);
#endif
    xu_phone_game_switch(&game->application, &game->host);
    std::abort(); // Completed continuations are never resumed.
}
extern "C" XU_EXPORT int xu_phone_game_is_hosted() { return current != nullptr ? 1 : 0; }
extern "C" XU_EXPORT int xu_phone_game_on_main_thread() {
    return (current != nullptr && pthread_equal(current->owner, pthread_self())) ? 1 : 0;
}
extern "C" XU_EXPORT int xu_phone_game_next_frame() {
    if (!current || !current->running || current->done) return -1;
    XuPhoneGame *game = current;
    if (game->stopping) return 0;
#ifdef __ANDROID__
    if (android_mode) {
        int rc = android_pump_fn ? android_pump_fn() : 1;
        if (rc <= 0) { game->stopping = true; return 0; }
        return 1;
    }
#endif
    game->suspended = true;
    xu_phone_game_switch(&game->application, &game->host);
    game->suspended = false;
    return game->stopping ? 0 : 1;
}
extern "C" XU_WEAK long long xu_phone_game_resume_epoch() { return 0; }
extern "C" XU_WEAK int xu_phone_game_set_trap_back(int enabled) {
    (void)enabled;
    return 0;
}
extern "C" XU_WEAK void *xu_phone_sdl_sym(const char *name) {
    (void)name;
    return nullptr;
}
extern "C" XU_WEAK int xu_phone_callback_mode() { return 0; }
extern "C" XU_WEAK int xu_phone_callback_take(int *discard_reason, int *has_quit, int *close_count,
                                              unsigned int *closes_out, int closes_cap) {
    (void)closes_out;
    (void)closes_cap;
    if (discard_reason) *discard_reason = 0;
    if (has_quit) *has_quit = 0;
    if (close_count) *close_count = 0;
    return 0;
}
extern "C" XU_WEAK int xu_phone_callback_pop(void *out_event_bytes, char *text_buf, int text_cap) {
    (void)out_event_bytes;
    (void)text_buf;
    (void)text_cap;
    return 0;
}
extern "C" XU_EXPORT void xu_phone_game_mapped(void *address, size_t bytes) {
    if (!current) std::abort();
    size_t page = static_cast<size_t>(getpagesize());
    current->mappings[reinterpret_cast<uintptr_t>(address)] = (bytes + page - 1) / page * page;
}
extern "C" XU_EXPORT void xu_phone_game_unmapped(void *address, size_t bytes) {
    if (!current) std::abort();
    size_t page = static_cast<size_t>(getpagesize());
    uintptr_t first = reinterpret_cast<uintptr_t>(address), end = first + (bytes + page - 1) / page * page;
    auto &maps = current->mappings;
    for (auto it = maps.begin(); it != maps.end();) {
        uintptr_t low = it->first, high = low + it->second;
        if (low >= end) break;
        if (high <= first) { ++it; continue; }
        it = maps.erase(it);
        if (low < first) maps[low] = first - low;
        if (high > end) { maps[end] = high - end; break; }
    }
}
static void enter() {
    char name[] = "XuPhoneGame";
    char *args[] = {name, nullptr};
    char **envp = environ;
    if (current && !current->envp) {
        current->envp = clone_environ(environ);
        if (current->envp) envp = current->envp;
    }
    xu_app_start(1, args, envp);
    std::abort();
}
static int resume(XuPhoneGame *game) {
    current = game;
    game->running = true;
    xu_phone_game_switch(&game->host, &game->application);
    game->running = false;
    current = nullptr;
    return status(game);
}
extern "C" XU_EXPORT int xu_phone_game_create(XuPhoneGame **out) {
    if (!out) return fail("Phone game requires an output owner");
    *out = nullptr;
    if (current) return fail("Phone game creation cannot reenter an application");
    auto *game = new XuPhoneGame;
    game->owner = pthread_self();
    size_t page = static_cast<size_t>(getpagesize());
    constexpr size_t usable = 8 * 1024 * 1024;
    game->stack_bytes = usable + page * 2;
    game->stack = mmap(nullptr, game->stack_bytes, PROT_NONE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (game->stack == MAP_FAILED) { delete game; return fail("Phone game stack allocation failed"); }
    char *base = static_cast<char *>(game->stack) + page;
    if (mprotect(base, usable, PROT_READ | PROT_WRITE)) {
        munmap(game->stack, game->stack_bytes);
        delete game;
        return fail("Phone game stack protection failed");
    }
    game->application.sp = reinterpret_cast<uintptr_t>(base + usable);
    game->application.registers[11] = reinterpret_cast<uintptr_t>(enter);
    *out = game;
    return resume(game);
}
extern "C" XU_EXPORT int xu_phone_game_step(XuPhoneGame *game) {
    if (!owned(game)) return XU_GAME_FAILED;
    if (game->done) return status(game);
    return resume(game);
}
extern "C" XU_EXPORT int xu_phone_game_stop(XuPhoneGame *game) {
    if (!owned(game)) return XU_GAME_FAILED;
    if (game->done) return status(game);
    game->stopping = true;
    return resume(game);
}
extern "C" XU_EXPORT long xu_phone_game_exit_status(const XuPhoneGame *game) {
    if (!owned(game)) return -1;
    return game->result;
}
extern "C" XU_EXPORT int xu_phone_game_destroy(XuPhoneGame *game) {
    if (!owned(game)) return XU_GAME_FAILED;
    if (!game->done) return fail("Phone game must finish or stop before destruction");
    bool failed = !release_mappings(game);
    if (munmap(game->stack, game->stack_bytes)) failed = true;
    free_environ(game->envp);
    std::free(game->state);
    delete game;
    return failed ? fail("Phone game mapping cleanup failed") : XU_GAME_DONE;
}
#ifdef __ANDROID__
extern "C" XU_EXPORT long xu_phone_game_run_android(int (*pump)(void)) {
    if (current) return -1;
    XuPhoneGame * volatile game = new XuPhoneGame;
    game->owner = pthread_self();
    game->running = true;
    current = game;
    android_pump_fn = pump;
    android_mode = true;
    if (sigsetjmp(android_exit_env, 0) == 0) {
        enter();
    }
    android_mode = false;
    android_pump_fn = nullptr;
    game->running = false;
    current = nullptr;
    long result = game->result;
    release_mappings(game);
    free_environ(game->envp);
    std::free(game->state);
    delete game;
    return result;
}
#endif

// The game profile does not bind the UI mailbox/Canvas host.
extern "C" int xu_ui_host_run_cooperative(const char *, int (*)(void *, int (*)(void)), void *, int (*)(void)) { return 127; }
extern "C" int xu_ui_mem_try_read_len(const char *, unsigned *) { return 0; }
extern "C" int xu_ui_mem_try_read_copy(const char *, char *, unsigned) { return 0; }
extern "C" int xu_ui_mem_try_write(const char *, const char *, unsigned, unsigned *) { return 0; }
