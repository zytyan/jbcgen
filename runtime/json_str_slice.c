#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdint.h>
#include "json_str_slice.h"

size_t json_slice_len(const json_str_slice *s)
{
    return s->end - s->begin;
}

bool json_slice_eq(const json_str_slice *s1, const json_str_slice *s2)
{
    if (s1->begin == s2->begin && s1->end == s2->end) {
        return true;
    }
    if (json_slice_len(s1) != json_slice_len(s2)) {
        return false;
    }
    size_t len = json_slice_len(s1);
    return memcmp(s1->begin, s2->begin, len) == 0;
}

bool json_slice_eq_str(const json_str_slice *s1, const char *s2)
{
    size_t len = json_slice_len(s1);

    for (size_t i = 0; i < len; i++) {
        if (s2[i] == '\0' || s1->begin[i] != s2[i]) {
            return false;
        }
    }

    return s2[len] == '\0';
}

json_error_code json_slice_write_to_buf(const json_str_slice *s, char *buf, size_t len, size_t *written)
{
    size_t slen = json_slice_len(s);
    if (written != NULL) {
        *written = slen;
    }
    if (slen + 1 > len) {
        if (buf != NULL && len > 0) {
            buf[0] = '\0';
        }
        return JSON_ERROR_RANGE_BUFFER_TOO_SMALL;
    }
    memcpy(buf, s->begin, slen);
    buf[slen] = '\0';
    return JSON_ERROR_NONE;
}

void json_free_string(const json_allocator *allocator, json_string *str)
{
    if (str->owner) {
        allocator->free(str->owner);
    }
    *str = (json_string){0};
}

static size_t json_string_cap(const json_string *str)
{
    const char *real_begin = str->owner;
    if (!real_begin) {
        // 对于没有owner的string，是没有属于自己的空间的，所以cap是0
        return 0;
    }
    return str->tail - real_begin;
}
static json_error_code json_string_ensure_cap(const json_allocator *allocator, json_string *str, size_t cap)
{
    if (str->writable && json_string_cap(str) >= cap) {
        return JSON_ERROR_NONE;
    }
    char *new_buf = (char *)allocator->malloc(cap);
    if (!new_buf) {
        return JSON_ERROR_OTHER_NO_MEMORY;
    }
    size_t old_len = json_slice_len(&str->text);
    if (old_len == 0) {
        json_free_string(allocator, str);
        str->text.begin = new_buf;
        str->text.end = new_buf;
        str->owner = new_buf;
        str->tail = new_buf + cap;
        str->writable = true;
        return JSON_ERROR_NONE;
    }
    memcpy(new_buf, str->text.begin, old_len);
    json_free_string(allocator, str);
    str->owner = new_buf;
    str->text.begin = new_buf;
    str->text.end = new_buf + old_len;
    str->tail = new_buf + cap;
    str->writable = true;
    return JSON_ERROR_NONE;
}

static bool json_string_has_room_for_nul(const json_string *string)
{
    return string->text.end < string->tail;
}

static size_t json_owned_string_remaind_cap(const json_string *str)
{
    return str->tail - str->text.end;
}

static void json_string_reset(json_string *str)
{
    str->text.begin = str->owner;
    str->text.end = str->owner;
}

json_error_code json_slice_to_owned_string(const json_allocator *allocator, const json_str_slice *from, json_string *to)
{
    size_t len = json_slice_len(from);
    size_t buf_size = len + 1;
    char *buf = (char *)allocator->malloc(buf_size);
    if (!buf) {
        *to = (json_string){0};
        return JSON_ERROR_OTHER_NO_MEMORY;
    }
    memcpy(buf, from->begin, len);
    buf[len] = '\0';
    to->text.begin = buf;
    to->text.end = buf + len;
    to->tail = buf + buf_size;
    to->owner = buf;
    to->writable = true;
    return JSON_ERROR_NONE;
}

