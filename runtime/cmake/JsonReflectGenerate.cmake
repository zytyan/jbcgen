include_guard(GLOBAL)

set(_JSON_REFLECT_HELPER_DIR "${CMAKE_CURRENT_LIST_DIR}")

function(json_reflect_generate)
    set(options NO_COMPILE_COMMANDS)
    set(one_value_args
        TARGET
        HEADER
        OUTPUT
        INCLUDE
        COMPILE_COMMANDS
        ANNOTATION_PARSER
        CLANG
    )
    set(multi_value_args CLANG_ARGS DEPENDS)
    cmake_parse_arguments(
        JSON_REFLECT
        "${options}"
        "${one_value_args}"
        "${multi_value_args}"
        ${ARGN}
    )

    if(JSON_REFLECT_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR
            "json_reflect_generate received unknown arguments: "
            "${JSON_REFLECT_UNPARSED_ARGUMENTS}"
        )
    endif()
    foreach(required_arg TARGET HEADER OUTPUT)
        if(NOT JSON_REFLECT_${required_arg})
            message(FATAL_ERROR
                "json_reflect_generate requires ${required_arg}"
            )
        endif()
    endforeach()
    if(NOT TARGET "${JSON_REFLECT_TARGET}")
        message(FATAL_ERROR
            "json_reflect_generate target does not exist: ${JSON_REFLECT_TARGET}"
        )
    endif()
    if(NOT TARGET json_reflect_api)
        message(FATAL_ERROR
            "json_reflect_generate requires the json_reflect_api target"
        )
    endif()
    if(JSON_REFLECT_NO_COMPILE_COMMANDS AND JSON_REFLECT_COMPILE_COMMANDS)
        message(FATAL_ERROR
            "json_reflect_generate cannot combine NO_COMPILE_COMMANDS and "
            "COMPILE_COMMANDS"
        )
    endif()

    get_filename_component(
        input_header
        "${JSON_REFLECT_HEADER}"
        ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}"
    )
    get_filename_component(
        output_source
        "${JSON_REFLECT_OUTPUT}"
        ABSOLUTE
        BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}"
    )
    get_filename_component(output_directory "${output_source}" DIRECTORY)
    if(JSON_REFLECT_INCLUDE)
        set(include_spelling "${JSON_REFLECT_INCLUDE}")
    else()
        set(include_spelling "${input_header}")
    endif()

    set(compile_commands_dependency)
    if(NOT JSON_REFLECT_NO_COMPILE_COMMANDS)
        if(JSON_REFLECT_COMPILE_COMMANDS)
            get_filename_component(
                compile_commands
                "${JSON_REFLECT_COMPILE_COMMANDS}"
                ABSOLUTE
                BASE_DIR "${CMAKE_CURRENT_BINARY_DIR}"
            )
        else()
            if(NOT CMAKE_EXPORT_COMPILE_COMMANDS)
                message(FATAL_ERROR
                    "json_reflect_generate requires CMAKE_EXPORT_COMPILE_COMMANDS=ON "
                    "or NO_COMPILE_COMMANDS with explicit CLANG_ARGS"
                )
            endif()
            set(compile_commands "${CMAKE_BINARY_DIR}")
        endif()
        if(IS_DIRECTORY "${compile_commands}")
            set(compile_commands_dependency
                "${compile_commands}/compile_commands.json"
            )
        else()
            set(compile_commands_dependency "${compile_commands}")
        endif()
    endif()

    set(generator_dependencies)
    if(JSON_REFLECT_ANNOTATION_PARSER)
        set(generator_command "${JSON_REFLECT_ANNOTATION_PARSER}")
        if(EXISTS "${JSON_REFLECT_ANNOTATION_PARSER}")
            list(APPEND generator_dependencies
                "${JSON_REFLECT_ANNOTATION_PARSER}"
            )
        endif()
    else()
        get_filename_component(
            source_root
            "${_JSON_REFLECT_HELPER_DIR}/../.."
            ABSOLUTE
        )
        set(parser_source_dir "${source_root}/annotation_parser/src")
        if(EXISTS "${parser_source_dir}/annotation_parser/__main__.py")
            find_package(Python3 3.13 REQUIRED COMPONENTS Interpreter)
            set(generator_command
                "${CMAKE_COMMAND}" -E env
                "PYTHONPATH=${parser_source_dir}"
                "${Python3_EXECUTABLE}" -m annotation_parser
            )
            file(GLOB_RECURSE generator_dependencies CONFIGURE_DEPENDS
                "${parser_source_dir}/annotation_parser/*.py"
            )
        else()
            find_program(
                installed_annotation_parser
                NAMES annotation-parser
            )
            if(NOT installed_annotation_parser)
                message(FATAL_ERROR
                    "json_reflect_generate requires an installed annotation-parser "
                    "or ANNOTATION_PARSER <path>"
                )
            endif()
            set(generator_command "${installed_annotation_parser}")
            list(APPEND generator_dependencies "${installed_annotation_parser}")
        endif()
    endif()

    set(generator_args
        "${input_header}"
        -o "${output_source}"
        --include "${include_spelling}"
    )
    if(NOT JSON_REFLECT_NO_COMPILE_COMMANDS)
        list(APPEND generator_args -c "${compile_commands}")
    endif()
    if(JSON_REFLECT_CLANG)
        list(APPEND generator_args --clang "${JSON_REFLECT_CLANG}")
    endif()
    if(JSON_REFLECT_CLANG_ARGS)
        list(APPEND generator_args -- ${JSON_REFLECT_CLANG_ARGS})
    endif()

    add_custom_command(
        OUTPUT "${output_source}"
        COMMAND "${CMAKE_COMMAND}" -E make_directory "${output_directory}"
        COMMAND ${generator_command} ${generator_args}
        DEPENDS
            "${input_header}"
            ${compile_commands_dependency}
            ${generator_dependencies}
            ${JSON_REFLECT_DEPENDS}
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
        COMMAND_EXPAND_LISTS
        VERBATIM
    )
    set_source_files_properties("${output_source}" PROPERTIES GENERATED TRUE)
    target_sources("${JSON_REFLECT_TARGET}" PRIVATE "${output_source}")
    target_link_libraries("${JSON_REFLECT_TARGET}" PRIVATE json_reflect_api)
endfunction()
