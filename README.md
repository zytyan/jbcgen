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

## 架构

Clang JSON AST 和文档注释先构建纯描述性的 Schema IR。Decode Plan 与 Release Plan 分别直接从 Schema IR 生成；C generator 再分别消费两种 Plan。未来的 Encode Plan 也将直接从 Schema IR 生成。

Python 前端和注解说明见 [annotation_parser/README.md](annotation_parser/README.md)。

## C部分

`runtime` 提供单遍扫描的 pull parser、结构化错误、字符串与动态数组辅助函数。生成的 decode 输出对象必须预先全零；失败时会回滚为全零，成功后使用对应的 cleanup 函数释放。

当前使用 Python 3.13、Clang、C11，并按 64 位 LP64 数据模型解释基础整数类型。
