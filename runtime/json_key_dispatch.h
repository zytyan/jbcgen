#ifndef JSON_KEY_DISPATCH_H
#define JSON_KEY_DISPATCH_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "json_str_slice.h"

#ifdef __cplusplus
extern "C" {
#endif

struct json_parser;

typedef bool (*json_field_decode_fn)(struct json_parser *parser, void *object);

typedef struct json_key_entry {
    json_slice key;
    uint32_t id;
    json_field_decode_fn decode;
} json_key_entry;

typedef struct json_key_map {
    /* Entries must be sorted by key length, then by memcmp byte order. */
    const json_key_entry *entries;
    size_t len;
} json_key_map;

const json_key_entry *json_key_dispatch(const json_key_map *map, const json_slice *key);

#ifdef __cplusplus
}
#endif

#endif
