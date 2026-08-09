#ifndef JSON_STR_SLICE
#define JSON_STR_SLICE

#include <stddef.h>
#include <stdbool.h>
#include "json_allocator.h"
#include "json_error.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct json_str_slice {
    const char *begin;
    const char *end;
} json_str_slice;

typedef struct json_string {
    json_str_slice text;
    const char *tail;
    void *owner;
    bool writable;
} json_string;

size_t json_slice_len(const json_str_slice *s);

bool json_slice_eq(const json_str_slice *s1, const json_str_slice *s2);

bool json_slice_eq_str(const json_str_slice *s1, const char *s2);

// written 在成功和空间不足时都返回完整内容长度（不含 NUL）
json_error_code json_slice_write_to_buf(const json_str_slice *s, char *buf, size_t len, size_t *written);

void json_free_string(const json_allocator *allocator, json_string *str);

json_error_code json_slice_to_owned_string(const json_allocator *allocator, const json_str_slice *from, json_string *to);

void json_string_borrow(const json_str_slice *slice, json_string *str);

json_error_code json_string_into_owned_c_str(const json_allocator *allocator, json_string *str, char **out);

json_error_code json_str_unescape(const json_allocator *allocator, const json_str_slice *from, json_string *to,
                                  size_t *error_offset);

#ifdef __cplusplus
}
#endif

#endif
