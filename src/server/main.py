import json
import operator
import re
from enum import Enum

import beet
import bolt
import mecha
from functools import reduce

import attrs
from pathlib import Path

from bolt import AstTargetIdentifier, AstValue, AstIdentifier
from mecha import AstNode, AstResourceLocation, AstBlock, AstSelector, AstNbtCompoundKey, AstNbtValue, AstJsonObjectKey, AstJsonValue
from pygls.lsp.server import LanguageServer
from lsprotocol.types import *
from pygls.workspace import TextDocument
from tokenstream import SourceLocation

server = LanguageServer("bolt-lsp", "v0.1")
tokens = {}


class CustomTokenTypes(Enum):
    COMMENT = "bolt-comment"
    STRING = "bolt-string"
    NUMBER = "bolt-number"
    KEYWORD = "bolt-keyword"
    FUNCTION = "bolt-function"
    BIE_TYPE = "bolt-BIEType"
    DATA_TYPE = "bolt-dataType"
    OTHER_TYPE = "bolt-otherType"
    VARIABLE = "bolt-variable"
    PARAMETER = "bolt-parameter"
    COMMAND = "bolt-command"
    DATA_GEN = "bolt-dataGen"
    MACRO = "bolt-macro"
    SELECTOR = "bolt-selector"
    NBT_KEY = "bolt-nbt-key"
    NBT_STRING = "bolt-nbt-string"
    NBT_NUMBER = "bolt-nbt-number"
    NBT_TYPE = "bolt-nbt-type"


class CustomTokenModifiers(Enum):
    TAG = "tag"
    DECLARATION = "declaration"
    DEFINITION = "definition"
    READONLY = "readonly"
    STATIC = "static"
    DEPRECATED = "deprecated"


def find_nearest_ancestor_file(start_path, target_filename):
    """
    从 start_path 开始向上查找，返回最近祖先目录中包含 target_filename 的完整文件路径。
    如果没找到返回 None。
    """
    current = Path(start_path).resolve()

    # 如果是文件，先切换到所在目录
    if current.is_file():
        current = current.parent

    # 逐级向上查找
    while current != current.parent:  # 避免无限循环，根目录时停止
        candidate = current / target_filename
        if candidate.is_file():
            return str(candidate)
        current = current.parent

    return None


@attrs.define
class Token:
    line: int
    start_col: int
    text: str
    type: CustomTokenTypes
    modifiers: set[CustomTokenModifiers] = attrs.field(factory=set)


def progress_diagnostics(ls: LanguageServer, doc: TextDocument, raw_diagnostics: mecha.diagnostic.DiagnosticCollection):
    diagnostics = []
    for exception in raw_diagnostics.exceptions:
        diagnostics.append(Diagnostic(
            range=Range(Position(exception.location.lineno - 1, exception.location.colno - 1), Position(exception.end_location.lineno - 1, exception.end_location.colno - 1)),
            message=exception.message,
            severity=DiagnosticSeverity.Error
        ))
    ls.text_document_publish_diagnostics(PublishDiagnosticsParams(doc.uri, diagnostics))


