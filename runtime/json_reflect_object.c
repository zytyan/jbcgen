#include "json_reflect_internal.h"

#include <string.h>

static bool decode_field(
    json_parser *parser,
    const json_reflect_record *record,
    const json_key_entry *entry,
    unsigned char *seen,
    json_source_location key_location,
    void *out
)
{
    const json_reflect_field *field = &record->fields[entry->id];
    if (seen[entry->id] != 0) {
        json_reflect_context_error(
            parser,
            JSON_ERROR_OTHER_DUPLICATE_KEY,
            field->primary_key,
            key_location
        );
        return false;
    }
    seen[entry->id] = 1;
    if ((field->flags & JSON_REFLECT_REQUIRED) != 0 &&
        json_peek_token(parser)->kind == JSON_TOKEN_NULL) {
        json_reflect_context_error(
            parser,
            JSON_ERROR_OTHER_NULL_REQUIRED_VALUE,
            field->primary_key,
            json_peek_token(parser)->location
        );
        return false;
    }
    void *count = field->count_type == NULL
                      ? NULL
                      : json_reflect_at(out, field->count_offset);
    return json_reflect_decode_value(
        parser,
        field->type,
        field->constraints,
        json_reflect_at(out, field->offset),
        count,
        field->count_type
    );
}

static bool decode_member(
    json_parser *parser,
    const json_reflect_record *record,
    unsigned char *seen,
    void *out
)
{
    const json_source_location key_location = json_peek_token(parser)->location;
    json_cow_str key = {0};
    if (!json_decode_string(parser, &key)) {
        return false;
    }
    if (!json_consume_colon(parser)) {
        json_free_cow_str(parser->allocator, &key);
        return false;
    }

    const json_slice slice = json_cow_str_as_slice(&key);
    const json_key_entry *entry = json_key_dispatch(&record->keys, &slice);
    json_free_cow_str(parser->allocator, &key);
    if (entry == NULL) {
        return json_skip_value(parser);
    }
    return decode_field(parser, record, entry, seen, key_location, out);
}

static bool check_required(
    json_parser *parser,
    const json_reflect_record *record,
    const unsigned char *seen,
    json_source_location object_end
)
{
    for (size_t index = 0; index < record->field_count; ++index) {
        if ((record->fields[index].flags & JSON_REFLECT_REQUIRED) != 0 &&
            seen[index] == 0) {
            json_reflect_context_error(
                parser,
                JSON_ERROR_OTHER_MISSING_REQUIRED_KEY,
                record->fields[index].primary_key,
                object_end
            );
            return false;
        }
    }
    return true;
}

bool json_reflect_decode_object(
    json_parser *parser,
    const json_reflect_type *type,
    void *out
)
{
    const json_reflect_record *record = type->record;
    unsigned char seen[record->field_count == 0 ? 1 : record->field_count];
    memset(seen, 0, sizeof(seen));
    if (!json_object_begin(parser)) {
        return false;
    }

    json_source_location object_end = json_peek_token(parser)->location;
    if (json_peek_token(parser)->kind == JSON_TOKEN_RBRACE) {
        return json_object_try_end(parser) &&
               check_required(parser, record, seen, object_end);
    }

    while (true) {
        if (!decode_member(parser, record, seen, out)) {
            return false;
        }
        if (json_peek_token(parser)->kind == JSON_TOKEN_RBRACE) {
            object_end = json_peek_token(parser)->location;
            if (!json_object_try_end(parser)) {
                return false;
            }
            break;
        }
        if (!json_consume_comma(parser)) {
            return false;
        }
    }
    return check_required(parser, record, seen, object_end);
}
