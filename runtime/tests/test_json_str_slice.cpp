#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <limits>
#include <map>
#include "gtest/gtest.h"
#include "json_str_slice.h"

static json_str_slice makeSlice(const char *str)
{
    return {str, str + strlen(str)};
}

/* 用于测试分配失败和内存泄漏检测的自定义分配器 */
struct MockAllocator {
    json_allocator base;
    int failAtAllocation;              /* 在第几次分配时失败（从1开始计数），0表示不失败 */
    int currentAllocation;             /* 当前分配计数 */
    size_t currentBytes;               /* 当前已分配的字节数 */
    size_t totalBytes;                 /* 历史累计分配的字节数（用于泄漏检测） */
    std::map<void *, size_t> allocMap; /* 记录每个指针的分配大小 */
};

/* 当前线程的 MockAllocator 指针（用于在 malloc/free 中访问） */
static thread_local MockAllocator *gCurrentMock = nullptr;

/* 实际分配器的包装函数 */
static void *realMalloc(size_t size)
{
    return malloc(size);
}

static void realFree(void *ptr)
{
    free(ptr);
}

static void *mockMalloc(size_t size)
{
    MockAllocator *mock = gCurrentMock;
    if (!mock) {
        return malloc(size);
    }
    mock->currentAllocation++;
    void *ptr = malloc(size);
    if (ptr) {
        mock->currentBytes += size;
        mock->totalBytes += size;
        mock->allocMap[ptr] = size;
    }
    return ptr;
}

static void *mockFailingMalloc(size_t size)
{
    MockAllocator *mock = gCurrentMock;
    if (!mock) {
        return malloc(size);
    }
    mock->currentAllocation++;
    if (mock->failAtAllocation == mock->currentAllocation) {
        return NULL;
    }
    void *ptr = malloc(size);
    if (ptr) {
        mock->currentBytes += size;
        mock->totalBytes += size;
        mock->allocMap[ptr] = size;
    }
    return ptr;
}

static void mockFree(void *ptr)
{
    if (!ptr) {
        return;
    }
    MockAllocator *mock = gCurrentMock;
    if (!mock) {
        free(ptr);
        return;
    }
    auto it = mock->allocMap.find(ptr);
    if (it != mock->allocMap.end()) {
        mock->currentBytes -= it->second;
        mock->allocMap.erase(it);
    }
    free(ptr);
}

static void mockInit(MockAllocator *mock, int failAtAllocation)
{
    mock->failAtAllocation = failAtAllocation;
    mock->currentAllocation = 0;
    mock->currentBytes = 0;
    mock->totalBytes = 0;
    mock->allocMap.clear();
    mock->base.malloc = mockFailingMalloc;
    mock->base.free = mockFree;
}

class JsonStrSliceTest : public ::testing::Test {
  protected:
    json_allocator allocator;

    void SetUp() override
    {
        allocator.malloc = realMalloc;
        allocator.free = realFree;
    }
};

class JsonStrSliceAllocFailTest : public ::testing::Test {
  protected:
    MockAllocator mockAllocator;

    void SetUp() override
    {
        mockInit(&mockAllocator, 0); /* 默认不失败 */
        gCurrentMock = &mockAllocator;
    }

    void TearDown() override
    {
        gCurrentMock = nullptr;
    }

    json_allocator *getAllocator()
    {
        return &mockAllocator.base;
    }

    void setFailAt(int failAtAllocation)
    {
        mockAllocator.failAtAllocation = failAtAllocation;
        mockAllocator.currentAllocation = 0;
    }
};

/* 用于内存泄漏检测的分配器 */
class JsonStrSliceLeakTest : public ::testing::Test {
  protected:
    MockAllocator leakAllocator;

    void SetUp() override
    {
        leakAllocator.failAtAllocation = 0;
        leakAllocator.currentAllocation = 0;
        leakAllocator.currentBytes = 0;
        leakAllocator.totalBytes = 0;
        leakAllocator.allocMap.clear();
        leakAllocator.base.malloc = mockMalloc;
        leakAllocator.base.free = mockFree;
        gCurrentMock = &leakAllocator;
    }

