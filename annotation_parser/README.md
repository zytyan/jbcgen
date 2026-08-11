# annotation-parser

`annotation-parser` 从 C 头文件、Clang JSON AST 和文档注释生成 C11 JSON decoder 与 cleanup 实现。

## 数据流

```text
Clang JSON AST + documentation comments
               │
               ▼
  structured frontend AST (`AstType` tree)
               │
               ▼
               Schema
                  │
          `validate_schema`
                  │
                  ▼
            GeneratePlan
                  │
                  ▼
       C reflection descriptors
                  │
                  ▼
       generic decode / release
```

Clang frontend 负责 typedef 展开以及基础类型、enum、record、指针和数组的结构化解析。传入 Schema Builder 的字段和函数签名已经是不可变的 `AstType` 树；Schema 层不再解析 `qualType` 字符串。

`Schema` 是唯一语义来源，直接保存 type、record、field、function、稳定 ID、JSON key、required、flatten、约束、数组布局、所有权和 `omitempty`。注解词汇表是内建静态定义，不提供外部 Schema 插件接口。

validator 在构建前检查注解命令和参数词汇表；`SchemaBuilder` 负责构造类型图、解析引用、建立数组布局并派生所有权；独立的 `validate_schema()` 在完整 Schema 上检查 constraints、计数字段、binding/key 冲突和 ownership 组合。无法形成结构化 Schema 的错误（例如未知 C 类型或缺失引用字段）仍由 Builder 就地报告。

`GeneratePlan` 是唯一生成计划。每个 `TypePlan` 保存描述符名称、字段路径、排序后的 key 表、物理资源字段和类型依赖；类型和约束仍引用 Schema，不复制。Schema 和 GeneratePlan 均能打印确定性调试文本；打印结果不能反向解析，也不承诺跨版本兼容。

C generator 使用 5 个固定完整模板，生成 `static const` 类型、record、field、key、storage 和 array-layout 描述表，以及公开 decode/cleanup 的薄包装函数。key entry 只包含 key 和 field ID，按 UTF-8 `(len, memcmp)` 排序后由 runtime 二分查找。通用对象/数组控制流、required、约束、失败回滚与 cleanup 都位于 `json_reflect.c`；生成代码不包含逐字段 callback。

描述符中的偏移和大小使用 C 的 `offsetof` 与 `sizeof`，不固化 Clang 计算出的数字。`json_reflect_basic_types.h/.c` 为每种 C 基本类型提供唯一的只读描述符；基础字段通过 `JSON_REFLECT_BASIC_TYPE(真实字段表达式)` 触发 C11 `_Generic`，typedef 自动匹配兼容基础类型。Schema ID 同样区分 `int`、`long` 和 `long long`，不会因为 LP64 下位宽一致而合并。enum 保留明确的 enum kind 和底层基础整数类型。生成代码不再重复定义基础类型描述符。JSON binding 字段表与物理 storage 表分离，因此 flatten 和 alias 不会造成重复释放。描述符是生成代码与 runtime 之间的内部接口，不承诺第三方 ABI 稳定性。

Runtime 的标量便利函数按基本类型命名：`json_decode_bool`、`json_decode_char`、`json_decode_signed_char`、`json_decode_unsigned_char`、`json_decode_short`、`json_decode_unsigned_short`、`json_decode_int`、`json_decode_unsigned_int`、`json_decode_long`、`json_decode_unsigned_long`、`json_decode_long_long`、`json_decode_unsigned_long_long`、`json_decode_float` 和 `json_decode_double`。旧的按位宽函数不再提供。

生成的每个类型描述符都带有 ABI 版本、`sizeof(json_reflect_type)` 和编译环境指纹，并通过公开 wrapper 引用 `json_reflect_abi_v1`。指纹覆盖 reflection、parser、error、string 和 key-map 公开结构布局以及 plain `char` signedness；runtime 会在解码前拒绝不兼容描述符。共享库 SONAME 主版本为 `1`。生成目标必须与 runtime 和实际使用用户结构体的目标共享 packing、char signedness、target ABI 和控制结构体定义的宏；这些选项不一致属于不支持的构建。

## CLI

```text
annotation-parser INPUT.h -o OUTPUT.c \
  [--clang CLANG] [-c PATH] [--include HEADER] \
  [--dump-ir schema|plan|all] \
  [-- <clang 参数>...]
```

`-c/--compile-commands` 接受 `compile_commands.json` 文件或其所在目录。精确匹配输入文件时使用对应条目；处理通常不在数据库中的头文件时，选择目录最近的 translation unit，同名 stem 优先。编译器、输入文件、`-c`、依赖生成和输出参数会被剔除，其余参数在数据库记录的 `directory` 下传给 Clang。`--` 后的参数最后追加，可覆盖数据库中的设置。

开发目录中可直接运行：

```sh
PYTHONPATH=src python3 -m annotation_parser ../example/example.h \
  -o example_json.c --include example/example.h -- -I ../runtime
```

生成文件头记录来源头文件及其内容的 SHA-256。生成结果与已有文件相同时不会重写文件；生成失败时也不会覆盖已有输出。Clang 和注解错误包含文件、行、列。