def parse(ls: LanguageServer, doc: TextDocument):
    beet_config_path = find_nearest_ancestor_file(doc.path, "beet.json")
    if beet_config_path:
        with open(beet_config_path, "r", encoding="utf-8") as f:
            raw_config = json.load(f)

        config = {
            "data_pack": raw_config["data_pack"],
            "pipeline": ["mecha"],
            "require": ["bolt"],
        }
    else:
        config = {
            "pipeline": ["mecha"],
            "require": ["bolt"],
        }
    try:
        with beet.run_beet(config) as ctx:
            mc = ctx.inject(mecha.Mecha)
            ast = mc.parse(source=doc.source)
        ls.text_document_publish_diagnostics(PublishDiagnosticsParams(doc.uri, []))
    except mecha.diagnostic.DiagnosticErrorSummary as e:
        progress_diagnostics(ls, doc, e.diagnostics)
        return
    except mecha.diagnostic.DiagnosticError as e:
        progress_diagnostics(ls, doc, e.diagnostics)
        return

    tokens[doc.uri] = []
    this_tokens = tokens[doc.uri]

    def range_text(range: tuple[SourceLocation, SourceLocation]):
        return doc.source[range[0].pos:range[1].pos]

    def add_token(range: tuple[SourceLocation, SourceLocation], type: CustomTokenTypes, modifiers: set[CustomTokenModifiers] | None = None):
        if modifiers is None:
            modifiers = set()
        text = range_text(range)
        this_tokens.append(Token(
            line=range[0].lineno - 1,
            start_col=range[0].colno - 1,
            text=text,
            type=type,
            modifiers=modifiers,
        ))
        # ls.window_log_message(LogMessageParams(type=MessageType.Info, message=f"添加标记：{text}({range[0].lineno - 1}, {range[0].colno - 1}) {type} {modifiers}"))

    def node_range(node: AstNode):
        return node.location, node.end_location

    def node_text(node: AstNode):
        return range_text(node_range(node))

    def begin_word_range(node: AstNode, word_count: int = 1):
        end_location = node.location
        for i in range(word_count):
            while range_text((end_location, end_location.with_horizontal_offset(1))) == " ":
                end_location = end_location.with_horizontal_offset(1)
            while range_text((end_location, end_location.with_horizontal_offset(1))) != " ":
                end_location = end_location.with_horizontal_offset(1)
        return node.location, end_location

    def select_word_to_skip(node: AstNode, words_list: list[list[str]]):
        end_location = node.location
        for words in words_list:
            for word in words:
                if range_text((end_location, end_location.with_horizontal_offset(len(word)))) == word:
                    end_location = end_location.with_horizontal_offset(len(word))
                    while range_text((end_location, end_location.with_horizontal_offset(1))) == " ":
                        end_location = end_location.with_horizontal_offset(1)
                    break
            else:
                return begin_word_range(node)
        return node.location, end_location

    for node in ast.walk():
        if isinstance(node, AstNode):
            identifier = getattr(node, "identifier", None)
            match node:
                case mecha.AstCommand():
                    match identifier:
                        case 'function:name:commands':
                            add_token(begin_word_range(node), CustomTokenTypes.DATA_GEN)
                            add_token(node_range(node.arguments[0]), CustomTokenTypes.FUNCTION, {CustomTokenModifiers.DEFINITION})
                        case 'say:message':
                            add_token(begin_word_range(node), CustomTokenTypes.COMMAND)
                        case 'execute:if:block:pos:block:subcommand':
                            add_token(begin_word_range(node, 2), CustomTokenTypes.COMMAND)
                        case 'if:condition:body':
                            add_token(select_word_to_skip(node, [["if"]]), CustomTokenTypes.KEYWORD)
                        case 'else:body':
                            add_token(select_word_to_skip(node, [["else"]]), CustomTokenTypes.KEYWORD)
                        case 'function:name':
                            add_token(begin_word_range(node), CustomTokenTypes.COMMAND)
                            add_token(node_range(node.arguments[0]), CustomTokenTypes.FUNCTION)
                        case 'tellraw:targets:message':
                            add_token(begin_word_range(node), CustomTokenTypes.COMMAND)
                        case 'for:target:in:iterable:body':
                            add_token(select_word_to_skip(node, [["for"]]), CustomTokenTypes.KEYWORD)
                            add_token((node.arguments[0].end_location, node.arguments[1].location), CustomTokenTypes.KEYWORD)
                        case 'predicate:name:content':
                            add_token(begin_word_range(node), CustomTokenTypes.DATA_GEN)
                            add_token(node_range(node.arguments[0]), CustomTokenTypes.DATA_TYPE, {CustomTokenModifiers.DEFINITION})
                case AstBlock():
                    match identifier:
                        case AstResourceLocation():
                            if identifier.is_tag:
                                add_token(node_range(node), CustomTokenTypes.BIE_TYPE, {CustomTokenModifiers.TAG})
                            else:
                                add_token(node_range(node), CustomTokenTypes.BIE_TYPE)
                case mecha.AstCoordinate():
                    add_token(node_range(node), CustomTokenTypes.NUMBER)
                case mecha.AstString() | mecha.AstMessageText():
                    add_token(node_range(node), CustomTokenTypes.STRING)
                case AstTargetIdentifier():
                    add_token(node_range(node), CustomTokenTypes.VARIABLE, {CustomTokenModifiers.DEFINITION})
                case AstIdentifier():
                    add_token(node_range(node), CustomTokenTypes.VARIABLE)
                case AstValue():
                    if isinstance(node.value, int | float):
                        add_token(node_range(node), CustomTokenTypes.NUMBER)
                    else:
                        add_token(node_range(node), CustomTokenTypes.STRING)
                case AstSelector():
                    add_token(node_range(node), CustomTokenTypes.SELECTOR)
                case AstNbtCompoundKey() | AstJsonObjectKey():
                    add_token(node_range(node), CustomTokenTypes.NBT_KEY)
                case AstNbtValue() | AstJsonValue():
                    if isinstance(node.value, int | float):
                        add_token(node_range(node), CustomTokenTypes.NBT_NUMBER)
                    else:
                        add_token(node_range(node), CustomTokenTypes.NBT_STRING)


