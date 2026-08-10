#include "json_str_slice.h"

#include <stdint.h>
#include <string.h>

json_slice json_string_as_slice(const json_string *string)
{
    return (json_slice){string->ptr, string->len};
}

size_t json_slice_len(const json_slice *slice)
{
    return slice->len;
}

json_slice json_cow_str_as_slice(const json_cow_str *cow)
{
    if (cow->kind == JSON_COW_CONST_BORROWED_SLICE) {
        return cow->slice;
    }
    return json_string_as_slice(&cow->string);
}

bool json_slice_eq(const json_slice *s1, const json_slice *s2)
{
    if (s1->len != s2->len) {
        return false;
    }
    return s1->len == 0 || s1->ptr == s2->ptr || memcmp(s1->ptr, s2->ptr, s1->len) == 0;
}

bool json_slice_eq_str(const json_slice *slice, const char *string)
{
    size_t len = strlen(string);
    return slice->len == len && (len == 0 || memcmp(slice->ptr, string, len) == 0);
}

json_error_code json_slice_write_to_buf(const json_slice *slice, char *buf, size_t len, size_t *written)
{
    if (written != NULL) {
        *written = slice->len;
    }
    if (slice->len == SIZE_MAX || slice->len + 1 > len) {
        if (buf != NULL && len > 0) {
            buf[0] = '\0';
        }
        return JSON_ERROR_RANGE_BUFFER_TOO_SMALL;
    }
    if (slice->len != 0) {
        memcpy(buf, slice->ptr, slice->len);
    }
    buf[slice->len] = '\0';
    return JSON_ERROR_NONE;
}

void json_free_string(const json_allocator *allocator, json_string *string)
{
    if (string->ptr != NULL) {
        allocator->free(string->ptr);
    }
    *string = (json_string){0};
}

void json_free_cow_str(const json_allocator *allocator, json_cow_str *cow)
{
    if (cow->kind == JSON_COW_OWNED_STRING && cow->string.ptr != NULL) {
        allocator->free(cow->string.ptr);
    }
    *cow = (json_cow_str){0};
}

json_error_code json_slice_to_owned_string(const json_allocator *allocator, const json_slice *from,
                                           json_string *to)
{
    if (from->len == SIZE_MAX) {
        *to = (json_string){0};
        return JSON_ERROR_RANGE_BUFFER_TOO_SMALL;
    }
    size_t cap = from->len + 1;
    char *ptr = allocator->malloc(cap);
    if (ptr == NULL) {
        *to = (json_string){0};
        return JSON_ERROR_OTHER_NO_MEMORY;
    }
    if (from->len != 0) {
        memcpy(ptr, from->ptr, from->len);
    }
    ptr[from->len] = '\0';
    *to = (json_string){ptr, from->len, cap};
    return JSON_ERROR_NONE;
}

void json_cow_str_borrow(const json_slice *slice, json_cow_str *cow)
{
    cow->slice = *slice;
    cow->kind = JSON_COW_CONST_BORROWED_SLICE;
}

void json_cow_str_borrow_mut(char *ptr, size_t len, size_t cap, json_cow_str *cow)
{
    cow->string = (json_string){ptr, len, cap};
    cow->kind = JSON_COW_MUT_BORROWED_STRING;
}

json_error_code json_cow_str_into_owned_c_str(const json_allocator *allocator, json_cow_str *cow, char **out)
{
    *out = NULL;
    json_slice slice = json_cow_str_as_slice(cow);
    if (cow->kind == JSON_COW_OWNED_STRING && cow->string.cap > cow->string.len) {
        cow->string.ptr[cow->string.len] = '\0';
        *out = cow->string.ptr;
        *cow = (json_cow_str){0};
        return JSON_ERROR_NONE;
    }
    if (slice.len == SIZE_MAX) {
        return JSON_ERROR_RANGE_BUFFER_TOO_SMALL;
    }
    char *ptr = allocator->malloc(slice.len + 1);
    if (ptr == NULL) {
        return JSON_ERROR_OTHER_NO_MEMORY;
    }
    if (slice.len != 0) {
        memcpy(ptr, slice.ptr, slice.len);
    }
    ptr[slice.len] = '\0';
    json_free_cow_str(allocator, cow);
    *out = ptr;
    return JSON_ERROR_NONE;
}

static int hex_value(char c)
{
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    if (c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    }
    return -1;
}

static json_error_code parse_hex_quad(const char **cursor, const char *end, const char **error_pos,
                                      uint32_t *out)
{
    if ((size_t)(end - *cursor) < 4) {
        *error_pos = end;
        return JSON_ERROR_ESCAPE_INVALID_UNICODE;
    }
    uint32_t value = 0;
    const char *ptr = *cursor;
    for (size_t index = 0; index < 4; ++index) {
        int digit = hex_value(*ptr++);
        if (digit < 0) {
            *error_pos = ptr - 1;
            return JSON_ERROR_ESCAPE_INVALID_UNICODE;
        }
        value = (value << 4) | (uint32_t)digit;
    }
    *cursor = ptr;
    *out = value;
    return JSON_ERROR_NONE;
}

