#include "json_reflect.h"

#include <assert.h>

static const json_reflect_type foreign_type = {
    JSON_REFLECT_TYPE_ABI_INIT,
    .kind = JSON_REFLECT_INTEGER,
    .basic_id = JSON_REFLECT_BASIC_ID_INT,
    .bits = sizeof(int) * CHAR_BIT,
    .flags = JSON_REFLECT_SIGNED,
    .size = sizeof(int),
};

int main(void)
{
    assert(json_reflect_abi_guard(&json_reflect_abi_v1));
    assert(!json_reflect_type_abi_compatible(&foreign_type));
    return 0;
}
