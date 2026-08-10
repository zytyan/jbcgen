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
        uint32_t id = 0;
        ASSERT_TRUE(json_key_dispatch(&map, &entries[index].key, &id));
        EXPECT_EQ(id, index + 1);
    }
}

TEST(JsonKeyDispatchTest, MissesAtLengthAndByteBoundariesLeaveIdUnchanged)
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
        uint32_t id = 99;
        EXPECT_FALSE(json_key_dispatch(&map, &key, &id));
        EXPECT_EQ(id, 99U);
    }
}

TEST(JsonKeyDispatchTest, RejectsInvalidArguments)
{
    json_slice key = slice("id");
    uint32_t id = 0;
    EXPECT_FALSE(json_key_dispatch(nullptr, &key, &id));
    const json_key_map empty{nullptr, 0};
    EXPECT_FALSE(json_key_dispatch(&empty, nullptr, &id));
    EXPECT_FALSE(json_key_dispatch(&empty, &key, nullptr));
    const json_key_map invalid{nullptr, 1};
    EXPECT_FALSE(json_key_dispatch(&invalid, &key, &id));
    const json_slice invalid_key{nullptr, 1};
    EXPECT_FALSE(json_key_dispatch(&empty, &invalid_key, &id));
}

} // namespace