    void TearDown() override
    {
        gCurrentMock = nullptr;
    }

    json_allocator *getAllocator()
    {
        return &leakAllocator.base;
    }

    size_t getCurrentBytes() const
    {
        return leakAllocator.currentBytes;
    }
};

/* ========== json_slice_len 测试 ========== */
TEST_F(JsonStrSliceTest, SliceLen)
{
    struct {
        const char *str;
        size_t len;
    } cases[] = {
        {"", 0},
        {"a", 1},
        {"hello", 5},
        {"hello world", 11},
    };

    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        json_str_slice slice = makeSlice(cases[i].str);
        EXPECT_EQ(json_slice_len(&slice), cases[i].len) << "Input: " << cases[i].str;
    }
}

/* ========== json_slice_eq 测试 ========== */
TEST_F(JsonStrSliceTest, SliceEq)
{
    /* 相同指针 */
    const char *str = "hello";
    json_str_slice s1 = makeSlice(str);
    json_str_slice s2 = makeSlice(str);
    EXPECT_TRUE(json_slice_eq(&s1, &s2));

    /* 相同内容不同指针 */
    json_str_slice s3 = makeSlice("hello");
    char *s4_data = strdup("hello");
    json_str_slice s4 = makeSlice(s4_data);
    EXPECT_TRUE(json_slice_eq(&s3, &s4));
    free(s4_data);

    /* 不同内容 */
    json_str_slice s5 = makeSlice("hello");
    json_str_slice s6 = makeSlice("world");
    EXPECT_FALSE(json_slice_eq(&s5, &s6));

    /* 不同长度 */
    json_str_slice s7 = makeSlice("hello");
    char *s8_data = strdup("hell");
    json_str_slice s8 = makeSlice(s8_data);
    EXPECT_FALSE(json_slice_eq(&s7, &s8));
    free(s8_data);

    /* 空字符串 */
    json_str_slice s9 = makeSlice("");
    json_str_slice s10 = makeSlice("");
    EXPECT_TRUE(json_slice_eq(&s9, &s10));
}

/* ========== json_slice_eq_str 测试 ========== */
TEST_F(JsonStrSliceTest, SliceEqStr)
{
    json_str_slice slice = makeSlice("hello");

    EXPECT_TRUE(json_slice_eq_str(&slice, "hello"));
    EXPECT_FALSE(json_slice_eq_str(&slice, "hello world"));
    EXPECT_FALSE(json_slice_eq_str(&slice, "world"));
    EXPECT_FALSE(json_slice_eq_str(&slice, "hell"));
    EXPECT_FALSE(json_slice_eq_str(&slice, ""));
}

/* ========== json_slice_write_to_buf 测试 ========== */
TEST_F(JsonStrSliceTest, SliceWriteToBuf)
{
    char buf[256];

    /* 正常写入 */
    json_str_slice slice = makeSlice("hello");
    size_t written = 0;
    EXPECT_EQ(json_slice_write_to_buf(&slice, buf, sizeof(buf), &written), JSON_ERROR_NONE);
    EXPECT_EQ(written, 5u);
    EXPECT_STREQ(buf, "hello");

    /* 缓冲区太小 */
    json_str_slice slice2 = makeSlice("hello");
    EXPECT_EQ(json_slice_write_to_buf(&slice2, buf, 3, &written), JSON_ERROR_RANGE_BUFFER_TOO_SMALL);
    EXPECT_EQ(written, 5u);

    /* 刚好够大 */
    json_str_slice slice3 = makeSlice("hi");
    EXPECT_EQ(json_slice_write_to_buf(&slice3, buf, 3, &written), JSON_ERROR_NONE);
    EXPECT_EQ(written, 2u);
    EXPECT_STREQ(buf, "hi");

    /* 空字符串 */
    json_str_slice slice4 = makeSlice("");
    EXPECT_EQ(json_slice_write_to_buf(&slice4, buf, sizeof(buf), &written), JSON_ERROR_NONE);
    EXPECT_EQ(written, 0u);
    EXPECT_STREQ(buf, "");
}

