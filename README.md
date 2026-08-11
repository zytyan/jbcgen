# jbcgen

从 C 结构体和文档注释生成 C11 JSON 解码器与资源释放函数。


## 快速开始

头文件在结构体和函数声明上使用文档注释：

```c
/// @jsonStruct
typedef struct User {
  /// @json(key=id, altkey=user-id, required)
  uint32_t id;
  /// @json(type=array, len=itemCount)
  Item *items;
  size_t itemCount;
} User;

/// 将结构体本身映射为 JSON 数组；匿名 typedef 同样支持
/// @jsonStruct(asarray, elems=elems, len=len, cap=cap)
typedef struct {
  Item *elems;
  size_t len;
  size_t cap;
} ItemVec;

/// @jsonDecode
bool decodeUser(json_parser *parser, User *user);

/// @jsonCleanup
void releaseUser(json_allocator *allocator, User *user);
```

生成 C 源码：

```sh
cd annotation_parser
PYTHONPATH=src python3 -m annotation_parser ../example/example.h \
  -o example_json.c --include example/example.h -- -I ../runtime
```

使用 `--dump-ir schema|plan|all` 可将只读调试文本输出到 stderr。

数组容器的 `elems` 必须指定，`len`、`cap` 可独立省略。JSON `[]` 不申请元素缓冲区，结果为 `elems == NULL` 且已有计数字段为 0；`cap` 保存实际可用元素容量。

## 架构

Clang frontend 先把 JSON AST 中的 C 类型解析为不可变的 `AstType` 树；后续层不再解析 `qualType` 字符串。Schema 直接保存 C 类型图、JSON 字段语义、数组布局、约束、所有权、入口函数和源码位置。

```text
Clang Frontend AstType
          │
          ▼
          Schema
             │
      validate_schema
             │
             ▼
       GeneratePlan
         ├── C decoder
         └── C cleanup
```

每个 `TypePlan` 同时保存 decode/release helper、字段分派、类型依赖和失败回滚关系。Decode 失败调用同一 TypePlan 的 release helper，不再维护互相重复的 Decode Plan、Release Plan 或插件状态。`omitempty` 保存在字段 Schema 中，供未来 encoder 使用。

注解词汇表由 validator 在构建前检查；`SchemaBuilder` 只处理形成结构化 Schema 所需的类型解析、引用关联、数组布局和所有权派生。constraints、计数字段类型、binding/key 冲突及 ownership 组合规则由独立的 `validate_schema()` 在完整 Schema 上统一验证；`build_schema()` 只返回验证通过的结果。

生成器使用 10 个固定的完整 C 模板（文件、错误辅助、key map、对象/数组解码、字段解码、对象/数组释放和公开入口）。对象 key map 的 entry 保存 key、字段 ID 与字段 decode callback；map 按 UTF-8 字节的 `(len, memcmp)` 排序并二分查找，因此对象主 decoder 只负责控制流，各字段实现位于独立的 `decode_<Record>_field_<path>` helper 中。

Python 前端和注解说明见 [annotation_parser/README.md](annotation_parser/README.md)。

## C部分

`runtime` 提供单遍扫描的 pull parser、结构化错误、字符串与动态数组辅助函数。生成的 decode 输出对象必须预先全零；失败时会回滚为全零，成功后使用对应的 cleanup 函数释放。

当前使用 Python 3.13、Clang、C11，并按 64 位 LP64 数据模型解释基础整数类型。

构建依赖为 Python 3.13、Clang 和 CMake；运行 C/C++ 回归测试还需要支持 C++17 的编译器与 GoogleTest。生成的 C 代码只依赖本仓库 `runtime`。
