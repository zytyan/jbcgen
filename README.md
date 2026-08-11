# jbcgen

`jbcgen` 从 C 类型声明和文档注释生成 C11 JSON 反射描述符、decoder 包装函数和 cleanup 包装函数。生成代码把类型布局描述为 `static const` 数据，通用解码、释放和失败回滚由 `json_reflect_api` runtime 执行。

当前只实现 JSON decode/release，不提供 encoder 或 writer。

## 依赖与安装

- Python 3.13
- Clang
- CMake 3.14 及以上
- C11 编译器
- 64 位 LP64 数据模型

从源码运行 generator：

```sh
cd annotation_parser
PYTHONPATH=src python3 -m annotation_parser --help
```

也可以安装 Python 命令：

```sh
python3.13 -m pip install ./annotation_parser
annotation-parser --help
```

Runtime 目前没有安装规则，推荐把本仓库作为 CMake 子目录引入，目标名为 `json_reflect_api`。

共享库构建使用 ABI 主版本 `1`。生成代码通过宏引用版本化符号
`json_reflect_check_abi_v1`，因此 ABI 主版本不匹配会在链接时失败；公开 wrapper
同时将本编译单元根据基本类型宽度/对齐、公开结构布局和 plain `char` signedness 计算出的 64 位指纹
传给 runtime，不匹配时解码返回 `JSON_ERROR_OTHER_ABI_MISMATCH`，cleanup 安全跳过。
ABI 信息只检查一次，不存入每个类型描述符。runtime、生成的
reflection `.c` 和使用用户结构体的目标必须使用相同的 target ABI、packing、
`-fsigned-char`/`-funsigned-char` 及影响头文件布局的宏。所有公开枚举使用固定
宽度存储，不受 `-fshort-enums` 影响。

## 最小示例

在公开头文件中包含 `json_pull.h`，并使用文档注释声明 JSON 行为：

```c
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "json_pull.h"

typedef struct Address {
    char city[64];
} Address;

/// @jsonStruct
typedef struct User {
    /// @json(key=id, altkey=user-id, required)
    uint32_t id;

    /// @json(maxlen=100)
    char *name;

    /// @json(type=array, len=address_count)
    Address *addresses;
    size_t address_count;
} User;

/// @jsonDecode
bool decode_user(json_parser *parser, User *out);

/// @jsonCleanup
void cleanup_user(json_allocator *allocator, User *value);
```

生成 C 文件：

```sh
PYTHONPATH=annotation_parser/src python3 -m annotation_parser \
  include/my_project/user.h \
  -o generated/user_json.c \
  --include my_project/user.h \
  -- -I runtime -I include
```

`--include` 是生成 C 文件中使用的头文件拼写。上例会生成：

```c
#include "my_project/user.h"
```

在程序中调用：

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "my_project/user.h"

int read_user(const char *text)
{
    json_allocator allocator = {malloc, free};
    json_slice input = {text, strlen(text)};
    json_parser parser;
    User user = {0};

    json_parser_init(&parser, &allocator, input);
    if (!decode_user(&parser, &user)) {
        fprintf(stderr, "JSON error %d at %zu:%zu\n",
                (int)parser.error.code,
                parser.error.location.line,
                parser.error.location.column);
        return 0;
    }

    /* 使用 user。 */
    cleanup_user(&allocator, &user);
    return 1;
}
```

`json_estimate_error_msg_len()` 和 `json_fmt_error()` 可以将结构化错误格式化为文本。传给 `json_fmt_error()` 的缓冲区至少需要 `json_estimate_error_msg_len() + 1` 字节。

## CLI

```text
annotation-parser INPUT.h -o OUTPUT.c \
  [--clang CLANG] [-c PATH] [--include HEADER] \
  [--dump-ir schema|plan|all] \
  [-- <clang 参数>...]