void json_string_borrow(const json_str_slice *slice, json_string *str)
{
    str->text.begin = slice->begin;
    str->text.end = slice->end;
    str->tail = slice->end;
    str->owner = NULL;
    str->writable = false;
}

json_error_code json_string_into_owned_c_str(const json_allocator *allocator, json_string *str, char **out)
{
    *out = NULL;
    if (str->owner && str->writable && ((const char *)str->owner) == str->text.begin &&
        json_string_has_room_for_nul(str)) {
        // 对于可以移动的值，直接移动为 C nul terminated str
        char *ret = (char *)str->text.begin;
        *(char *)str->text.end = '\0'; // 添加一个0结尾
        *str = (json_string){0};
        *out = ret;
        return JSON_ERROR_NONE;
    }
    // 对于无法移动的值，申请内存，并尝试释放原内存，以满足移动语义。
    size_t str_len = json_slice_len(&str->text);
    size_t buf_len = str_len + 1; // '\0' 结尾
    char *buf = allocator->malloc(buf_len);
    if (!buf) {
        return JSON_ERROR_OTHER_NO_MEMORY;
    }
    memcpy(buf, str->text.begin, str_len);
    buf[buf_len - 1] = '\0';
    if (str->owner) {
        allocator->free(str->owner);
    }
    *str = (json_string){0};
    *out = buf;
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

static json_error_code json_calc_hex_unicode_escape(const char **ptr, const char *end, const char **error_pos,
                                                    uint32_t *out)
{
    if (end - *ptr < 4) {
        *error_pos = end;
        return JSON_ERROR_ESCAPE_INVALID_UNICODE;
    }

    uint32_t value = 0;
    const char *p = *ptr;

    for (size_t i = 0; i < 4; i++) {
        int v = hex_value(*p++);
        if (v < 0) {
            *error_pos = p - 1;
            return JSON_ERROR_ESCAPE_INVALID_UNICODE;
        }
        value = (value << 4) | (uint32_t)v;
    }

    *ptr = p;
    *out = value;
    return JSON_ERROR_NONE;
}

static json_error_code json_write_utf8(uint32_t value, json_string *to)
{
    if (value >= 0xD800 && value <= 0xDFFF) {
        return JSON_ERROR_ESCAPE_INVALID_UNICODE;
    }
    size_t remain = json_owned_string_remaind_cap(to);

    size_t need;

    if (value <= 0x7F) {
        need = 1;
    } else if (value <= 0x7FF) {
        need = 2;
    } else if (value <= 0xFFFF) {
        need = 3;
    } else if (value <= 0x10FFFF) {
        need = 4;
    } else {
        return JSON_ERROR_ESCAPE_INVALID_UNICODE;
    }

    if (remain < need + 1) { // 保留nul
        return JSON_ERROR_RANGE_BUFFER_TOO_SMALL;
    }

    char *dst = (char *)to->text.end;

    if (need == 1) {
        *dst++ = (char)value;
    } else if (need == 2) {
        *dst++ = (char)(0xC0 | (value >> 6));
        *dst++ = (char)(0x80 | (value & 0x3F));
    } else if (need == 3) {
        *dst++ = (char)(0xE0 | (value >> 12));
        *dst++ = (char)(0x80 | ((value >> 6) & 0x3F));
        *dst++ = (char)(0x80 | (value & 0x3F));
    } else {
        *dst++ = (char)(0xF0 | (value >> 18));
        *dst++ = (char)(0x80 | ((value >> 12) & 0x3F));
        *dst++ = (char)(0x80 | ((value >> 6) & 0x3F));
        *dst++ = (char)(0x80 | (value & 0x3F));
    }

    to->text.end = dst;
    return JSON_ERROR_NONE;
}

static json_error_code json_proc_hex_unicode_escape(const char **ptr, const char *end, json_string *to,
                                                    const char **error_pos)
{
    const char *p = *ptr;
    uint32_t value = 0;
    json_error_code code = json_calc_hex_unicode_escape(&p, end, error_pos, &value);
    if (code != JSON_ERROR_NONE) {
        return code;
    }
    // high surrogate
    if (value >= 0xD800 && value <= 0xDBFF) {
        const char *next = p;
        if (end - next >= 6 && next[0] == '\\' && next[1] == 'u') {
            next += 2;
            uint32_t low = 0;
            const char *low_error = NULL;
            code = json_calc_hex_unicode_escape(&next, end, &low_error, &low);
            if (code != JSON_ERROR_NONE || low < 0xDC00 || low > 0xDFFF) {
                *error_pos = code == JSON_ERROR_NONE ? next - 4 : low_error;
                return JSON_ERROR_ESCAPE_INVALID_UNICODE;
            }
            value = 0x10000 + ((value - 0xD800) << 10) + (low - 0xDC00);
            p = next;
        } else {
            *error_pos = p;
            return JSON_ERROR_ESCAPE_INVALID_UNICODE;
        }
    }
    // 单独low surrogate非法，不过json允许悬空surrogate……什么道理
    if (value >= 0xDC00 && value <= 0xDFFF) {
        *error_pos = p - 4;
        return JSON_ERROR_ESCAPE_INVALID_UNICODE;
    }
    code = json_write_utf8(value, to);
    if (code != JSON_ERROR_NONE) {
        *error_pos = p;
        return code;
    }

    *ptr = p;
    return JSON_ERROR_NONE;
}

json_error_code json_str_unescape(const json_allocator *allocator, const json_str_slice *from, json_string *to,
                                  size_t *error_offset)
{
    size_t from_len = json_slice_len(from);
    if (error_offset != NULL) {
        *error_offset = 0;
    }
    json_string_reset(to); // 清空字符串，避免原始内容残留
    json_error_code code = json_string_ensure_cap(allocator, to, from_len + 1);
    if (code != JSON_ERROR_NONE) {
        // 保证有一个0结尾
        json_free_string(allocator, to);
        return code;
    }
    char *dst = (char *)to->text.end;
    const char *write_tail = to->tail - 1;
    const char *p = from->begin;
    while (p < from->end) {
        if (dst >= write_tail) {
            code = JSON_ERROR_RANGE_BUFFER_TOO_SMALL;
            goto fail;
        }
        char c = *p++;
        if (c != '\\') {
            *dst++ = c;
            to->text.end = dst;
            continue;
        }
        if (p >= from->end) {
            if (error_offset != NULL) {
                *error_offset = (size_t)(p - 1 - from->begin);
            }
            code = JSON_ERROR_ESCAPE_INVALID_SEQUENCE;
            goto fail;
        }
        c = *p++;
        switch (c) {
            case '"':
                *dst++ = '"';
                break;
            case '\\':
                *dst++ = '\\';
                break;
            case '/':
                *dst++ = '/';
                break;
            case 'b':
                *dst++ = '\b';
                break;
            case 'f':
                *dst++ = '\f';
                break;
            case 'n':
                *dst++ = '\n';
                break;
            case 'r':
                *dst++ = '\r';
                break;
            case 't':
                *dst++ = '\t';
                break;
            case 'u': {
                const char *error_pos = NULL;
                code = json_proc_hex_unicode_escape(&p, from->end, to, &error_pos);
                if (code != JSON_ERROR_NONE) {
                    if (error_offset != NULL) {
                        *error_offset = (size_t)(error_pos - from->begin);
                    }
                    goto fail;
                }
                dst = (char *)to->text.end;
                break;
            }
            default:
                if (error_offset != NULL) {
                    *error_offset = (size_t)(p - 1 - from->begin);
                }
                code = JSON_ERROR_ESCAPE_INVALID_SEQUENCE;
                goto fail;
        }
        to->text.end = dst;
    }
    *(char *)to->text.end = '\0';
    return JSON_ERROR_NONE;

fail:
    json_free_string(allocator, to);
    return code;
}
