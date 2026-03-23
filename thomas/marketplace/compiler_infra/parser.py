"""Parser for the Thomas language using recursive descent with Pratt parsing."""

from __future__ import annotations

from ._exceptions import ParseError
from ._types import (
    ArrayLit,
    ArrayType,
    AssignStmt,
    ASTNode,
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
    Identifier,
    IfStmt,
    IndexAssignStmt,
    IndexExpr,
    IntLit,
    IntType,
    NullLit,
    Program,
    ReturnStmt,
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


class Parser:
    """Recursive descent parser with Pratt parsing for expressions."""

    def __init__(self, tokens: list[Token]) -> None:
        """Initialize the parser.

        Args:
            tokens: List of tokens from the lexer.
        """
        self.tokens = tokens
        self.pos = 0

    def error(self, message: str) -> ParseError:
        """Create a parse error at the current token."""
        token = self.current_token()
        return ParseError(message, token.location)

    def current_token(self) -> Token:
        """Get the current token."""
        if self.pos >= len(self.tokens):
            return self.tokens[-1]  # EOF
        return self.tokens[self.pos]

    def peek_token(self, offset: int = 1) -> Token:
        """Peek ahead at a token."""
        pos = self.pos + offset
        if pos >= len(self.tokens):
            return self.tokens[-1]  # EOF
        return self.tokens[pos]

    def advance(self) -> Token:
        """Consume and return the current token."""
        token = self.current_token()
        if token.type != TokenType.EOF:
            self.pos += 1
        return token

    def expect(self, token_type: TokenType) -> Token:
        """Expect a specific token type and consume it."""
        token = self.current_token()
        if token.type != token_type:
            raise self.error(f"Expected {token_type.name}, got {token.type.name}")
        return self.advance()

    def match(self, *token_types: TokenType) -> bool:
        """Check if current token matches any of the given types."""
        return self.current_token().type in token_types

    def consume_if(self, token_type: TokenType) -> bool:
        """Consume token if it matches the type."""
        if self.match(token_type):
            self.advance()
            return True
        return False

    def parse_type(self) -> Type:
        """Parse a type annotation."""
        if self.match(TokenType.IDENT):
            name = self.advance().value
            if name == "int":
                base_type: Type = IntType()
            elif name == "float":
                base_type = FloatType()
            elif name == "bool":
                base_type = BoolType()
            elif name == "string":
                base_type = StringType()
            elif name == "void":
                base_type = VoidType()
            else:
                raise self.error(f"Unknown type: {name}")

            # Handle array syntax: int[], int[][], etc.
            while self.consume_if(TokenType.LBRACKET):
                self.expect(TokenType.RBRACKET)
                base_type = ArrayType(base_type)

            return base_type

        raise self.error(f"Expected type, got {self.current_token().type.name}")

    def parse_program(self) -> Program:
        """Parse a complete program."""
        location = self.current_token().location
        declarations: list[ASTNode] = []

        while self.current_token().type != TokenType.EOF:
            if self.match(TokenType.FN):
                declarations.append(self.parse_func_decl())
            elif self.match(TokenType.LET):
                declarations.append(self.parse_var_decl())
            else:
                raise self.error("Expected function or variable declaration")

        return Program(declarations, location)

    def parse_func_decl(self) -> FuncDecl:
        """Parse a function declaration."""
        location = self.expect(TokenType.FN).location
        name = self.expect(TokenType.IDENT).value

        self.expect(TokenType.LPAREN)
        params: list[tuple[str, Type]] = []

        if not self.match(TokenType.RPAREN):
            while True:
                param_name = self.expect(TokenType.IDENT).value
                self.expect(TokenType.COLON)
                param_type = self.parse_type()
                params.append((param_name, param_type))

                if not self.consume_if(TokenType.COMMA):
                    break

        self.expect(TokenType.RPAREN)

        # Parse return type
        if self.consume_if(TokenType.ARROW):
            return_type = self.parse_type()
        else:
            return_type = VoidType()

        body = self.parse_block()
        return FuncDecl(name, params, return_type, body, location)

    def parse_var_decl(self) -> VarDecl:
        """Parse a variable declaration."""
        location = self.expect(TokenType.LET).location
        name = self.expect(TokenType.IDENT).value

        self.expect(TokenType.COLON)
        var_type = self.parse_type()

        init_expr: ASTNode | None = None
        if self.consume_if(TokenType.ASSIGN):
            init_expr = self.parse_expression()

        self.consume_if(TokenType.SEMICOLON)
        return VarDecl(name, var_type, init_expr, location)

    def parse_block(self) -> Block:
        """Parse a block of statements."""
        location = self.expect(TokenType.LBRACE).location
        statements: list[ASTNode] = []

        while not self.match(TokenType.RBRACE) and not self.match(TokenType.EOF):
            statements.append(self.parse_statement())

        self.expect(TokenType.RBRACE)
        return Block(statements, location)

    def parse_statement(self) -> ASTNode:
        """Parse a statement."""
        if self.match(TokenType.IF):
            return self.parse_if_stmt()
        elif self.match(TokenType.WHILE):
            return self.parse_while_stmt()
        elif self.match(TokenType.FOR):
            return self.parse_for_stmt()
        elif self.match(TokenType.RETURN):
            return self.parse_return_stmt()
        elif self.match(TokenType.LET):
            return self.parse_var_decl()
        elif self.match(TokenType.LBRACE):
            return self.parse_block()
        else:
            # Assignment or expression statement
            expr = self.parse_expression()

            # Check for assignment
            if self.match(TokenType.ASSIGN, TokenType.PLUS_ASSIGN, TokenType.MINUS_ASSIGN):
                if isinstance(expr, Identifier):
                    op = self.current_token().type
                    self.advance()
                    value = self.parse_expression()
                    self.consume_if(TokenType.SEMICOLON)
                    return AssignStmt(expr.name, value, op, expr.location)
                elif isinstance(expr, IndexExpr):
                    self.expect(TokenType.ASSIGN)
                    value = self.parse_expression()
                    self.consume_if(TokenType.SEMICOLON)
                    return IndexAssignStmt(expr.target, expr.index, value, expr.location)
                else:
                    raise self.error("Invalid assignment target")

            self.consume_if(TokenType.SEMICOLON)
            return ExprStmt(expr, expr.location)

    def parse_if_stmt(self) -> IfStmt:
        """Parse an if statement."""
        location = self.expect(TokenType.IF).location
        self.expect(TokenType.LPAREN)
        condition = self.parse_expression()
        self.expect(TokenType.RPAREN)

        then_branch = self.parse_block()

        else_branch: Block | None = None
        if self.consume_if(TokenType.ELSE):
            if self.match(TokenType.IF):
                # Handle else if as nested if
                else_if_stmt = self.parse_if_stmt()
                else_branch = Block([else_if_stmt], else_if_stmt.location)
            else:
                else_branch = self.parse_block()

        return IfStmt(condition, then_branch, else_branch, location)

    def parse_while_stmt(self) -> WhileStmt:
        """Parse a while loop."""
        location = self.expect(TokenType.WHILE).location
        self.expect(TokenType.LPAREN)
        condition = self.parse_expression()
        self.expect(TokenType.RPAREN)

        body = self.parse_block()
        return WhileStmt(condition, body, location)

    def parse_for_stmt(self) -> ForStmt:
        """Parse a for loop."""
        location = self.expect(TokenType.FOR).location
        self.expect(TokenType.LPAREN)

        # Init
        init: ASTNode | None = None
        if not self.match(TokenType.SEMICOLON):
            if self.match(TokenType.LET):
                # Parse variable declaration without consuming semicolon
                init_location = self.expect(TokenType.LET).location
                name = self.expect(TokenType.IDENT).value
                self.expect(TokenType.COLON)
                var_type = self.parse_type()

                init_expr: ASTNode | None = None
                if self.consume_if(TokenType.ASSIGN):
                    init_expr = self.parse_expression()

                init = VarDecl(name, var_type, init_expr, init_location)
            else:
                init = self.parse_expression()
        self.expect(TokenType.SEMICOLON)

        # Condition
        condition: ASTNode | None = None
        if not self.match(TokenType.SEMICOLON):
            condition = self.parse_expression()
        self.expect(TokenType.SEMICOLON)

        # Update
        update: ASTNode | None = None
        if not self.match(TokenType.RPAREN):
            expr = self.parse_expression()
            # Handle assignment in update expression
            if self.match(TokenType.ASSIGN, TokenType.PLUS_ASSIGN, TokenType.MINUS_ASSIGN):
                if isinstance(expr, Identifier):
                    op = self.current_token().type
                    self.advance()
                    value = self.parse_expression()
                    update = AssignStmt(expr.name, value, op, expr.location)
                else:
                    update = expr
            else:
                update = expr
        self.expect(TokenType.RPAREN)

        body = self.parse_block()
        return ForStmt(init, condition, update, body, location)

    def parse_return_stmt(self) -> ReturnStmt:
        """Parse a return statement."""
        location = self.expect(TokenType.RETURN).location
        value: ASTNode | None = None

        if not self.match(TokenType.SEMICOLON, TokenType.RBRACE, TokenType.EOF):
            value = self.parse_expression()

        self.consume_if(TokenType.SEMICOLON)
        return ReturnStmt(value, location)

    def parse_expression(self) -> ASTNode:
        """Parse an expression using Pratt parsing."""
        return self.parse_logical_or()

    def parse_logical_or(self) -> ASTNode:
        """Parse logical OR expression."""
        left = self.parse_logical_and()

        while self.match(TokenType.LOGICAL_OR, TokenType.OR):
            op = self.current_token().type
            op_location = self.advance().location
            right = self.parse_logical_and()
            left = BinaryExpr(left, op, right, op_location)

        return left

    def parse_logical_and(self) -> ASTNode:
        """Parse logical AND expression."""
        left = self.parse_equality()

        while self.match(TokenType.LOGICAL_AND, TokenType.AND):
            op = self.current_token().type
            op_location = self.advance().location
            right = self.parse_equality()
            left = BinaryExpr(left, op, right, op_location)

        return left

    def parse_equality(self) -> ASTNode:
        """Parse equality operators."""
        left = self.parse_comparison()

        while self.match(TokenType.EQ, TokenType.NE):
            op = self.current_token().type
            op_location = self.advance().location
            right = self.parse_comparison()
            left = BinaryExpr(left, op, right, op_location)

        return left

    def parse_comparison(self) -> ASTNode:
        """Parse comparison operators."""
        left = self.parse_additive()

        while self.match(TokenType.LT, TokenType.GT, TokenType.LE, TokenType.GE):
            op = self.current_token().type
            op_location = self.advance().location
            right = self.parse_additive()
            left = BinaryExpr(left, op, right, op_location)

        return left

    def parse_additive(self) -> ASTNode:
        """Parse addition and subtraction."""
        left = self.parse_multiplicative()

        while self.match(TokenType.PLUS, TokenType.MINUS):
            op = self.current_token().type
            op_location = self.advance().location
            right = self.parse_multiplicative()
            left = BinaryExpr(left, op, right, op_location)

        return left

    def parse_multiplicative(self) -> ASTNode:
        """Parse multiplication, division, and modulo."""
        left = self.parse_unary()

        while self.match(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            op = self.current_token().type
            op_location = self.advance().location
            right = self.parse_unary()
            left = BinaryExpr(left, op, right, op_location)

        return left

    def parse_unary(self) -> ASTNode:
        """Parse unary operators."""
        if self.match(TokenType.MINUS, TokenType.NOT):
            op = self.current_token().type
            op_location = self.advance().location
            operand = self.parse_unary()
            return UnaryExpr(op, operand, op_location)

        return self.parse_postfix()

    def parse_postfix(self) -> ASTNode:
        """Parse postfix operations (function calls, array indexing)."""
        expr = self.parse_primary()

        while True:
            if self.match(TokenType.LPAREN):
                # Function call
                self.advance()
                args: list[ASTNode] = []

                if not self.match(TokenType.RPAREN):
                    while True:
                        args.append(self.parse_expression())
                        if not self.consume_if(TokenType.COMMA):
                            break

                self.expect(TokenType.RPAREN)

                if isinstance(expr, Identifier):
                    expr = CallExpr(expr.name, args, expr.location)
                else:
                    raise self.error("Only identifiers can be called")

            elif self.match(TokenType.LBRACKET):
                # Array indexing
                self.advance()
                index = self.parse_expression()
                self.expect(TokenType.RBRACKET)

                if isinstance(expr, Identifier):
                    expr = IndexExpr(expr.name, index, expr.location)
                else:
                    raise self.error("Only identifiers can be indexed")

            else:
                break

        return expr

    def parse_primary(self) -> ASTNode:
        """Parse primary expressions."""
        token = self.current_token()
        location = token.location

        if self.match(TokenType.INT_LIT):
            value = self.advance().value
            return IntLit(value, location)

        if self.match(TokenType.FLOAT_LIT):
            value = self.advance().value
            return FloatLit(value, location)

        if self.match(TokenType.STRING_LIT):
            value = self.advance().value
            return StringLit(value, location)

        if self.match(TokenType.TRUE):
            self.advance()
            return BoolLit(True, location)

        if self.match(TokenType.FALSE):
            self.advance()
            return BoolLit(False, location)

        if self.match(TokenType.NULL):
            self.advance()
            return NullLit(location)

        if self.match(TokenType.IDENT):
            name = self.advance().value
            return Identifier(name, location)

        if self.match(TokenType.LPAREN):
            self.advance()
            expr = self.parse_expression()
            self.expect(TokenType.RPAREN)
            return expr

        if self.match(TokenType.LBRACKET):
            # Array literal
            self.advance()
            elements: list[ASTNode] = []

            if not self.match(TokenType.RBRACKET):
                elements.append(self.parse_expression())

                # Check for [value; count] syntax
                if self.consume_if(TokenType.SEMICOLON):
                    count = self.parse_expression()
                    # Expand to full array
                    if isinstance(elements[0], IntLit) and isinstance(count, IntLit):
                        elements = [IntLit(elements[0].value, elements[0].location) for _ in range(count.value)]
                else:
                    while self.consume_if(TokenType.COMMA):
                        elements.append(self.parse_expression())

            self.expect(TokenType.RBRACKET)
            return ArrayLit(elements, location)

        raise self.error(f"Unexpected token: {token.type.name}")
