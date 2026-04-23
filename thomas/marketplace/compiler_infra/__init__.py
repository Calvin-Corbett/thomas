"""Thomas compiler infrastructure module.

This module provides a complete compiler pipeline for the Thomas language,
including lexing, parsing, type checking, IR generation, optimization,
code generation, and virtual machine execution.
"""

from ._exceptions import (
    CodegenError,
    CompilerError,
    CompilerErrorCollector,
    LexError,
    ParseError,
    RuntimeError,
    TypeError,
)
from ._types import (
    ArrayLit,
    ArrayType,
    AssignStmt,
    ASTNode,
    ASTVisitor,
    BinaryExpr,
    Block,
    BoolLit,
    BoolType,
    CallExpr,
    ExprStmt,
    FloatLit,
    FloatType,
    ForStmt,
    FuncDecl,
    FuncType,
    Identifier,
    IfStmt,
    IndexAssignStmt,
    IndexExpr,
    IntLit,
    IntType,
    NullLit,
    Program,
    ReturnStmt,
    SourceLocation,
    StringLit,
    StringType,
    Token,
    TokenType,
    Type,
    UnaryExpr,
    VarDecl,
    VoidType,
    WhileStmt,
)
from .codegen import Bytecode, BytecodeProgram, CodeGenerator
from .ir import IRBasicBlock, IRBuilder, IRFunction, IRInstruction, IROpcode, IRProgram
from .lexer import Lexer
from .optimizer import IROptimizer
from .parser import Parser
from .pipeline import Compiler, CompilerConfig, compile, compile_and_execute
from .type_checker import SymbolTable, TypeChecker
from .vm import VirtualMachine

__version__ = "0.1.0"

__all__ = [
    # Types
    "Token",
    "TokenType",
    "SourceLocation",
    "ASTNode",
    "ASTVisitor",
    "Program",
    "FuncDecl",
    "VarDecl",
    "Block",
    "IfStmt",
    "WhileStmt",
    "ForStmt",
    "ReturnStmt",
    "AssignStmt",
    "IndexAssignStmt",
    "ExprStmt",
    "BinaryExpr",
    "UnaryExpr",
    "CallExpr",
    "IndexExpr",
    "ArrayLit",
    "Identifier",
    "IntLit",
    "FloatLit",
    "StringLit",
    "BoolLit",
    "NullLit",
    "Type",
    "IntType",
    "FloatType",
    "BoolType",
    "StringType",
    "VoidType",
    "ArrayType",
    "FuncType",
    # Exceptions
    "CompilerError",
    "LexError",
    "ParseError",
    "TypeError",
    "CodegenError",
    "RuntimeError",
    "CompilerErrorCollector",
    # Compiler components
    "Lexer",
    "Parser",
    "TypeChecker",
    "SymbolTable",
    "IRBuilder",
    "IRProgram",
    "IRFunction",
    "IRBasicBlock",
    "IRInstruction",
    "IROpcode",
    "IROptimizer",
    "CodeGenerator",
    "BytecodeProgram",
    "Bytecode",
    "VirtualMachine",
    "Compiler",
    "CompilerConfig",
    # Convenience functions
    "compile",
    "compile_and_execute",
]
