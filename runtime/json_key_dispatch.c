#include "json_key_dispatch.h"

bool json_key_dispatch(const json_key_map *map, const json_slice *key, uint32_t *id)
{
    if (map == NULL || key == NULL || id == NULL) {
        return false;
    }
    for (size_t index = 0; index < map->len; ++index) {
        if (json_slice_eq(&map->entries[index].key, key)) {
            *id = map->entries[index].id;
            return true;
        }
    }
    return false;
}
