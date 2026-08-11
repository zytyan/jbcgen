cmake_minimum_required(VERSION 3.14)

if(JSON_REFLECT_SANITIZER_FLAGS)
    add_compile_options(
        ${JSON_REFLECT_SANITIZER_FLAGS}
        -fno-omit-frame-pointer
        -g
    )
endif()

# Test source files
set(JSON_REFLECT_TEST_SOURCES
        test_json_tokenizer.cpp
        test_json_pull.cpp
        test_json_reflect.cpp
        test_json_decode_string.cpp
        test_json_key_dispatch.cpp
        test_json_str_slice.cpp
        test_generated_decoder.cpp
        tracking_allocator.cpp
)

add_executable(
    json_reflect_tests
    ${JSON_REFLECT_TEST_SOURCES}
)

json_reflect_generate(
    TARGET json_reflect_tests
    HEADER "${JBCGEN_ROOT}/example/example.h"
    OUTPUT "${GENERATED_SOURCE}"
    INCLUDE "example/example.h"
    CLANG_ARGS -I "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

target_link_libraries(
    json_reflect_tests
    PRIVATE
    GTest::gtest_main
    json_reflect_api
)

target_include_directories(json_reflect_tests PRIVATE
    ${GENERATED_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../..
)

include(GoogleTest)
if(NOT JSON_REFLECT_ENABLE_ASAN AND NOT JSON_REFLECT_ENABLE_UBSAN)
    gtest_discover_tests(json_reflect_tests)
endif()

add_test(
    NAME json_reflect_tests
    COMMAND json_reflect_tests
)

add_executable(json_reflect_basic_types_test test_json_reflect_basic_types.c)
target_link_libraries(json_reflect_basic_types_test PRIVATE json_reflect_api)
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(json_reflect_basic_types_test PRIVATE -fshort-enums)
endif()
add_test(NAME json_reflect_basic_types_test COMMAND json_reflect_basic_types_test)

if(UNIX AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    add_executable(json_reflect_abi_mismatch_test test_json_reflect_abi_mismatch.c)
    target_link_libraries(json_reflect_abi_mismatch_test PRIVATE json_reflect_api)
    target_compile_options(json_reflect_abi_mismatch_test PRIVATE
        -fpack-struct=1
        -funsigned-char
    )
    add_test(NAME json_reflect_abi_mismatch_test COMMAND json_reflect_abi_mismatch_test)
endif()

if(UNIX AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    add_executable(
        json_allocator_contract_test
        test_allocator_contract.c
        ${GENERATED_SOURCE}
    )
    target_link_libraries(json_allocator_contract_test PRIVATE json_reflect_api)
    target_include_directories(json_allocator_contract_test PRIVATE
        ${GENERATED_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/../..
    )
    target_compile_options(json_allocator_contract_test PRIVATE
        -fno-builtin-malloc
        -fno-builtin-calloc
        -fno-builtin-realloc
        -fno-builtin-free
        -fno-builtin-aligned-alloc
    )
    target_link_options(json_allocator_contract_test PRIVATE
        -Wl,--wrap=malloc
        -Wl,--wrap=calloc
        -Wl,--wrap=realloc
        -Wl,--wrap=free
        -Wl,--wrap=aligned_alloc
    )
    add_test(NAME json_allocator_contract_test COMMAND json_allocator_contract_test)
endif()

if(JSON_REFLECT_ENABLE_ASAN OR JSON_REFLECT_ENABLE_UBSAN)
    set(SANITIZER_TESTS json_reflect_tests json_reflect_basic_types_test)
    if(TARGET json_reflect_abi_mismatch_test)
        list(APPEND SANITIZER_TESTS json_reflect_abi_mismatch_test)
    endif()
    if(TARGET json_allocator_contract_test)
        list(APPEND SANITIZER_TESTS json_allocator_contract_test)
    endif()

    set(SANITIZER_TEST_ENVIRONMENT)
    if(JSON_REFLECT_ENABLE_ASAN)
        if(JSON_REFLECT_ENABLE_LSAN_CHECKS)
            list(APPEND SANITIZER_TEST_ENVIRONMENT
                "ASAN_OPTIONS=detect_leaks=1"
                "LSAN_OPTIONS=detect_leaks=1"
            )
        else()
            list(APPEND SANITIZER_TEST_ENVIRONMENT
                "ASAN_OPTIONS=detect_leaks=0"
                "LSAN_OPTIONS=detect_leaks=0"
            )
        endif()
    endif()
    if(JSON_REFLECT_ENABLE_UBSAN)
        list(APPEND SANITIZER_TEST_ENVIRONMENT
            "UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1"
        )
    endif()
    set_tests_properties(${SANITIZER_TESTS} PROPERTIES
        ENVIRONMENT "${SANITIZER_TEST_ENVIRONMENT}"
    )
endif()
