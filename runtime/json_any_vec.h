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

bool json_any_vec_init(json_allocator *allocator, json_any_vec *vec, size_t reserved);

void json_any_vec_move_to(json_any_vec *vec, void **elems, size_t *count, size_t elem_size);

#ifdef __cplusplus
}
#endif

#endif