#include "json_key_dispatch.h"

#include <string.h>

static int json_key_compare(const json_slice *left, const json_slice *right)
{
    if (left->len < right->len) {
        return -1;
    }
    if (left->len > right->len) {
        return 1;
    }
    if (left->len == 0) {
        return 0;
    }
    return memcmp(left->ptr, right->ptr, left->len);
}

const json_key_entry *json_key_dispatch(const json_key_map *map, const json_slice *key)
{
    if (map == NULL || key == NULL ||
        (map->len != 0 && map->entries == NULL) ||
        (key->len != 0 && key->ptr == NULL)) {
        return NULL;
    }

    size_t begin = 0;
    size_t end = map->len;
    while (begin < end) {
        const size_t middle = begin + (end - begin) / 2;
        const json_key_entry *entry = &map->entries[middle];
        const int order = json_key_compare(key, &entry->key);
        if (order == 0) {
            return entry;
        }
        if (order < 0) {
            end = middle;
        } else {
            begin = middle + 1;
        }
    }
    return NULL;
}