/* ========== json_string_borrow 测试 ========== */
TEST_F(JsonStrSliceTest, StringBorrowFromSlice)
{
    const char *original = "hello world";
    json_str_slice slice = makeSlice(original);
    json_string str;

    json_string_borrow(&slice, &str);

    EXPECT_EQ(str.text.begin, original);
    EXPECT_EQ(str.text.end, original + strlen(original));
    EXPECT_EQ(str.tail, original + strlen(original));
    EXPECT_EQ(str.owner, nullptr);
}

/* ========== json_slice_to_owned_string 测试 ========== */
TEST_F(JsonStrSliceTest, SliceToOwnedString)
{
    json_str_slice slice = makeSlice("hello");
    json_string str;
    json_error_code result = json_slice_to_owned_string(&allocator, &slice, &str);

    EXPECT_EQ(result, JSON_ERROR_NONE);
    EXPECT_STREQ(str.text.begin, "hello");
    EXPECT_EQ(json_slice_len(&str.text), 5);
    EXPECT_NE(str.owner, nullptr);
    EXPECT_EQ(str.owner, str.text.begin);

    json_free_string(&allocator, &str);
}

TEST_F(JsonStrSliceAllocFailTest, SliceToOwnedStringAllocFail)
{
    json_str_slice slice = makeSlice("hello");
    json_string str;

    /* 第1次分配失败 */
    setFailAt(1);
    json_error_code result = json_slice_to_owned_string(getAllocator(), &slice, &str);
    EXPECT_EQ(result, JSON_ERROR_OTHER_NO_MEMORY);
}

TEST_F(JsonStrSliceTest, SliceToOwnedStringEmpty)
{
    json_str_slice slice = makeSlice("");
    json_string str;
    json_error_code result = json_slice_to_owned_string(&allocator, &slice, &str);

    EXPECT_EQ(result, JSON_ERROR_NONE);
    EXPECT_EQ(json_slice_len(&str.text), 0);
    EXPECT_NE(str.owner, nullptr);

    json_free_string(&allocator, &str);
}

/* ========== json_free_string 测试 ========== */
TEST_F(JsonStrSliceTest, FreeString)
{
    json_str_slice slice = makeSlice("hello");
    json_string str;
    json_error_code result = json_slice_to_owned_string(&allocator, &slice, &str);
    ASSERT_EQ(result, JSON_ERROR_NONE);
    json_free_string(&allocator, &str);
    EXPECT_EQ(str.text.begin, nullptr);
    EXPECT_EQ(str.text.end, nullptr);
    EXPECT_EQ(str.tail, nullptr);
    EXPECT_EQ(str.owner, nullptr);
}

TEST_F(JsonStrSliceTest, FreeStringNoOwner)
{
    /* borrowed string 的 free 是安全的 */
    const char *original = "hello";
    json_str_slice slice = makeSlice(original);
    json_string str;
    json_string_borrow(&slice, &str);

    json_free_string(&allocator, &str); /* 不应该崩溃 */
}

/* ========== json_string_into_owned_c_str 测试 ========== */
TEST_F(JsonStrSliceTest, StringIntoOwnedCStr)
{
    /* 测试 owned 字符串且有足够空间 */
    json_str_slice slice = makeSlice("hello");
    json_string str;
    json_error_code result = json_slice_to_owned_string(&allocator, &slice, &str);
    ASSERT_EQ(result, JSON_ERROR_NONE);

    /* 确保有空间放nul */
    str.tail = (const char *)str.owner + 10; /* 扩大tail以确保有空间 */

    char *cstr = nullptr;
    EXPECT_EQ(json_string_into_owned_c_str(&allocator, &str, &cstr), JSON_ERROR_NONE);
    EXPECT_NE(cstr, nullptr);
    EXPECT_STREQ(cstr, "hello");
    free((void *)cstr);
}

