#include "example/example.h"
#include "gtest/gtest.h"

#include <cstdlib>
#include <cstring>

namespace {

size_t allocation_count;
size_t free_count;

void *tracking_malloc(size_t size)
{
    ++allocation_count;
    return std::malloc(size);
}

void tracking_free(void *pointer)
{
    if (pointer != nullptr) {
        ++free_count;
    }
    std::free(pointer);
}

json_str_slice slice(const char *text)
{
    return {text, text + std::strlen(text)};
}

class GeneratedDecoderTest : public ::testing::Test {
  protected:
    json_allocator allocator{tracking_malloc, tracking_free};

    void SetUp() override
    {
        allocation_count = 0;
        free_count = 0;
    }

    bool decode(const char *input, User *user, json_parser *parser)
    {
        json_parser_init(parser, &allocator, slice(input));
        return decodeUser(parser, user);
    }
};

TEST_F(GeneratedDecoderTest, RequiredEmptyArrayAndObjectDoNotAllocate)
{
    User user{};
    json_parser parser{};
    ASSERT_TRUE(decode(R"({"id":1,"age":18,"bases":[],"metadata":{}})", &user, &parser));
    EXPECT_EQ(user.bases, nullptr);
    EXPECT_EQ(user.basesLen, 0U);
    EXPECT_EQ(allocation_count, 0U);
    EXPECT_EQ(json_peek_token(&parser)->kind, JSON_TOKEN_EOF);
    releaseUser(&allocator, &user);
    EXPECT_EQ(free_count, 0U);
}

TEST_F(GeneratedDecoderTest, RequiredNullAndMissingAreDistinct)
{
    User user{};
    json_parser parser{};
    EXPECT_FALSE(decode(R"({"id":1,"age":18,"bases":null,"metadata":{}})", &user, &parser));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_NULL_REQUIRED_VALUE);
    EXPECT_EQ(allocation_count, 0U);

    parser = {};
    user = {};
    EXPECT_FALSE(decode(R"({"id":1,"age":18,"bases":[]})", &user, &parser));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_MISSING_REQUIRED_KEY);
    EXPECT_EQ(allocation_count, 0U);
}

TEST_F(GeneratedDecoderTest, EmptyStringIsAllocatedAndCleanupIsRepeatable)
{
    User user{};
    json_parser parser{};
    ASSERT_TRUE(decode(R"({"id":1,"name":"","age":18,"bases":[],"metadata":{}})", &user, &parser));
    ASSERT_NE(user.name, nullptr);
    EXPECT_STREQ(user.name, "");
    EXPECT_EQ(allocation_count, 1U);
    releaseUser(&allocator, &user);
    releaseUser(&allocator, &user);
    EXPECT_EQ(free_count, 1U);
    EXPECT_EQ(user.name, nullptr);
}

TEST_F(GeneratedDecoderTest, DynamicArrayDecodesAndReleasesElements)
{
    User user{};
    json_parser parser{};
    ASSERT_TRUE(decode(
        R"({"user-id":9,"age":20,"bases":[{"id":7,"name":"city"}],"metadata":{},"accessCnt":3,"lastAccess":4,"unknown":{"x":[1]}})",
        &user, &parser));
    ASSERT_NE(user.bases, nullptr);
    ASSERT_EQ(user.basesLen, 1U);
    EXPECT_EQ(user.bases[0].id, 7);
    EXPECT_STREQ(user.bases[0].name, "city");
    EXPECT_EQ(user.data.accessCnt, 3);
    EXPECT_EQ(user.data.lastAccess, 4);
    EXPECT_EQ(allocation_count, 1U);
    releaseUser(&allocator, &user);
    EXPECT_EQ(free_count, 1U);
}

TEST_F(GeneratedDecoderTest, DuplicateAliasAndRangeFailureRollback)
{
    User user{};
    json_parser parser{};
    EXPECT_FALSE(decode(
        R"({"id":1,"user-id":2,"age":18,"bases":[],"metadata":{}})",
        &user, &parser));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_DUPLICATE_KEY);

    parser = {};
    user = {};
    allocation_count = 0;
    free_count = 0;
    EXPECT_FALSE(decode(
        R"({"id":1,"bases":[{"id":7}],"age":17,"metadata":{}})",
        &user, &parser));
    EXPECT_EQ(parser.error.code, JSON_ERROR_RANGE_NUMBER);
    EXPECT_EQ(allocation_count, 1U);
    EXPECT_EQ(free_count, 1U);
    EXPECT_EQ(user.bases, nullptr);
    EXPECT_EQ(user.basesLen, 0U);
}

}  // namespace