```

| 参数 | 作用 |
| --- | --- |
| `INPUT.h` | 带注解的输入头文件 |
| `-o, --output` | 生成的 C 源文件，必需 |
| `--include` | 生成文件中包含输入头文件时使用的拼写；默认使用输入路径 |
| `--clang` | 实际运行的 Clang 可执行文件，默认 `clang` |
| `-c, --compile-commands` | `compile_commands.json` 文件或其所在目录 |
| `--dump-ir` | 将 Schema、GeneratePlan 或两者打印到 stderr |
| `--` | 后续参数原样追加到 Clang 参数末尾 |

生成文件头包含来源头文件路径和内容 SHA-256。生成内容未变化时不会重写输出文件；生成失败也不会覆盖已有输出。

### 使用 compile_commands.json

```sh
annotation-parser include/my_project/user.h \
  -o generated/user_json.c \
  --include my_project/user.h \
  -c build \
  -- -I runtime
```

Compilation database 的行为：

- 支持 `arguments` 数组和 `command` 字符串两种格式。
- 优先使用 `file` 与输入文件完全匹配的记录。
- 头文件没有记录时，选择目录距离最近的 translation unit，同名 stem 优先。
- 忽略数据库中的编译器、输入文件、输出文件、依赖生成和 `-c` 等 driver 参数。
- 相对路径按记录的 `directory` 解析。
- `--` 后的显式参数最后追加，可覆盖数据库中的 `-D`、`-std`、`-x` 等设置。
- 实际编译器由 `--clang` 决定，不使用数据库记录中的 compiler。

如果自动选择的 translation unit 不代表目标头文件的编译环境，应在 `--` 后显式补充或覆盖参数。

## 注解

注解必须位于 Clang 能识别的文档注释中，例如 `///` 或 `/** ... */`。字段支持尾随 `/// @json(...)`。未知命令、未知参数、非法重复参数及不适用的组合会在生成期报告文件、行和列。

### 声明级注解

| 注解 | 作用 |
| --- | --- |
| `@jsonStruct` | 将结构体映射为 JSON 对象，并允许作为公开 decode 根类型 |
| `@jsonStruct(asarray, elems=..., len=..., cap=...)` | 将结构体映射为 JSON 数组容器；`len`、`cap` 可省略 |
| `@jsonDecode` | 标记 `bool function(json_parser *, T *)` |
| `@jsonCleanup` | 标记 `void function(json_allocator *, T *)` |

每个公开 `@jsonDecode` 目标必须有对应的 `@jsonCleanup`。公开目标类型必须带 `@jsonStruct`；未标记结构体仍可作为可达的嵌套值、指针目标或 flatten 类型。

### 字段级 `@json(...)`

| 参数 | 作用 |
| --- | --- |
| `key=name` | 指定主 JSON key；默认使用 C 字段名 |
| `altkey=name` | 指定别名，可重复；主键和所有别名命中同一字段 |
| `required` | key 必须出现且值不能为 `null` |
| `min=value`, `max=value` | 数值含边界约束 |
| `minlen=n`, `maxlen=n` | 解码后的字符串字节数或数组元素数约束 |
| `type=array, len=count` | 将非字符 `T *` 解释为动态数组，并把元素数写入 `count` |
| `len=count` | 为固定 `T[N]` 保存实际元素数 |
| `flatten` | 将值结构体的 JSON 字段展开到父对象 |
| `omitempty` | 仅保存在 Schema 中，当前 decoder 不使用 |

`required` 的主键或任一 `altkey` 出现即可满足“已提供”。值为 `{}`、`[]` 或空字符串是合法的；值为 `null` 和 key 缺失使用不同错误码。`required` 不能与 `flatten` 组合，也不能标记数组长度元数据字段。

动态数组的伴随长度字段只存储元素数，不会作为独立 JSON key 解码。

### 数组容器结构体

```c
/// @jsonStruct(asarray, elems=elems, len=len, cap=cap)
typedef struct ItemVec {
    Item *elems;
    size_t len;
    size_t cap;
    unsigned reserved;
} ItemVec;
```

