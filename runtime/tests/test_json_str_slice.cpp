#include "json_str_slice.h"

#include "gtest/gtest.h"

#include <cstdlib>
#include <cstring>
#include <string>

namespace {

size_t allocations;
size_t frees;
bool fail_allocations;

void *tracked_malloc(size_t size)
{
    if (fail_allocations) {
        return nullptr;
    }
    ++allocations;
    return std::malloc(size);
}

void tracked_free(void *ptr)
{
    if (ptr != nullptr) {
        ++frees;
    }
    std::free(ptr);
}

json_slice slice(const char *text)
{
    return {text, std::strlen(text)};
}

class JsonStringTest : public ::testing::Test {
  protected:
    json_allocator allocator{tracked_malloc, tracked_free};

    void SetUp() override
    {
        allocations = 0;
        frees = 0;
        fail_allocations = false;
    }
};

TEST_F(JsonStringTest, SliceEqualityUsesExplicitLength)
{
    json_slice hello = slice("hello");
    const char embedded_data[] = {'h', 'e', '\0', 'l', 'o'};
    json_slice embedded{embedded_data, sizeof(embedded_data)};
    json_slice same{hello.ptr, hello.len};
    EXPECT_TRUE(json_slice_eq(&hello, &same));
    EXPECT_TRUE(json_slice_eq_str(&hello, "hello"));
    EXPECT_FALSE(json_slice_eq(&hello, &embedded));
    EXPECT_FALSE(json_slice_eq_str(&embedded, "he"));
}

TEST_F(JsonStringTest, OwnedStringHasPointerLengthAndCapacity)
{
    json_slice input = slice("hello");
    json_string string{};
    ASSERT_EQ(json_slice_to_owned_string(&allocator, &input, &string), JSON_ERROR_NONE);
    EXPECT_STREQ(string.ptr, "hello");
    EXPECT_EQ(string.len, 5U);
    EXPECT_EQ(string.cap, 6U);
    json_slice view = json_string_as_slice(&string);
    EXPECT_TRUE(json_slice_eq(&view, &input));
    json_free_string(&allocator, &string);
    EXPECT_EQ(string.ptr, nullptr);
    EXPECT_EQ(frees, 1U);
}

TEST_F(JsonStringTest, EmptyOwnedStringStillOwnsTerminator)
{
    json_slice input{nullptr, 0};
    json_string string{};
    ASSERT_EQ(json_slice_to_owned_string(&allocator, &input, &string), JSON_ERROR_NONE);
    ASSERT_NE(string.ptr, nullptr);
    EXPECT_EQ(string.ptr[0], '\0');
    EXPECT_EQ(string.len, 0U);
    EXPECT_EQ(string.cap, 1U);
    json_free_string(&allocator, &string);
}

TEST_F(JsonStringTest, CowDistinguishesOwnedAndBorrowedStorage)
{
    const char literal[] = "borrowed";
    json_slice input = slice(literal);
    json_cow_str cow{};
    json_cow_str_borrow(&input, &cow);
    EXPECT_EQ(cow.kind, JSON_COW_CONST_BORROWED_SLICE);
    EXPECT_EQ(json_cow_str_as_slice(&cow).ptr, literal);
    json_free_cow_str(&allocator, &cow);
    EXPECT_EQ(frees, 0U);

    json_string owned{};
    ASSERT_EQ(json_slice_to_owned_string(&allocator, &input, &owned), JSON_ERROR_NONE);
    cow.string = owned;
    cow.kind = JSON_COW_OWNED_STRING;
    json_slice owned_view = json_cow_str_as_slice(&cow);
    EXPECT_TRUE(json_slice_eq(&owned_view, &input));
    json_free_cow_str(&allocator, &cow);
    EXPECT_EQ(frees, 1U);
}

TEST_F(JsonStringTest, CowToCStringMovesOwnedAndCopiesBorrowed)
{
    json_slice input = slice("hello");
    json_string owned{};
    ASSERT_EQ(json_slice_to_owned_string(&allocator, &input, &owned), JSON_ERROR_NONE);
    char *original = owned.ptr;
    json_cow_str cow{};
    cow.string = owned;
    cow.kind = JSON_COW_OWNED_STRING;
    char *result = nullptr;
    ASSERT_EQ(json_cow_str_into_owned_c_str(&allocator, &cow, &result), JSON_ERROR_NONE);
    EXPECT_EQ(result, original);
    EXPECT_STREQ(result, "hello");
    allocator.free(result);

    json_cow_str_borrow(&input, &cow);
    result = nullptr;
    ASSERT_EQ(json_cow_str_into_owned_c_str(&allocator, &cow, &result), JSON_ERROR_NONE);
    EXPECT_NE(result, input.ptr);
    EXPECT_STREQ(result, "hello");
    allocator.free(result);
}

TEST_F(JsonStringTest, MutableBorrowIsNeverFreedOrMoved)
{
    char buffer[16] = "hello";
    json_cow_str cow{};
    json_cow_str_borrow_mut(buffer, 5, sizeof(buffer), &cow);
    EXPECT_EQ(cow.kind, JSON_COW_MUT_BORROWED_STRING);
    char *result = nullptr;
    ASSERT_EQ(json_cow_str_into_owned_c_str(&allocator, &cow, &result), JSON_ERROR_NONE);
    EXPECT_NE(result, buffer);
    EXPECT_STREQ(result, "hello");
    EXPECT_EQ(frees, 0U);
    allocator.free(result);
}

TEST_F(JsonStringTest, UnescapesUnicodeIntoOwnedString)
{
    json_slice input = slice("hello\\n\\u4e2d\\ud83d\\ude05");
    json_string output{};
    size_t error_offset = 99;
    ASSERT_EQ(json_str_unescape(&allocator, &input, &output, &error_offset), JSON_ERROR_NONE);
    EXPECT_EQ(std::string(output.ptr, output.len), "hello\n中😅");
    EXPECT_EQ(error_offset, 0U);
    json_free_string(&allocator, &output);
}

TEST_F(JsonStringTest, UnescapeReportsErrorAndAllocationFailure)
{
    json_slice invalid = slice("\\x");
    json_string output{};
    size_t offset = 0;
    EXPECT_EQ(json_str_unescape(&allocator, &invalid, &output, &offset), JSON_ERROR_ESCAPE_INVALID_SEQUENCE);
    EXPECT_EQ(offset, 1U);
    EXPECT_EQ(output.ptr, nullptr);

    fail_allocations = true;
    json_slice valid = slice("text");
    EXPECT_EQ(json_str_unescape(&allocator, &valid, &output, &offset), JSON_ERROR_OTHER_NO_MEMORY);
    EXPECT_EQ(output.ptr, nullptr);
}

} // namespace