@server.feature(INITIALIZE)
async def initialize(ls: LanguageServer, params: InitializeParams):
    """初始化服务器"""
    ls.window_log_message(LogMessageParams(type=MessageType.Info, message="服务器已启动"))


@server.feature(TEXT_DOCUMENT_DID_OPEN)
async def on_open(ls: LanguageServer, params: DidOpenTextDocumentParams):
    """当文件打开时，发送一个诊断示例"""
    first_line = params.text_document.text.split("\n")[0]
    ls.window_show_message(ShowMessageParams(MessageType.Info, f"欢迎使用 {first_line} ！"))
    # diagnostics = [Diagnostic(range=Range(Position(0, 0), Position(0, 5)), message="示例警告：检查你的代码", severity=DiagnosticSeverity.Warning)]
    # ls.text_document_publish_diagnostics(PublishDiagnosticsParams(params.text_document.uri, diagnostics))
    parse(ls, ls.workspace.get_text_document(params.text_document.uri))


@server.feature(TEXT_DOCUMENT_DID_CHANGE)
async def on_change(ls: LanguageServer, params: DidChangeTextDocumentParams):
    parse(ls, ls.workspace.get_text_document(params.text_document.uri))


@server.feature(TEXT_DOCUMENT_COMPLETION)
async def completions(ls: LanguageServer, params: CompletionParams):
    """提供代码补全"""
    items = [
        # CompletionItem(label="hello", kind=12, insert_text="hello()"),
        # CompletionItem(label="world", kind=12, insert_text="world()"),
    ]
    return CompletionList(is_incomplete=False, items=items)


@server.feature(
    TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
    SemanticTokensLegend(
        token_types=list(CustomTokenTypes),
        token_modifiers=list(CustomTokenModifiers)
    )
)
async def semantic_tokens_full(ls, params: SemanticTokensParams):
    """提供语义标记"""
    data = []
    last_line = 0
    last_col = 0
    the_tokens = tokens.get(params.text_document.uri, [])
    the_tokens.sort(key=lambda x: (x.line, x.start_col))
    for token in the_tokens:
        this_line = token.line - last_line
        last_line = token.line
        if this_line > 0:
            last_col = 0
        this_col = token.start_col - last_col
        last_col = token.start_col
        data.extend([
            this_line,
            this_col,
            len(token.text),
            list(CustomTokenTypes).index(token.type),
            reduce(operator.or_, [list(CustomTokenModifiers).index(m) for m in token.modifiers], 0)
        ])
    return SemanticTokens(data)


@server.feature(TEXT_DOCUMENT_DEFINITION)
async def definition(ls, params: DefinitionParams):
    """提供定义"""
    return [Location(uri=params.text_document.uri, range=Range(Position(0, 0), Position(0, 5)))]


if __name__ == "__main__":
    server.start_io()