static json_error_code append_utf8(uint32_t value, json_string *to)
{
    size_t need;
    if (value <= 0x7f) {
        need = 1;
    } else if (value <= 0x7ff) {
        need = 2;
    } else if (value <= 0xffff && !(value >= 0xd800 && value <= 0xdfff)) {
        need = 3;
    } else if (value <= 0x10ffff) {
        need = 4;
    } else {
        return JSON_ERROR_ESCAPE_INVALID_UNICODE;
    }
    if (to->cap - to->len <= need) {
        return JSON_ERROR_RANGE_BUFFER_TOO_SMALL;
    }
    unsigned char *dst = (unsigned char *)to->ptr + to->len;
    if (need == 1) {
        dst[0] = (unsigned char)value;
    } else if (need == 2) {
        dst[0] = (unsigned char)(0xc0 | (value >> 6));
        dst[1] = (unsigned char)(0x80 | (value & 0x3f));
    } else if (need == 3) {
        dst[0] = (unsigned char)(0xe0 | (value >> 12));
        dst[1] = (unsigned char)(0x80 | ((value >> 6) & 0x3f));
        dst[2] = (unsigned char)(0x80 | (value & 0x3f));
    } else {
        dst[0] = (unsigned char)(0xf0 | (value >> 18));
        dst[1] = (unsigned char)(0x80 | ((value >> 12) & 0x3f));
        dst[2] = (unsigned char)(0x80 | ((value >> 6) & 0x3f));
        dst[3] = (unsigned char)(0x80 | (value & 0x3f));
    }
    to->len += need;
    return JSON_ERROR_NONE;
}

static json_error_code append_unicode_escape(const char **cursor, const char *end, const char **error_pos,
                                             json_string *to)
{
    uint32_t value = 0;
    json_error_code code = parse_hex_quad(cursor, end, error_pos, &value);
    if (code != JSON_ERROR_NONE) {
        return code;
    }
    if (value >= 0xd800 && value <= 0xdbff) {
        const char *next = *cursor;
        if ((size_t)(end - next) < 6 || next[0] != '\\' || next[1] != 'u') {
            *error_pos = next;
            return JSON_ERROR_ESCAPE_INVALID_UNICODE;
        }
        next += 2;
        uint32_t low = 0;
        code = parse_hex_quad(&next, end, error_pos, &low);
        if (code != JSON_ERROR_NONE || low < 0xdc00 || low > 0xdfff) {
            if (code == JSON_ERROR_NONE) {
                *error_pos = next - 4;
            }
            return JSON_ERROR_ESCAPE_INVALID_UNICODE;
        }
        value = 0x10000 + ((value - 0xd800) << 10) + (low - 0xdc00);
        *cursor = next;
    } else if (value >= 0xdc00 && value <= 0xdfff) {
        *error_pos = *cursor - 4;
        return JSON_ERROR_ESCAPE_INVALID_UNICODE;
    }
    return append_utf8(value, to);
}

json_error_code json_str_unescape(const json_allocator *allocator, const json_slice *from, json_string *to,
                                  size_t *error_offset)
{
    if (error_offset != NULL) {
        *error_offset = 0;
    }
    json_free_string(allocator, to);
    if (from->len == SIZE_MAX) {
        return JSON_ERROR_RANGE_BUFFER_TOO_SMALL;
    }
    to->cap = from->len + 1;
    to->ptr = allocator->malloc(to->cap);
    if (to->ptr == NULL) {
        *to = (json_string){0};
        return JSON_ERROR_OTHER_NO_MEMORY;
    }
    to->len = 0;
    const char *cursor = from->ptr;
    const char *end = from->ptr + from->len;
    json_error_code code = JSON_ERROR_NONE;
    while (cursor < end) {
        char value = *cursor++;
        if (value != '\\') {
            to->ptr[to->len++] = value;
            continue;
        }
        if (cursor >= end) {
            code = JSON_ERROR_ESCAPE_INVALID_SEQUENCE;
            if (error_offset != NULL) {
                *error_offset = (size_t)(cursor - 1 - from->ptr);
            }
            goto fail;
        }
        value = *cursor++;
        switch (value) {
            case '"': value = '"'; break;
            case '\\': value = '\\'; break;
            case '/': value = '/'; break;
            case 'b': value = '\b'; break;
            case 'f': value = '\f'; break;
            case 'n': value = '\n'; break;
            case 'r': value = '\r'; break;
            case 't': value = '\t'; break;
            case 'u': {
                const char *error_pos = NULL;
                code = append_unicode_escape(&cursor, end, &error_pos, to);
                if (code != JSON_ERROR_NONE) {
                    if (error_offset != NULL) {
                        *error_offset = (size_t)(error_pos - from->ptr);
                    }
                    goto fail;
                }
                continue;
            }
            default:
                code = JSON_ERROR_ESCAPE_INVALID_SEQUENCE;
                if (error_offset != NULL) {
                    *error_offset = (size_t)(cursor - 1 - from->ptr);
                }
                goto fail;
        }
        to->ptr[to->len++] = value;
    }
    to->ptr[to->len] = '\0';
    return JSON_ERROR_NONE;

fail:
    json_free_string(allocator, to);
    return code;
}
