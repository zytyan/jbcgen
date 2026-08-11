#include "json_key_dispatch.h"

#include "gtest/gtest.h"

#include <cstring>

namespace {

json_slice slice(const char *text)
{
    return {text, std::strlen(text)};
}

TEST(JsonKeyDispatchTest, FindsEntriesSortedByLengthThenBytes)
{
    const json_key_entry entries[] = {
        {slice(""), 1},
        {slice("a"), 2},
        {slice("b"), 3},
        {slice("aa"), 4},
        {slice("zz"), 5},
        {slice("long"), 6},
    };
    const json_key_map map{entries, 6};

    for (uint32_t index = 0; index < 6; ++index) {
        const json_key_entry *entry = json_key_dispatch(&map, &entries[index].key);
        ASSERT_EQ(entry, &entries[index]);
        EXPECT_EQ(entry->id, index + 1);
    }
}

TEST(JsonKeyDispatchTest, MissesAtLengthAndByteBoundaries)
{
    const json_key_entry entries[] = {
        {slice("a"), 1},
        {slice("c"), 2},
        {slice("aa"), 3},
        {slice("cc"), 4},
    };
    const json_key_map map{entries, 4};

    for (const char *text : {"", "b", "d", "ab", "dd", "long"}) {
        json_slice key = slice(text);
        EXPECT_EQ(json_key_dispatch(&map, &key), nullptr);
    }
}

TEST(JsonKeyDispatchTest, RejectsInvalidArguments)
{
    json_slice key = slice("id");
    EXPECT_EQ(json_key_dispatch(nullptr, &key), nullptr);
    const json_key_map empty{nullptr, 0};
    EXPECT_EQ(json_key_dispatch(&empty, nullptr), nullptr);
    const json_key_map invalid{nullptr, 1};
    EXPECT_EQ(json_key_dispatch(&invalid, &key), nullptr);
    const json_slice invalid_key{nullptr, 1};
    EXPECT_EQ(json_key_dispatch(&empty, &invalid_key), nullptr);
}

} // namespace
