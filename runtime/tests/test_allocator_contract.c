#include "example/example.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>

enum {
    ARENA_SIZE = 64 * 1024,
    MAX_POINTERS = 256,
};

typedef union arena_storage {
    max_align_t alignment;
    unsigned char bytes[ARENA_SIZE];
} arena_storage;

typedef struct arena_state {
    arena_storage storage;
    void *pointers[MAX_POINTERS];
    unsigned char live[MAX_POINTERS];
    size_t offset;
    size_t allocations;
    size_t frees;
    size_t invalid_frees;
} arena_state;

static arena_state arena;
static size_t unexpected_heap_calls;

static void arena_reset(void)
{
    memset(&arena, 0, sizeof(arena));
}

static void *arena_malloc(size_t size)
{
    const size_t alignment = _Alignof(max_align_t);
    const size_t begin = (arena.offset + alignment - 1) & ~(alignment - 1);
    if (size > ARENA_SIZE - begin) {
        return NULL;
    }
    size_t slot = 0;
    while (slot < MAX_POINTERS && arena.live[slot] != 0) {
        ++slot;
    }
    if (slot == MAX_POINTERS) {
        return NULL;
    }
    void *result = arena.storage.bytes + begin;
    arena.offset = begin + (size == 0 ? 1 : size);
    arena.pointers[slot] = result;
    arena.live[slot] = 1;
    ++arena.allocations;
    return result;
}

static void arena_free(void *pointer)
{
    if (pointer == NULL) {
        return;
    }
    for (size_t slot = 0; slot < MAX_POINTERS; ++slot) {
        if (arena.pointers[slot] == pointer && arena.live[slot] != 0) {
            arena.live[slot] = 0;
            ++arena.frees;
            return;
        }
    }
    ++arena.invalid_frees;
}

static int arena_is_clean(void)
{
    if (arena.allocations != arena.frees || arena.invalid_frees != 0) {
        return 0;
    }
    for (size_t slot = 0; slot < MAX_POINTERS; ++slot) {
        if (arena.live[slot] != 0) {
            return 0;
        }
    }
    return 1;
}

static json_slice literal_slice(const char *text, size_t length)
{
    json_slice result = {text, length};
    return result;
}

static int decode_user_with_arena(json_allocator *allocator)
{
    static const char input[] =
        "{\"id\":1,\"name\":\"arena\",\"age\":18,"
        "\"bases\":[{\"id\":2}],\"metadata\":{}}";
    json_parser parser = {0};
    User value = {0};
    json_parser_init(
        &parser, allocator, literal_slice(input, sizeof(input) - 1)
    );
    if (!decodeUser(&parser, &value)) {
        return 0;
    }
    releaseUser(allocator, &value);
    releaseUser(allocator, &value);
    return value.name == NULL && value.bases == NULL && value.basesLen == 0;
}

static int decode_string_slots_with_arena(json_allocator *allocator)
{
    static const char input[] = "[\"one\",\"two\",\"three\"]";
    json_parser parser = {0};
    StringSlots value = {0};
    json_parser_init(
        &parser, allocator, literal_slice(input, sizeof(input) - 1)
    );
    if (!decodeStringSlots(&parser, &value)) {
        return 0;
    }
    releaseStringSlots(allocator, &value);
    releaseStringSlots(allocator, &value);
    return value.elems == NULL && value.cap == 0;
}

void *__wrap_malloc(size_t size)
{
    (void)size;
    ++unexpected_heap_calls;
    return NULL;
}

void *__wrap_calloc(size_t count, size_t size)
{
    (void)count;
    (void)size;
    ++unexpected_heap_calls;
    return NULL;
}

void *__wrap_realloc(void *pointer, size_t size)
{
    (void)pointer;
    (void)size;
    ++unexpected_heap_calls;
    return NULL;
}

void __wrap_free(void *pointer)
{
    (void)pointer;
    ++unexpected_heap_calls;
}

void *__wrap_aligned_alloc(size_t alignment, size_t size)
{
    (void)alignment;
    (void)size;
    ++unexpected_heap_calls;
    return NULL;
}

int main(void)
{
    json_allocator allocator = {arena_malloc, arena_free};

    arena_reset();
    if (!decode_user_with_arena(&allocator) || !arena_is_clean()) {
        return 1;
    }
    arena_reset();
    if (!decode_string_slots_with_arena(&allocator) || !arena_is_clean()) {
        return 2;
    }
    return unexpected_heap_calls == 0 ? 0 : 3;
}
