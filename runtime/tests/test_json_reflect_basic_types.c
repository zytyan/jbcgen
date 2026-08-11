#include "json_reflect.h"

#include <assert.h>
#include <limits.h>

typedef unsigned long count_type;
typedef enum signed_enum {
    SIGNED_ENUM_NEGATIVE = -1,
    SIGNED_ENUM_POSITIVE = 1,
} signed_enum;

typedef struct basic_fields {
    _Bool boolean;
    char plain_char;
    signed char signed_char;
    unsigned char unsigned_char;
    short signed_short;
    unsigned short unsigned_short;
    int signed_int;
    unsigned int unsigned_int;
    long signed_long;
    count_type aliased_unsigned_long;
    long long signed_long_long;
    unsigned long long unsigned_long_long;
    float float32;
    double float64;
} basic_fields;

#define FIELD_TYPE(name) JSON_REFLECT_BASIC_TYPE(((basic_fields *)0)->name)

static const json_reflect_type *const types[] = {
    FIELD_TYPE(boolean),          FIELD_TYPE(plain_char),
    FIELD_TYPE(signed_char),      FIELD_TYPE(unsigned_char),
    FIELD_TYPE(signed_short),     FIELD_TYPE(unsigned_short),
    FIELD_TYPE(signed_int),       FIELD_TYPE(unsigned_int),
    FIELD_TYPE(signed_long),      FIELD_TYPE(aliased_unsigned_long),
    FIELD_TYPE(signed_long_long), FIELD_TYPE(unsigned_long_long),
    FIELD_TYPE(float32),          FIELD_TYPE(float64),
};

static const json_reflect_type enum_type = {
    .kind = JSON_REFLECT_ENUM,
    .basic_id = JSON_REFLECT_BASIC_ID((signed_enum){0}),
    .bits = sizeof(signed_enum) * CHAR_BIT,
    .flags = JSON_REFLECT_BASIC_SIGNED((signed_enum){0}),
    .size = sizeof(signed_enum),
};

int main(void)
{
    assert(JSON_REFLECT_ABI_CHECK());
    assert(sizeof(json_token_kind) == sizeof(uint8_t));
    assert(sizeof(json_error_code) == sizeof(uint8_t));
    assert(sizeof(json_expected_type) == sizeof(uint8_t));
    assert(sizeof(json_range_target) == sizeof(uint8_t));
    assert(sizeof(json_cow_str_kind) == sizeof(uint8_t));
    assert(types[0]->kind == JSON_REFLECT_BOOL);
    for (size_t index = 1; index <= 11; ++index) {
        assert(types[index]->kind == JSON_REFLECT_INTEGER);
    }
    assert(types[12]->kind == JSON_REFLECT_FLOAT);
    assert(types[13]->kind == JSON_REFLECT_FLOAT);

    assert(types[0] == &json_reflect_type_bool);
    assert(types[1] == &json_reflect_type_char);
    assert(types[2] == &json_reflect_type_signed_char);
    assert(types[3] == &json_reflect_type_unsigned_char);
    assert(types[6] == &json_reflect_type_int);
    assert(types[9] == &json_reflect_type_unsigned_long);
    assert(types[10] == &json_reflect_type_long_long);
    assert(types[13] == &json_reflect_type_double);

    assert(types[0]->bits == sizeof(_Bool) * CHAR_BIT);
    assert(types[1]->bits == sizeof(char) * CHAR_BIT);
    assert(types[6]->bits == sizeof(int) * CHAR_BIT);
    assert(types[9]->bits == sizeof(count_type) * CHAR_BIT);
    assert(types[13]->bits == sizeof(double) * CHAR_BIT);

    assert(types[1]->flags == (CHAR_MIN < 0 ? JSON_REFLECT_SIGNED : 0));
    assert(types[2]->flags == JSON_REFLECT_SIGNED);
    assert(types[3]->flags == 0);
    assert(types[8]->flags == JSON_REFLECT_SIGNED);
    assert(types[9]->flags == 0);
    assert(types[12]->flags == JSON_REFLECT_SIGNED);
    assert(types[1]->basic_id == JSON_REFLECT_BASIC_ID_CHAR);
    assert(types[9]->basic_id == JSON_REFLECT_BASIC_ID_UNSIGNED_LONG);
    assert(types[10]->basic_id == JSON_REFLECT_BASIC_ID_LONG_LONG);
    assert(enum_type.kind == JSON_REFLECT_ENUM);
    assert(enum_type.basic_id == JSON_REFLECT_BASIC_ID_SIGNED_CHAR);
    assert(enum_type.bits == sizeof(signed_enum) * CHAR_BIT);
    assert(enum_type.flags == JSON_REFLECT_SIGNED);
    return 0;
}
