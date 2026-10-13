/* Ownership/ABI regression; also run with UndefinedBehaviorSanitizer. */
#include "../packages/sqlite/native/bridge.c"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>

#define N(name) EXPORT(name)
static xu_int text(const char *s) {
    size_t n = strlen(s);
    xu_int id = N(buffer_new)((xu_int)n);
    assert(id);
    for (size_t i = 0; i < n; i++) assert(N(buffer_put)(id, (xu_int)i, s[i], 1) == 0);
    return id;
}
static void *buffers(void *unused) {
    (void)unused;
    for (int i = 0; i < 100; i++) {
        xu_int id = N(buffer_new)(8);
        assert(id);
        assert(N(buffer_put)(id, 0, -1, 8) == 0);
        assert(N(buffer_get)(id, 0) == -1);
        assert(N(buffer_put)(id, 8, 1, 1) == SQLITE_MISUSE);
        N(buffer_free)(id);
        assert(N(buffer_len)(id) == -1);
        N(buffer_free)(id);
    }
    return NULL;
}
int main(void) {
    xu_int path = text(":memory:");
    xu_int db = N(open)(path);
    N(buffer_free)(path);
    assert(db && N(status)(db) == SQLITE_OK);
    xu_int sql = text("SELECT ? AS blob, ? AS text, ? AS number, ? AS real");
    xu_int stmt = N(prepare)(db, sql);
    N(buffer_free)(sql);
    assert(stmt && N(parameter_count)(stmt) == 4);
    xu_int empty = N(buffer_new)(0);
    assert(N(bind_buffer)(stmt, 1, empty, 1) == 0);
    assert(N(bind_buffer)(stmt, 2, empty, 0) == 0);
    N(buffer_free)(empty); /* SQLITE_TRANSIENT must retain both values. */
    assert(N(bind_int)(stmt, 3, LLONG_MIN) == 0);
    xu_int number = text("1.5");
    assert(N(bind_float)(stmt, 4, number) == 0);
    N(buffer_free)(number);
    assert(N(step)(stmt) == SQLITE_ROW);
    assert(N(column_type)(stmt, 0) == SQLITE_BLOB);
    assert(N(column_type)(stmt, 1) == SQLITE_TEXT);
    assert(N(column_int)(stmt, 2) == LLONG_MIN);
    xu_int number_result = N(column_float)(stmt, 3);
    assert(number_result && N(buffer_len)(number_result) == 3);
    N(buffer_free)(number_result);
    xu_int result = N(column_buffer)(stmt, 0, 1);
    assert(result && N(buffer_len)(result) == 0);
    assert(N(step)(stmt) == SQLITE_DONE);
    assert(N(column_type)(stmt, 0) == 0); /* Access after ROW is rejected. */
    N(finalize)(stmt);
    N(finalize)(stmt);
    assert(N(step)(stmt) == SQLITE_MISUSE);
    assert(N(buffer_len)(result) == 0); /* Copy survives finalization. */
    N(buffer_free)(result);
    sql = text("SELECT 1; ; SELECT 2");
    assert(N(prepare)(db, sql) == 0 && N(status)(db) != SQLITE_OK);
    N(buffer_free)(sql);
    sql = text("SELECT 1");
    stmt = N(prepare)(db, sql);
    N(buffer_free)(sql);
    assert(stmt);
    assert(N(close)(db) == 0); /* Close also finalizes outstanding statements. */
    assert(N(close)(db) == 0 && N(step)(stmt) == SQLITE_MISUSE);
    assert(N(buffer_new)(MAX_BUFFER + 1) == 0);
    pthread_t workers[8];
    for (int i = 0; i < 8; i++) assert(pthread_create(&workers[i], NULL, buffers, NULL) == 0);
    for (int i = 0; i < 8; i++) assert(pthread_join(workers[i], NULL) == 0);
    assert(objects == NULL);
    puts("native bridge ownership, stale tokens, typed ABI and concurrent buffers PASS");
    return 0;
}
