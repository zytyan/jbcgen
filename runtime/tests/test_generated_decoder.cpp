#include "example/example.h"
#include "gtest/gtest.h"

#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>

namespace {

size_t allocation_count;
size_t free_count;
size_t allocation_limit;

void *tracking_malloc(size_t size)
{
    if (allocation_count >= allocation_limit) {
        return nullptr;
    }
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
        allocation_limit = std::numeric_limits<size_t>::max();
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

TEST_F(GeneratedDecoderTest, ArrayRecordEmptyAndNullNeverAllocate)
{
    IntVec values{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, slice("[]"));
    ASSERT_TRUE(decodeIntVec(&parser, &values));
    EXPECT_EQ(values.elems, nullptr);
    EXPECT_EQ(values.len, 0U);
    EXPECT_EQ(values.cap, 0U);
    EXPECT_EQ(values.reserved, 0U);
    EXPECT_EQ(allocation_count, 0U);

    parser = {};
    values = {};
    json_parser_init(&parser, &allocator, slice("null"));
    EXPECT_FALSE(decodeIntVec(&parser, &values));
    EXPECT_EQ(parser.error.code, JSON_ERROR_TYPE_MISMATCH);
    EXPECT_EQ(allocation_count, 0U);
    EXPECT_EQ(values.elems, nullptr);
}

TEST_F(GeneratedDecoderTest, ArrayRecordStoresLengthAndActualCapacity)
{
    IntVec values{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, slice("[10,20]"));
    ASSERT_TRUE(decodeIntVec(&parser, &values));
    ASSERT_NE(values.elems, nullptr);
    EXPECT_EQ(values.len, 2U);
    EXPECT_EQ(values.cap, 16U / sizeof(i32));
    EXPECT_EQ(values.elems[0], 10);
    EXPECT_EQ(values.elems[1], 20);
    EXPECT_EQ(values.reserved, 0U);
    releaseIntVec(&allocator, &values);
    releaseIntVec(&allocator, &values);
    EXPECT_EQ(allocation_count, 1U);
    EXPECT_EQ(free_count, 1U);
    EXPECT_EQ(values.elems, nullptr);
}

TEST_F(GeneratedDecoderTest, LenOnlyAndElemsOnlyArrayRecordsDecode)
{
    NarrowIntVec with_len{};
    BareIntVec bare{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, slice("[3,4]"));
    ASSERT_TRUE(decodeNarrowIntVec(&parser, &with_len));
    ASSERT_NE(with_len.elems, nullptr);
    EXPECT_EQ(with_len.len, 2U);

    parser = {};
    json_parser_init(&parser, &allocator, slice("[7]"));
    ASSERT_TRUE(decodeBareIntVec(&parser, &bare));
    ASSERT_NE(bare.elems, nullptr);
    EXPECT_EQ(bare.elems[0], 7);

    releaseNarrowIntVec(&allocator, &with_len);
    releaseBareIntVec(&allocator, &bare);
    EXPECT_EQ(allocation_count, free_count);
}

TEST_F(GeneratedDecoderTest, CapOnlyResourceElementsUseZeroedSpareSlots)
{
    StringSlots values{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, slice(R"(["first"])"));
    ASSERT_TRUE(decodeStringSlots(&parser, &values));
    ASSERT_NE(values.elems, nullptr);
    ASSERT_EQ(values.cap, 16U / sizeof(char *));
    ASSERT_GE(values.cap, 1U);
    EXPECT_STREQ(values.elems[0], "first");
    for (size_t index = 1; index < values.cap; ++index) {
        EXPECT_EQ(values.elems[index], nullptr);
    }
    releaseStringSlots(&allocator, &values);
    releaseStringSlots(&allocator, &values);
    EXPECT_EQ(allocation_count, free_count);
    EXPECT_EQ(values.elems, nullptr);
}

TEST_F(GeneratedDecoderTest, ArrayRecordPointerNullAndRequiredRules)
{
    VecEnvelope envelope{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, slice(R"({"optional":null,"required":[]})"));
    ASSERT_TRUE(decodeVecEnvelope(&parser, &envelope));
    EXPECT_EQ(envelope.optional, nullptr);
    ASSERT_NE(envelope.required, nullptr);
    EXPECT_EQ(envelope.required->elems, nullptr);
    EXPECT_EQ(envelope.required->len, 0U);
    EXPECT_EQ(envelope.required->cap, 0U);
    EXPECT_EQ(allocation_count, 1U);
    releaseVecEnvelope(&allocator, &envelope);
    EXPECT_EQ(allocation_count, free_count);

    parser = {};
    envelope = {};
    allocation_count = 0;
    free_count = 0;
    json_parser_init(&parser, &allocator, slice(R"({"required":null})"));
    EXPECT_FALSE(decodeVecEnvelope(&parser, &envelope));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_NULL_REQUIRED_VALUE);
    EXPECT_EQ(allocation_count, 0U);

    parser = {};
    envelope = {};
    json_parser_init(&parser, &allocator, slice("{}"));
    EXPECT_FALSE(decodeVecEnvelope(&parser, &envelope));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_MISSING_REQUIRED_KEY);
    EXPECT_EQ(allocation_count, 0U);
}

TEST_F(GeneratedDecoderTest, ArrayRecordElementFailureRollsBackCurrentSlot)
{
    StringSlots values{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, slice(R"(["first",1])"));
    EXPECT_FALSE(decodeStringSlots(&parser, &values));
    EXPECT_EQ(parser.error.code, JSON_ERROR_TYPE_MISMATCH);
    EXPECT_EQ(values.elems, nullptr);
    EXPECT_EQ(values.cap, 0U);
    EXPECT_EQ(allocation_count, free_count);
}

TEST_F(GeneratedDecoderTest, ArrayRecordAllocatorFailureRollsBack)
{
    StringSlots values{};
    json_parser parser{};
    allocation_limit = 1;
    json_parser_init(&parser, &allocator, slice(R"(["first"])"));
    EXPECT_FALSE(decodeStringSlots(&parser, &values));
    EXPECT_EQ(parser.error.code, JSON_ERROR_OTHER_NO_MEMORY);
    EXPECT_EQ(values.elems, nullptr);
    EXPECT_EQ(values.cap, 0U);
    EXPECT_EQ(allocation_count, 1U);
    EXPECT_EQ(free_count, 1U);
}

TEST_F(GeneratedDecoderTest, NarrowLengthOverflowReportsArrayRangeAndRollsBack)
{
    std::string input = "[";
    for (int index = 0; index < 256; ++index) {
        if (index != 0) input += ',';
        input += '0';
    }
    input += ']';

    NarrowIntVec values{};
    json_parser parser{};
    json_parser_init(&parser, &allocator, {input.data(), input.data() + input.size()});
    EXPECT_FALSE(decodeNarrowIntVec(&parser, &values));
    EXPECT_EQ(parser.error.code, JSON_ERROR_RANGE_ARRAY_LENGTH);
    EXPECT_EQ(values.elems, nullptr);
    EXPECT_EQ(values.len, 0U);
    EXPECT_EQ(allocation_count, free_count);
}

}  // namespace