- `asarray` 和 `elems=<field>` 必需。
- `elems` 必须是非 `void` 指针。
- `len`、`cap` 可独立省略；存在时必须引用互不相同的无符号整数字段。
- `len` 保存 JSON 元素数，`cap` 保存实际可用元素容量。
- 未被 `elems`、`len`、`cap` 引用的字段不参与解码或 cleanup，并保持零值。
- 同时缺少 `len` 和 `cap` 时，元素必须是不需要逐元素释放的平凡类型。
- 具名结构体和匿名 typedef 都支持；数组形状结构体不能 flatten。

## 支持的类型和 JSON 表示

| C 类型 | JSON 表示 | 说明 |
| --- | --- | --- |
| `_Bool`, `bool` | boolean | 仅接受 `true`/`false` |
| 各宽度有/无符号整数及 typedef | number 或数值字符串 | 按目标位宽检查溢出 |
| 数值 enum | number 或数值字符串 | 按 enum 底层整数存储 |
| `float`, `double` | number 或数值字符串 | `float` 写入前检查范围 |
| `char *` | string 或可选 `null` | 成功字符串以 NUL 结尾并由 allocator 持有 |
| `char[N]` | string | 最多保存 `N-1` 个解码后 UTF-8 字节 |
| `T[N]` | array | 最多接受 N 个元素，剩余位置保持零 |
| `T *` + `type=array,len=...` | array 或可选 `null` | 动态数组，延迟分配 |
| 值结构体 | object，或 array-shaped record | 可递归嵌套 |
| 结构体指针 | object/array 或可选 `null` | 确认 JSON 类型后才分配对象 |

暂不支持 union、位域、函数指针、柔性数组、C 零长数组、encoder、writer、外部 Schema 插件或 `__attribute__((annotation))`。

## 解码、分配和释放语义

- 输出对象必须全零。对已有资源的对象再次 decode 前，必须先调用 cleanup；生成的 decode 包装函数会清零输出，直接覆盖会泄漏旧资源。
- 未知 JSON 字段会递归跳过。
- 重复的已知 key（包括主键与别名的组合）采用最后一个值；覆盖前会先释放旧资源。
- 缺失的非 required 字段保持零值。
- 非 required 的 `char *`、动态数组和结构体指针接受 `null`，保持 `NULL` 且不分配。
- 动态数组和数组容器只有发现第一个元素后才分配；`null` 和 `[]` 都不申请元素缓冲区，空数组表示为 `NULL + 0`。
- 空 JSON 字符串会分配一个字节保存结尾 NUL，以区别于 `null`。
- C 字符串拒绝解码后嵌入 NUL；字符串长度按解码后的 UTF-8 字节计算。
- 所有非栈动态内存都通过调用者提供的 `json_allocator` 获取。
- decode 失败会深度释放已经构造的部分并把输出恢复为全零。
- cleanup 会深度释放并清零对象，可对零值或已经 cleanup 的对象重复调用。

## 集成已有 CMake 项目

可以只把 `runtime` 目录复制到已有项目。默认配置只构建 C11 库，不启用测试、
sanitizer，也不要求宿主提供 C++、GoogleTest 或 Python：

```cmake
add_subdirectory(third_party/json_reflect_runtime)
target_link_libraries(your_target PRIVATE json_reflect_api)
```

链接 `json_reflect_api` 会通过 `PUBLIC` include directory 自动提供 runtime 头文件。
生成器可以单独安装，也可以保留完整 jbcgen 仓库并按下面的例子从源码调用。

### 使用 CMake helper

`add_subdirectory` 会新增 `json_reflect_generate()`，但不会自动修改任何已有目标。
目标必须先创建，再调用 helper：

```cmake
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_subdirectory(third_party/jbcgen/runtime)

add_library(my_project_json STATIC)
target_include_directories(my_project_json PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
)

json_reflect_generate(
    TARGET my_project_json
    HEADER "include/my_project/user.h"
    OUTPUT "generated/user_json.c"
    INCLUDE "my_project/user.h"
)
```

