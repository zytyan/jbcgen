#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "gtest/gtest.h"
#include "json_tokenizer.h"

class JsonTokenizerTest : public ::testing::Test {
  protected:
    json_allocator allocator;

    void SetUp() override
    {
        allocator.malloc = malloc;
        allocator.free = free;
    }

    static json_slice make_slice(const char *str)
    {
        return {str, strlen(str)};
    }
};

TEST_F(JsonTokenizerTest, ParserInit)
{
    json_parser parser;
    json_slice slice = make_slice("null");
    json_parser_init(&parser, &allocator, slice);
    EXPECT_TRUE(parser.valid);
    EXPECT_EQ(parser.current_token.kind, JSON_TOKEN_NULL);
    EXPECT_EQ(parser.error.code, JSON_ERROR_NONE);
    EXPECT_EQ(parser.current_token.location.offset, 0u);
    EXPECT_EQ(parser.current_token.location.line, 1u);
    EXPECT_EQ(parser.current_token.location.column, 1u);
}

TEST_F(JsonTokenizerTest, TracksTokenLocationsByByte)
{
    json_parser parser;
    json_parser_init(&parser, &allocator, make_slice("\"中\" null"));
    EXPECT_EQ(parser.current_token.kind, JSON_TOKEN_STRING);
    json_advance_token(&parser);
    ASSERT_EQ(parser.current_token.kind, JSON_TOKEN_NULL);
    EXPECT_EQ(parser.current_token.location.offset, 6u);
    EXPECT_EQ(parser.current_token.location.line, 1u);
    EXPECT_EQ(parser.current_token.location.column, 7u);

    json_parser_init(&parser, &allocator, make_slice("\r\n \nnull"));
    ASSERT_EQ(parser.current_token.kind, JSON_TOKEN_NULL);
    EXPECT_EQ(parser.current_token.location.offset, 4u);
    EXPECT_EQ(parser.current_token.location.line, 3u);
    EXPECT_EQ(parser.current_token.location.column, 1u);
}

TEST_F(JsonTokenizerTest, Keywords)
{
    struct {
        const char *input;
        json_token_kind kind;
    } cases[] = {
        {"null", JSON_TOKEN_NULL},
        {"true", JSON_TOKEN_TRUE},
        {"false", JSON_TOKEN_FALSE},
    };

    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        json_parser parser;
        json_parser_init(&parser, &allocator, make_slice(cases[i].input));
        EXPECT_EQ(parser.current_token.kind, cases[i].kind)
            << "Input: " << cases[i].input;
    }
}

TEST_F(JsonTokenizerTest, Numbers)
{
    struct {
        const char *input;
        json_token_kind kind;
    } cases[] = {
        {"123", JSON_TOKEN_INT},
        {"-456", JSON_TOKEN_INT},
        {"0", JSON_TOKEN_INT},
        {"3.14", JSON_TOKEN_FLOAT},
        {"1e10", JSON_TOKEN_FLOAT},
        {"-0.5", JSON_TOKEN_FLOAT},
    };

    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        json_parser parser;
        json_parser_init(&parser, &allocator, make_slice(cases[i].input));
        EXPECT_EQ(parser.current_token.kind, cases[i].kind)
            << "Input: " << cases[i].input;
    }
}

TEST_F(JsonTokenizerTest, Strings)
{
    struct {
        const char *input;
        json_token_kind kind;
    } cases[] = {
        {"\"\"", JSON_TOKEN_STRING},
        {"\"hello\"", JSON_TOKEN_STRING},
        {"\"hello world\"", JSON_TOKEN_STRING},
    };

    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        json_parser parser;
        json_parser_init(&parser, &allocator, make_slice(cases[i].input));
        EXPECT_EQ(parser.current_token.kind, cases[i].kind)
            << "Input: " << cases[i].input;
    }
}

