#include "json_reflect.h"

#include <assert.h>

int main(void)
{
    assert(!JSON_REFLECT_ABI_CHECK());
    return 0;
}
