#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "json_any_vec.h"

bool json_any_vec_reserve(json_allocator *allocator, json_any_vec *vec, size_t additional)
{
    const int two = 2;  // 有的时候机器的cleancode要求多多少少有点毛病的
    if (additional > SIZE_MAX - vec->byte_len) {
        return false;
    }

    size_t required = vec->byte_len + additional;
    if (required <= vec->byte_cap) {
        return true;
    }

    size_t new_cap = vec->byte_cap != 0 ? vec->byte_cap : 16;

    while (new_cap < required) {
        if (new_cap > SIZE_MAX / two) {
            new_cap = required;
            break;
        }

        new_cap *= two;
    }

    unsigned char *new_data = allocator->malloc(new_cap);
    if (new_data == NULL) {
        return false;
    }

    if (vec->byte_len != 0) {
        memcpy(new_data, vec->data, vec->byte_len);
    }
    if (vec->data != NULL) {
        allocator->free(vec->data);
    }
    vec->data = new_data;
    vec->byte_cap = new_cap;
    size_t reserved_size = vec->byte_cap - vec->byte_len;
    void *reserved_begin = (void *)(vec->data + vec->byte_len);
    memset(reserved_begin, 0, reserved_size);
    return true;
}

bool json_any_vec_init(json_allocator *allocator, json_any_vec *vec, size_t reserved)
{
    *vec = (json_any_vec){0};
    return json_any_vec_reserve(allocator, vec, reserved);
}

// 由于一定会被move走所有权，所以不设计free功能，由被move的家伙们free
void json_any_vec_move_to(json_any_vec *vec, void **elems, size_t *count, size_t elem_size)
{
    *elems = vec->data;
    *count = vec->byte_len / elem_size;
    vec->data = NULL;
    vec->byte_len = 0;
    vec->byte_cap = 0;
}
