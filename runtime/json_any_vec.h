#ifndef JSON_ANY_VEC_H
#define JSON_ANY_VEC_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "json_allocator.h"

#ifdef __cplusplus
extern "C" {
#endif
typedef struct json_any_vec {
    unsigned char *data;
    size_t byte_len;
    size_t byte_cap;
} json_any_vec;

bool json_any_vec_reserve(json_allocator *allocator, json_any_vec *vec, size_t additional);

#ifdef __cplusplus
}
#endif

#endif
