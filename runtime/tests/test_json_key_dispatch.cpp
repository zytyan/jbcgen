#include "json_key_dispatch.h"

#include "gtest/gtest.h"

#include <cstring>

namespace {

json_slice slice(const char *text)
{
    return {text, std::strlen(text)};
}

TEST(JsonKeyDispatchTest, ReturnsIdForMatchingSlice)
{
    const json_key_entry entries[] = {
        {slice("id"), 7},
        {slice("display-name"), 11},
    };
    const json_key_map map{entries, 2};
    json_slice key = slice("display-name");
    uint32_t id = 0;
    ASSERT_TRUE(json_key_dispatch(&map, &key, &id));
    EXPECT_EQ(id, 11U);
}

TEST(JsonKeyDispatchTest, MissLeavesIdUnchanged)
{
    const json_key_entry entries[] = {{slice("id"), 7}};
    const json_key_map map{entries, 1};
    json_slice key = slice("unknown");
    uint32_t id = 99;
    EXPECT_FALSE(json_key_dispatch(&map, &key, &id));
    EXPECT_EQ(id, 99U);
}

TEST(JsonKeyDispatchTest, RejectsInvalidArguments)
{
    json_slice key = slice("id");
    uint32_t id = 0;
    EXPECT_FALSE(json_key_dispatch(nullptr, &key, &id));
    const json_key_map empty{nullptr, 0};
    EXPECT_FALSE(json_key_dispatch(&empty, nullptr, &id));
    EXPECT_FALSE(json_key_dispatch(&empty, &key, nullptr));
}

} // namespace
