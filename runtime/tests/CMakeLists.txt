cmake_minimum_required(VERSION 3.14)

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
        ${GENERATED_SOURCE}
)

set_source_files_properties(${GENERATED_SOURCE} PROPERTIES GENERATED TRUE)

add_executable(
    json_reflect_tests
    ${JSON_REFLECT_TEST_SOURCES}
)
add_dependencies(json_reflect_tests generate_example_json)

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
if(NOT ENABLE_SANITIZERS)
    gtest_discover_tests(json_reflect_tests)
endif()

add_test(
    NAME json_reflect_tests
    COMMAND json_reflect_tests
)

if(UNIX AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    add_executable(
        json_allocator_contract_test
        test_allocator_contract.c
        ${GENERATED_SOURCE}
    )
    add_dependencies(json_allocator_contract_test generate_example_json)
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

if(ENABLE_SANITIZERS)
    set(SANITIZER_TESTS json_reflect_tests)
    if(TARGET json_allocator_contract_test)
        list(APPEND SANITIZER_TESTS json_allocator_contract_test)
    endif()

    if(ENABLE_LSAN_CHECKS)
        set_tests_properties(${SANITIZER_TESTS} PROPERTIES
            ENVIRONMENT "ASAN_OPTIONS=detect_leaks=1;LSAN_OPTIONS=detect_leaks=1"
        )
    else()
        set_tests_properties(${SANITIZER_TESTS} PROPERTIES
            ENVIRONMENT "ASAN_OPTIONS=detect_leaks=0;LSAN_OPTIONS=detect_leaks=0"
        )
    endif()
endif()
