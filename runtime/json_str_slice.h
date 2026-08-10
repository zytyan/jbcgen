#ifndef JSON_STR_SLICE_H
#define JSON_STR_SLICE_H

#include <stdbool.h>
#include <stddef.h>

#include "json_allocator.h"
#include "json_error.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct json_slice {
    const char *ptr;
    size_t len;
} json_slice;

typedef struct json_string {
    char *ptr;
    size_t len;
    size_t cap;
} json_string;

typedef enum json_cow_str_kind {
    JSON_COW_OWNED_STRING,
    JSON_COW_MUT_BORROWED_STRING,
    JSON_COW_CONST_BORROWED_SLICE,
} json_cow_str_kind;

typedef struct json_cow_str {
    union {
        json_string string;
        json_slice slice;
    };
    json_cow_str_kind kind;
} json_cow_str;

json_slice json_cow_str_as_slice(const json_cow_str *cow);

json_slice json_string_as_slice(const json_string *string);

size_t json_slice_len(const json_slice *slice);

bool json_slice_eq(const json_slice *s1, const json_slice *s2);

bool json_slice_eq_str(const json_slice *slice, const char *string);

// written 在成功和空间不足时都返回完整内容长度（不含 NUL）。
json_error_code json_slice_write_to_buf(const json_slice *slice, char *buf, size_t len, size_t *written);

void json_free_string(const json_allocator *allocator, json_string *string);

void json_free_cow_str(const json_allocator *allocator, json_cow_str *cow);

json_error_code json_slice_to_owned_string(const json_allocator *allocator, const json_slice *from,
                                           json_string *to);

void json_cow_str_borrow(const json_slice *slice, json_cow_str *cow);

void json_cow_str_borrow_mut(char *ptr, size_t len, size_t cap, json_cow_str *cow);

// 消费 cow；成功时 out 获得 allocator 所管理的 NUL 结尾字符串。
json_error_code json_cow_str_into_owned_c_str(const json_allocator *allocator, json_cow_str *cow, char **out);

json_error_code json_str_unescape(const json_allocator *allocator, const json_slice *from, json_string *to,
                                  size_t *error_offset);

#ifdef __cplusplus
}
#endif

#endif