TEST_F(JsonTokenizerTest, Punctuators)
{
    struct {
        const char *input;
        json_token_kind kind;
    } cases[] = {
        {"[", JSON_TOKEN_LBRACKET},
        {"]", JSON_TOKEN_RBRACKET},
        {"{", JSON_TOKEN_LBRACE},
        {"}", JSON_TOKEN_RBRACE},
        {":", JSON_TOKEN_COLON},
        {",", JSON_TOKEN_COMMA},
    };

    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        json_parser parser;
        json_parser_init(&parser, &allocator, make_slice(cases[i].input));
        EXPECT_EQ(parser.current_token.kind, cases[i].kind)
            << "Input: " << cases[i].input;
    }
}

TEST_F(JsonTokenizerTest, Whitespace)
{
    json_parser parser;
    json_parser_init(&parser, &allocator, make_slice("   null"));
    EXPECT_TRUE(parser.valid);
    EXPECT_EQ(parser.current_token.kind, JSON_TOKEN_NULL);
}

TEST_F(JsonTokenizerTest, AdvanceToken)
{
    json_parser parser;
    json_parser_init(&parser, &allocator, make_slice("null true"));
    EXPECT_EQ(parser.current_token.kind, JSON_TOKEN_NULL);
    json_advance_token(&parser);
    EXPECT_EQ(parser.current_token.kind, JSON_TOKEN_TRUE);
    json_advance_token(&parser);
    EXPECT_EQ(parser.current_token.kind, JSON_TOKEN_EOF);
}

TEST_F(JsonTokenizerTest, PeekToken)
{
    json_parser parser;
    json_parser_init(&parser, &allocator, make_slice("null"));
    json_token *token = json_peek_token(&parser);
    EXPECT_NE(token, nullptr);
    EXPECT_EQ(token->kind, JSON_TOKEN_NULL);
}

TEST_F(JsonTokenizerTest, Error)
{
    json_parser parser;
    json_parser_init(&parser, &allocator, make_slice("nul"));
    EXPECT_FALSE(parser.valid);
    EXPECT_EQ(parser.current_token.kind, JSON_TOKEN_ERROR);
    EXPECT_EQ(parser.error.code, JSON_ERROR_SYNTAX_INVALID_KEYWORD);
}

TEST_F(JsonTokenizerTest, ErrorTokenHasExactLocation)
{
    json_parser parser;
    json_parser_init(&parser, &allocator, make_slice("\r\n  nullx"));

    ASSERT_EQ(parser.current_token.kind, JSON_TOKEN_ERROR);
    EXPECT_EQ(parser.error.code, JSON_ERROR_SYNTAX_INVALID_KEYWORD);
    EXPECT_EQ(parser.current_token.location.offset, 8u);
    EXPECT_EQ(parser.current_token.location.line, 2u);
    EXPECT_EQ(parser.current_token.location.column, 7u);
    EXPECT_EQ(parser.error.location.offset, parser.current_token.location.offset);
}

TEST_F(JsonTokenizerTest, ReportsSyntaxErrors)
{
    struct {
        const char *input;
        json_error_code code;
    } cases[] = {
        {"@", JSON_ERROR_SYNTAX_UNKNOWN_CHARACTER},
        {"\"\x01\"", JSON_ERROR_SYNTAX_UNESCAPED_CONTROL},
        {"\"unterminated", JSON_ERROR_SYNTAX_UNTERMINATED_STRING},
        {"\"escape\\", JSON_ERROR_SYNTAX_UNTERMINATED_STRING},
    };

    for (const auto &test : cases) {
        json_parser parser;
        json_parser_init(&parser, &allocator, make_slice(test.input));
        EXPECT_FALSE(parser.valid) << test.input;
        EXPECT_EQ(parser.error.code, test.code) << test.input;
    }
}

TEST_F(JsonTokenizerTest, TokenKindNames)
{
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_NULL), "NULL");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_TRUE), "TRUE");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_FALSE), "FALSE");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_INT), "INT");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_FLOAT), "NUMBER");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_STRING), "STRING");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_ESCAPE_STRING), "ESCAPE_STRING");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_EOF), "EOF");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_ERROR), "ERROR");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_LBRACKET), "LBRACKET");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_RBRACKET), "RBRACKET");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_LBRACE), "LBRACE");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_RBRACE), "RBRACE");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_COLON), "COLON");
    EXPECT_STREQ(token_kind_name(JSON_TOKEN_COMMA), "COMMA");
}