helper 会创建生成命令、把输出 `.c` 加入 `my_project_json`，并让该目标链接
`json_reflect_api`。`HEADER` 相对调用处的源码目录解析，`OUTPUT` 相对调用处的
构建目录解析。默认从 `${CMAKE_BINARY_DIR}/compile_commands.json` 提取编译参数；
可以用 `COMPILE_COMMANDS` 指定其他文件或目录。

完整仓库布局下，helper 使用仓库内匹配版本的 Python generator；只复制 runtime
时，它会查找已安装的 `annotation-parser`。也可以显式指定：

```cmake
json_reflect_generate(
    TARGET my_project_json
    HEADER "include/my_project/user.h"
    OUTPUT "generated/user_json.c"
    INCLUDE "my_project/user.h"
    COMPILE_COMMANDS "${CMAKE_BINARY_DIR}"
    ANNOTATION_PARSER "/opt/jbcgen/bin/annotation-parser"
    CLANG "/opt/llvm/bin/clang"
    CLANG_ARGS -DMY_EXTRA_DEFINE=1
    DEPENDS "include/my_project/config.h"
)
```

`INCLUDE` 是写入生成 `.c` 的头文件拼写；省略时使用 `HEADER` 的绝对路径。
`CLANG_ARGS` 追加在 compilation database 参数之后，`DEPENDS` 可声明影响 AST 的
额外文件。不使用 compilation database 时可指定 `NO_COMPILE_COMMANDS`，并通过
`CLANG_ARGS` 完整提供 include、宏和 target 参数。没有安装 generator 且只复制了
runtime 时，helper 会在 CMake 配置期给出错误；不调用 helper 则完全不需要 Python
或 generator。

### 手写生成命令

原有的 `add_custom_command` 集成方式仍然可用。以下示例假设仓库布局为：

```text
your-project/
  CMakeLists.txt
  include/my_project/user.h
  src/main.c
  third_party/jbcgen/
```

可复制的 `CMakeLists.txt`：

```cmake
cmake_minimum_required(VERSION 3.14)
project(my_project LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(Python3 3.13 REQUIRED COMPONENTS Interpreter)

set(JBCGEN_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/third_party/jbcgen")
set(JSON_HEADER "${CMAKE_CURRENT_SOURCE_DIR}/include/my_project/user.h")
set(JSON_GENERATED_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated")
set(JSON_GENERATED_C "${JSON_GENERATED_DIR}/user_json.c")

add_subdirectory(
    "${JBCGEN_ROOT}/runtime"
    "${CMAKE_CURRENT_BINARY_DIR}/jbcgen-runtime"
    EXCLUDE_FROM_ALL
)

file(GLOB_RECURSE JBCGEN_PYTHON_SOURCES CONFIGURE_DEPENDS
    "${JBCGEN_ROOT}/annotation_parser/src/annotation_parser/*.py"
)

add_custom_command(
    OUTPUT "${JSON_GENERATED_C}"
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${JSON_GENERATED_DIR}"
    COMMAND "${CMAKE_COMMAND}" -E env
        "PYTHONPATH=${JBCGEN_ROOT}/annotation_parser/src"
        "${Python3_EXECUTABLE}" -m annotation_parser
        "${JSON_HEADER}"
        -o "${JSON_GENERATED_C}"
        --include "my_project/user.h"
        -c "${CMAKE_BINARY_DIR}"
        --
        -I "${JBCGEN_ROOT}/runtime"
    DEPENDS
        "${JSON_HEADER}"
        ${JBCGEN_PYTHON_SOURCES}
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    VERBATIM
)

set_source_files_properties("${JSON_GENERATED_C}" PROPERTIES GENERATED TRUE)

add_library(my_project_json STATIC "${JSON_GENERATED_C}")
target_include_directories(my_project_json PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
)
target_link_libraries(my_project_json PUBLIC json_reflect_api)

add_executable(my_app src/main.c)
target_link_libraries(my_app PRIVATE my_project_json)
```

