# jbcgen Annotations

为 C 和 C++ 文档注释中的 jbcgen 注解提供语法高亮：

```c
/// @jsonStruct(asarray, elems=elems, len=len, cap=cap)
typedef struct ItemVec {
    Item *elems;
    size_t len;
    size_t cap;
} ItemVec;

/// @jsonStruct
typedef struct Item {
    int id; /// @json(key=identifier, required)
} Item;
```

当前高亮以下内容：

- `@jsonStruct`、`@jsonDecode`、`@jsonCleanup`、`@jsonEnum` 和 `@json`。
- flag、参数名、赋值符号、分隔符以及引号或裸字符串值。
- `///`、`//!`、`/** ... */` 和 `/*! ... */` 文档注释。

扩展仅包含 TextMate injection grammar，不运行 jbcgen、Python 或 Clang，也不进行语义校验。

## 本地安装

安装 VS Code Extension Manager：

```console
npm install --global @vscode/vsce
```

在本目录生成并安装 VSIX：

```console
vsce package
code --install-extension jbcgen-annotations-0.1.0.vsix
```

开发时也可以在 VS Code 中打开本目录并按 `F5`，启动 Extension Development Host。