TEST_F(JsonStrSliceTest, StringIntoOwnedCStrNeedAlloc)
{
    /* 测试需要重新分配的情况（borrowed string） */
    const char *original = "hello";
    json_str_slice slice = makeSlice(original);
    json_string str;
    json_string_borrow(&slice, &str);

    char *cstr = nullptr;
    EXPECT_EQ(json_string_into_owned_c_str(&allocator, &str, &cstr), JSON_ERROR_NONE);
    EXPECT_NE(cstr, nullptr);
    EXPECT_STREQ(cstr, "hello");
    EXPECT_NE(cstr, original); /* 应该是新分配的 */
    free((void *)cstr);
}

TEST_F(JsonStrSliceAllocFailTest, StringIntoOwnedCStrAllocFail)
{
    /* borrowed string 情况下的分配失败 */
    const char *original = "hello";
    json_str_slice slice = makeSlice(original);
    json_string str;
    json_string_borrow(&slice, &str);

    setFailAt(1);
    char *cstr = nullptr;
    json_error_code code = json_string_into_owned_c_str(getAllocator(), &str, &cstr);
    EXPECT_EQ(code, JSON_ERROR_OTHER_NO_MEMORY);
    EXPECT_EQ(cstr, nullptr);
}

/* ========== json_str_unescape 测试 ========== */
TEST_F(JsonStrSliceTest, UnescapeReturnsStructuredCodes)
{
    json_string result{};
    size_t error_offset = 99;
    json_str_slice valid = makeSlice("hello\\n\\u4e2d");
    EXPECT_EQ(json_str_unescape(&allocator, &valid, &result, &error_offset), JSON_ERROR_NONE);
    EXPECT_TRUE(json_slice_eq_str(&result.text, "hello\n中"));
    json_free_string(&allocator, &result);

    json_str_slice invalid_escape = makeSlice("\\x");
    EXPECT_EQ(json_str_unescape(&allocator, &invalid_escape, &result, &error_offset),
              JSON_ERROR_ESCAPE_INVALID_SEQUENCE);
    EXPECT_EQ(error_offset, 1u);
    EXPECT_EQ(result.owner, nullptr);

    json_str_slice invalid_unicode = makeSlice("\\u12G4");
    EXPECT_EQ(json_str_unescape(&allocator, &invalid_unicode, &result, &error_offset),
              JSON_ERROR_ESCAPE_INVALID_UNICODE);
    EXPECT_EQ(error_offset, 4u);
    EXPECT_EQ(result.owner, nullptr);
}

TEST_F(JsonStrSliceAllocFailTest, UnescapeAllocationFailure)
{
    json_string result{};
    json_str_slice input = makeSlice("\\n");
    size_t error_offset = 0;
    setFailAt(1);
    EXPECT_EQ(json_str_unescape(getAllocator(), &input, &result, &error_offset), JSON_ERROR_OTHER_NO_MEMORY);
    EXPECT_EQ(result.owner, nullptr);
}

/* ========== 边界条件测试 ========== */
TEST_F(JsonStrSliceTest, EmptySlice)
{
    json_str_slice slice = {nullptr, nullptr};
    EXPECT_EQ(json_slice_len(&slice), 0);

    json_str_slice slice2 = makeSlice("");
    EXPECT_EQ(json_slice_len(&slice2), 0);
}

TEST_F(JsonStrSliceTest, ZeroTerminated)
{
    /* 确保处理中间有\0的情况 */
    const char data[] = "hello\0world";
    json_str_slice slice = {data, data + 10}; /* 不包括末尾的\0 */

    EXPECT_EQ(json_slice_len(&slice), 10);

    /* json_slice_eq_str 会处理 */
    EXPECT_FALSE(json_slice_eq_str(&slice, "hello"));
}

/* ========== 内存泄漏检测测试 ========== */

