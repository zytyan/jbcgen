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
                  ▼
            GeneratePlan
             ├── C decoder
             └── C cleanup
```

Clang frontend 负责 typedef 展开以及基础类型、enum、record、指针和数组的结构化解析。传入 Schema Builder 的字段和函数签名已经是不可变的 `AstType` 树；Schema 层不再解析 `qualType` 字符串。

`Schema` 是唯一语义来源，直接保存 type、record、field、function、稳定 ID、JSON key、required、flatten、约束、数组布局、所有权和 `omitempty`。注解词汇表是内建静态定义，不提供外部 Schema 插件接口。

`GeneratePlan` 是唯一生成计划。每个 `TypePlan` 同时保存 decode/release helper、字段路径、排序后的 key 表、类型依赖及失败回滚目标；类型和约束仍引用 Schema，不复制。Schema 和 GeneratePlan 均能打印确定性调试文本；打印结果不能反向解析，也不承诺跨版本兼容。

## CLI

```text
annotation-parser INPUT.h -o OUTPUT.c \
  [--clang CLANG] [--include HEADER] \
  [--dump-ir schema|plan|all] \
  [-- <clang 参数>...]
```

开发目录中可直接运行：

```sh
PYTHONPATH=src python3 -m annotation_parser ../example/example.h \
  -o example_json.c --include example/example.h -- -I ../runtime
```

生成失败时不会覆盖已有输出文件。Clang 和注解错误包含文件、行、列。

## 注解

- `@jsonStruct`：将结构体映射为 JSON 对象，并允许作为公开生成入口。
- `@jsonStruct(asarray, elems=elems, len=len, cap=cap)`：将结构体本身映射为 JSON 数组。
- `@jsonDecode`：标记 `bool function(json_parser *, T *)` 声明。
- `@jsonCleanup`：标记 `void function(json_allocator *, T *)` 声明。
- `@json(...)`：设置字段行为。

字段参数：

- `key=name`：主 JSON key。
- `altkey=name`：别名，可重复；任一别名与主键共享重复检测和 required 状态。
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
- array-record 使用一个 TypePlan 同时描述解码、释放和失败回滚；调试打印会显示存储字段及计数来源。

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
- 未知字段跳过，重复已知字段报错，缺失的非 required 字段保持零值。
- required key 缺失与 required 值为 null 使用不同的结构化错误码。
- 非 required 的 `char *`、动态数组和结构体指针接受 null，且不分配。
- 动态数组使用延迟分配；`null` 和 `[]` 均保持 `NULL + 0`，只有第一个元素出现后才申请容量。
- 数组容器同样延迟申请元素缓冲区；根或值类型遇到 `null` 是类型错误，非 required 指针可接受 `null`，required 指针的 `null` 使用 required-null 错误。
- cap-only 资源元素容器按容量 cleanup；生成器依赖 `json_any_vec` 将未使用槽位置零，从而安全重复释放。
- 空 JSON 字符串分配一个 NUL 字节，以区别于 null。
- `char *` 与 `char[N]` 拒绝嵌入 NUL；字符串长度按解码后的 UTF-8 字节计算。
- 失败时调用同一 TypePlan 的 release helper 深度回滚并清零；cleanup 可重复调用。

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

Runtime 的 CMake 测试会生成、编译并执行 `example/example.h` 对应的 decoder。