## 集成现有项目

生成的 `.c` 文件需要与输入头文件一起编译，并链接仓库 `runtime` 提供的 CMake 目标 `json_reflect_api`。推荐在项目中开启 `CMAKE_EXPORT_COMPILE_COMMANDS`，通过 `add_custom_command(OUTPUT ...)` 调用 generator，并把输入头文件和 `annotation_parser/src/annotation_parser/*.py` 都列入 `DEPENDS`。

完整、可直接复制的 CMake 示例以及运行期调用示例见仓库根目录 [README.md](../README.md#集成已有-cmake-项目)。

## 注解

- `@jsonStruct`：将结构体映射为 JSON 对象，并允许作为公开生成入口。
- `@jsonStruct(asarray, elems=elems, len=len, cap=cap)`：将结构体本身映射为 JSON 数组。
- `@jsonDecode`：标记 `bool function(json_parser *, T *)` 声明。
- `@jsonCleanup`：标记 `void function(json_allocator *, T *)` 声明。
- `@json(...)`：设置字段行为。

字段参数：

- `key=name`：主 JSON key。
- `altkey=name`：别名，可重复；任一别名与主键共享 required 状态。
- `required`：key 必须出现且值不能为 null；`{}`、`[]` 和空字符串合法。
- `min`、`max`：含边界数值限制。
- `minlen`、`maxlen`：解码后字符串字节数或数组元素数限制。
- `type=array, len=countField`：将 `T *` 解释为动态数组。
- `len=countField`：为固定数组保存实际元素数。
- `flatten`：将值结构体字段展开到父对象；不能与 `required` 组合。
- `omitempty`：保存在字段 Schema 中，当前 decoder 不使用。

未知参数、重复的单值参数、不适用的参数组合和 JSON key 冲突都会在生成期报错。动态数组的伴随长度字段不作为独立 JSON key。

### 数组容器结构体

```c
/// @jsonStruct(asarray, elems=elems, len=len, cap=cap)
typedef struct {
    Elem *elems;
    size_t len;
    size_t cap;
    int reserved; /* ignored，始终保持零值 */
} ElemVec;
```

- `asarray` 和 `elems=<field>` 必须同时出现；`len`、`cap` 可分别省略。
- `elems` 必须是非 `void` 指针。`len`、`cap` 若存在，必须是互不相同的无符号整数字段；写入前按字段位宽检查溢出。
- `cap` 保存 `json_any_vec.byte_cap / sizeof(Elem)`，即实际可用元素容量，不是 JSON 元素数。
- 未被 `elems`、`len`、`cap` 引用的字段不参与解码和 cleanup，并保持零值。
- 没有 `len` 和 `cap` 时，元素类型必须无需逐元素释放。
- 具名结构体和匿名 typedef 均支持。数组形状的结构体不能用于 `flatten`。
- array-record 使用同一个类型描述符驱动解码、释放和失败回滚；调试打印会显示存储字段及计数来源。

## 支持的 C 类型

- `_Bool` / `bool`
- LP64 下的有符号和无符号基础整数及 typedef
- `float`、`double`
- 数值 enum
- `char *`、`char[N]`
- 固定 `T[N]`
- 值结构体、结构体指针和递归指针
- 带 `len` 的动态 `T *` 数组
- 使用 `@jsonStruct(asarray, ...)` 的结构体级数组容器

暂不支持 union、位域、函数指针、柔性或零长 C 数组。

## 解码与所有权

- 调用 decode 前，输出对象必须全零；重复使用前先 cleanup。
- 含 required 字段的对象通过 `json_allocator` 临时申请字段出现状态，并在所有成功或失败出口释放；不使用 VLA。
- 未知字段跳过；重复已知字段采用最后一个值，覆盖前会先释放旧资源；缺失的非 required 字段保持零值。
- required key 缺失与 required 值为 null 使用不同的结构化错误码。
- 非 required 的 `char *`、动态数组和结构体指针接受 null，且不分配。
- 动态数组使用延迟分配；`null` 和 `[]` 均保持 `NULL + 0`，只有第一个元素出现后才申请容量。
- 数组容器同样延迟申请元素缓冲区；根或值类型遇到 `null` 是类型错误，非 required 指针可接受 `null`，required 指针的 `null` 使用 required-null 错误。
- cap-only 资源元素容器按容量 cleanup；生成器依赖 `json_any_vec` 将未使用槽位置零，从而安全重复释放。
- 空 JSON 字符串分配一个 NUL 字节，以区别于 null。
- `char *` 与 `char[N]` 拒绝嵌入 NUL；字符串长度按解码后的 UTF-8 字节计算。
- 失败时调用通用 reflection release 深度回滚并清零；cleanup 可重复调用。

## 测试

```sh
cd annotation_parser
uvx ruff==0.16.2 format --check src tests
uvx ruff==0.16.2 check src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v

cd ../runtime
cmake -S . -B build -DBUILD_TESTING=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

Runtime 的 CMake 库目标为 `json_reflect_api`。其测试会生成、编译并执行 `example/example.h` 对应的 decoder；当前不生成 encoder，也不包含 writer runtime。
