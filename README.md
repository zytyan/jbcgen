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

使用 `--dump-ir schema|decode|release|all` 可将只读调试文本输出到 stderr。

数组容器的 `elems` 必须指定，`len`、`cap` 可独立省略。JSON `[]` 不申请元素缓冲区，结果为 `elems == NULL` 且已有计数字段为 0；`cap` 保存实际可用元素容量。

## 架构

Clang frontend 先把 JSON AST 中的 C 类型解析为不可变的 `AstType` 树；后续层不再解析 `qualType` 字符串。Schema 分成两部分：Core 只保存 C 类型图、声明身份、稳定引用和源码位置，JSON 行为由一组强类型插件状态保存。

```text
Clang Frontend AstType
          │
          ▼
  Core Schema IR + PluginSet
          ├── Decode Plan  ── C decoder
          ├── Release Plan ── C cleanup
          └── Encode Plan  ── future
```

Decode Plan 从 Binding、Array Layout、Value Types 和 Constraints 插件构建；Release Plan 独立从 Array Layout、Value Types 和 Ownership 插件构建。两者只共享 Core 的稳定 ID，不互相包含行为节点。`omitempty` 已由 Encode Hints 插件保存，等待未来 Encode Plan 使用。

Python 前端和注解说明见 [annotation_parser/README.md](annotation_parser/README.md)。

## C部分

`runtime` 提供单遍扫描的 pull parser、结构化错误、字符串与动态数组辅助函数。生成的 decode 输出对象必须预先全零；失败时会回滚为全零，成功后使用对应的 cleanup 函数释放。

当前使用 Python 3.13、Clang、C11，并按 64 位 LP64 数据模型解释基础整数类型。

构建依赖为 Python 3.13、Clang 和 CMake；运行 C/C++ 回归测试还需要支持 C++17 的编译器与 GoogleTest。生成的 C 代码只依赖本仓库 `runtime`。