TEST_F(JsonStrSliceLeakTest, SliceToOwnedStringNoLeak)
{
    json_str_slice slice = makeSlice("hello");
    json_string str;
    json_error_code result = json_slice_to_owned_string(getAllocator(), &slice, &str);

    EXPECT_EQ(result, JSON_ERROR_NONE);
    size_t bytesAfterAlloc = getCurrentBytes();
    EXPECT_GT(bytesAfterAlloc, 0); /* 确认有内存分配 */

    json_free_string(getAllocator(), &str);

    EXPECT_EQ(getCurrentBytes(), 0) << "Memory leak detected after json_free_string";
}

TEST_F(JsonStrSliceLeakTest, SliceToOwnedStringWithLeak)
{
    json_str_slice slice = makeSlice("hello");
    json_string str;
    json_error_code result = json_slice_to_owned_string(getAllocator(), &slice, &str);

    EXPECT_EQ(result, JSON_ERROR_NONE);
    size_t bytesAfterAlloc = getCurrentBytes();
    EXPECT_GT(bytesAfterAlloc, 0); /* 确认有内存分配 */

    EXPECT_EQ(getCurrentBytes(), bytesAfterAlloc) << "Memory should still be allocated (leaked)";
    json_free_string(getAllocator(), &str);
    EXPECT_EQ(getCurrentBytes(), 0);
}

TEST_F(JsonStrSliceLeakTest, BorrowedStringNoLeak)
{
    /* borrowed string 不分配内存 */
    const char *original = "hello";
    json_str_slice slice = makeSlice(original);
    json_string str;
    json_string_borrow(&slice, &str);

    size_t bytesBefore = getCurrentBytes();
    json_free_string(getAllocator(), &str);
    size_t bytesAfter = getCurrentBytes();

    EXPECT_EQ(bytesBefore, bytesAfter) << "Borrowed string should not allocate memory";
}

TEST_F(JsonStrSliceLeakTest, MultipleAllocationsNoLeak)
{
    /* 多次分配后全部释放，无泄漏 */
    const char *inputs[] = {"hello", "world", "test", "json"};
    json_string strings[4];

    for (size_t i = 0; i < 4; i++) {
        json_str_slice slice = makeSlice(inputs[i]);
        json_error_code result = json_slice_to_owned_string(getAllocator(), &slice, &strings[i]);
        EXPECT_EQ(result, JSON_ERROR_NONE);
    }

    EXPECT_GT(getCurrentBytes(), 0); /* 确认有内存分配 */

    for (size_t i = 0; i < 4; i++) {
        json_free_string(getAllocator(), &strings[i]);
    }

    EXPECT_EQ(getCurrentBytes(), 0) << "Memory leak after multiple allocations";
}

TEST_F(JsonStrSliceLeakTest, MultipleAllocationsWithPartialLeak)
{
    /* 多次分配，部分释放，检测泄漏 */
    const char *inputs[] = {"hello", "world", "test"};
    json_string strings[3];

    for (size_t i = 0; i < 3; i++) {
        json_str_slice slice = makeSlice(inputs[i]);
        json_error_code result = json_slice_to_owned_string(getAllocator(), &slice, &strings[i]);
        EXPECT_EQ(result, JSON_ERROR_NONE);
    }

    size_t bytesAfterAlloc = getCurrentBytes();
    EXPECT_GT(bytesAfterAlloc, 0);

    /* 只释放第一个 */
    json_free_string(getAllocator(), &strings[0]);

    size_t bytesAfterPartialFree = getCurrentBytes();
    EXPECT_LT(bytesAfterPartialFree, bytesAfterAlloc);
    EXPECT_GT(bytesAfterPartialFree, 0); /* 还有2个未释放 */

    EXPECT_EQ(getCurrentBytes(), bytesAfterPartialFree) << "Remaining allocations should still exist";
    json_free_string(getAllocator(), &strings[1]);
    json_free_string(getAllocator(), &strings[2]);
    EXPECT_EQ(getCurrentBytes(), 0);
}
