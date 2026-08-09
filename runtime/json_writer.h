#ifndef JSON_WRITER_H
#define JSON_WRITER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct json_writer {
    char *buf;
    size_t size;
    size_t written;
    int indent;
    bool valid;
} json_writer;

void json_writer_init(json_writer *writer, char *buf, size_t size, int indent);

// written 始终返回实际写入 buf 的字节数；缓冲区不足时返回 false。
bool json_writer_finish(json_writer *writer, size_t *written);

bool json_writer_write_char(json_writer *writer, char value);

bool json_writer_write_raw(json_writer *writer, const char *value, size_t len);

bool json_writer_write_cstr(json_writer *writer, const char *value);

bool json_writer_write_string(json_writer *writer, const char *value);

bool json_writer_write_bool(json_writer *writer, bool value);

bool json_writer_write_i64(json_writer *writer, int64_t value);

bool json_writer_write_hex_u64(json_writer *writer, uint64_t value);

bool json_writer_write_f64(json_writer *writer, double value);

bool json_writer_newline_indent(json_writer *writer, size_t depth);

#ifdef __cplusplus
}
#endif

#endif