配置并构建：

```sh
cmake -S . -B build -G Ninja
cmake --build build
```

说明：

- `CMAKE_EXPORT_COMPILE_COMMANDS` 让 generator 复用目标的宏、include、target 和语言选项。该功能通常配合 Ninja 或 Makefile generator 使用。
- `JSON_REFLECT_BUILD_TESTS` 默认关闭，因此 `add_subdirectory` 不会查找 GoogleTest、Python，也不会向宿主项目注册 runtime 测试；宿主项目自己的 `BUILD_TESTING` 不受影响。
- `DEPENDS` 同时列出输入头文件和 generator Python 源码，因此修改注解或 generator 后会重新执行。
- generator 自身会比较完整生成内容；内容相同时不会更新时间戳，避免无意义的下游重编译。
- `my_project_json` 通过 `PUBLIC` 链接 `json_reflect_api`，最终可执行文件只需链接 `my_project_json`。
- 若不使用 compilation database，可删除 `-c`，并在 `--` 后完整传入目标所需的 `-I`、`-D`、`--target` 等 Clang 参数。
- 如果已安装 `annotation-parser`，可以把 `cmake -E env ... python -m annotation_parser` 替换为 `annotation-parser` 命令，并将其可执行文件加入 `DEPENDS`。

## 架构与调试

```text
Clang JSON AST + documentation comments
               │
               ▼
       structured AstType tree
               │
               ▼
             Schema
               │
               ▼
          GeneratePlan
               │
               ▼
    C reflection descriptors
               │
               ▼
      json_reflect_api runtime
```

Clang frontend 负责把 C 类型解析为结构化 `AstType`，并保留 `int`、`long`、`long long` 等精确基础类型身份；Schema 保存类型图、JSON binding、约束、数组布局、入口函数和所有权；GeneratePlan 固定 key 的 `(UTF-8 byte length, memcmp)` 顺序和描述符布局。生成的基础字段使用 C11 `_Generic` 引用 runtime 中唯一的只读基础类型描述符，typedef 自动匹配其兼容基础类型；enum 保留 enum kind 和底层基础整数类型。Schema 与 GeneratePlan 的打印只用于调试，不是稳定序列化格式。

## 开发与测试

```sh
cd annotation_parser
ruff format --check .
ruff check .
PYTHONPATH=src python3 -m unittest discover -s tests -v

cd ../runtime
cmake -S . -B build -DJSON_REFLECT_BUILD_TESTS=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

Runtime 使用独立且默认关闭的开发选项，不读取宿主项目的同名通用选项：

```text
JSON_REFLECT_BUILD_TESTS=OFF
JSON_REFLECT_ENABLE_ASAN=OFF
JSON_REFLECT_ENABLE_UBSAN=OFF
JSON_REFLECT_ENABLE_LSAN_CHECKS=OFF
```

单独运行 ASan，并同时启用 LSan：

```sh
cmake -S runtime -B build-asan \
  -DJSON_REFLECT_BUILD_TESTS=ON \
  -DJSON_REFLECT_ENABLE_ASAN=ON \
  -DJSON_REFLECT_ENABLE_LSAN_CHECKS=ON
cmake --build build-asan
ctest --test-dir build-asan --output-on-failure
```

单独运行 UBSan：

```sh
cmake -S runtime -B build-ubsan \
  -DJSON_REFLECT_BUILD_TESTS=ON \
  -DJSON_REFLECT_ENABLE_UBSAN=ON
cmake --build build-ubsan
ctest --test-dir build-ubsan --output-on-failure
```

ASan 与 UBSan 可以分别或同时启用；LSan 依赖 ASan，不能只与 UBSan 配合。
这些选项都带 `JSON_REFLECT_` 前缀，不会因宿主项目设置 `BUILD_TESTING`、
`ENABLE_SANITIZERS` 或类似通用变量而意外启用。

完整注解和 frontend 实现说明见 [annotation_parser/README.md](annotation_parser/README.md)。
