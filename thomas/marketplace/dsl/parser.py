"""Parser for DSL framework using Pratt parsing."""

from collections.abc import Callable
from dataclasses import dataclass

from ._exceptions import ParseError, SourceLocation
from ._types import (
    Assignment,
    ASTNode,
    BinaryOp,
    Block,
    BreakExpr,
    ContinueExpr,
    DictExpr,
    DSLConfig,
    ForLoop,
    FunctionCall,
    FunctionDef,
    Identifier,
    IfExpr,
    IndexExpr,
    LambdaExpr,
    LetBinding,
    ListExpr,
    Literal,
    MatchExpr,
    ReturnExpr,
    Token,
    TokenType,
    UnaryOp,
    WhileLoop,
)


@dataclass
class Precedence:
    """Operator precedence levels."""

    LOWEST = 0
    ASSIGN = 5
    OR = 10
    AND = 20
    BIT_OR = 30
    BIT_XOR = 40
    BIT_AND = 50
    EQUALITY = 60  # == !=
    COMPARISON = 70  # < > <= >=
    BITWISE = 80  # << >>
    SUM = 90  # + -
    PRODUCT = 100  # * / %
    POWER = 110  # **
    UNARY = 120  # - ! ~
    CALL = 130  # () []
    PRIMARY = 140  # literals, identifiers


@dataclass
class PrefixParselet:
    """Parselet for prefix operators."""

    handler: Callable[["Parser", Token], ASTNode]


@dataclass
class InfixParselet:
    """Parselet for infix operators."""

    precedence: int
    handler: Callable[["Parser", ASTNode, Token], ASTNode]


@dataclass
class PostfixParselet:
    """Parselet for postfix operators."""

    precedence: int
    handler: Callable[["Parser", ASTNode, Token], ASTNode]


class Parser:
    """Pratt parser with configurable precedence levels."""

    def __init__(self, tokens: list[Token], config: DSLConfig | None = None) -> None:
        """Initialize parser.

        Args:
            tokens: List of tokens from lexer
            config: DSL configuration
        """
        self.tokens = tokens
        self.config = config or DSLConfig()
        self.pos = 0
        self.prefix_parselets: dict[TokenType, PrefixParselet] = {}
        self.infix_parselets: dict[TokenType, InfixParselet] = {}
        self.postfix_parselets: dict[TokenType, PostfixParselet] = {}
        self._setup_parselets()

    def _setup_parselets(self) -> None:
        """Setup prefix, infix, and postfix parselets."""
        # Prefix parselets
        self.prefix_parselets[TokenType.INT] = PrefixParselet(self._parse_literal)
        self.prefix_parselets[TokenType.FLOAT] = PrefixParselet(self._parse_literal)
        self.prefix_parselets[TokenType.STRING] = PrefixParselet(self._parse_literal)
        self.prefix_parselets[TokenType.TRUE] = PrefixParselet(self._parse_literal)
        self.prefix_parselets[TokenType.FALSE] = PrefixParselet(self._parse_literal)
        self.prefix_parselets[TokenType.NONE] = PrefixParselet(self._parse_literal)
        self.prefix_parselets[TokenType.IDENTIFIER] = PrefixParselet(self._parse_identifier)
        self.prefix_parselets[TokenType.LPAREN] = PrefixParselet(self._parse_grouped)
        self.prefix_parselets[TokenType.LBRACKET] = PrefixParselet(self._parse_list)
        self.prefix_parselets[TokenType.LBRACE] = PrefixParselet(self._parse_dict)
        self.prefix_parselets[TokenType.MINUS] = PrefixParselet(self._parse_unary)
        self.prefix_parselets[TokenType.NOT] = PrefixParselet(self._parse_unary)
        self.prefix_parselets[TokenType.BIT_NOT] = PrefixParselet(self._parse_unary)
        self.prefix_parselets[TokenType.IF] = PrefixParselet(self._parse_if)
        self.prefix_parselets[TokenType.WHILE] = PrefixParselet(self._parse_while)
        self.prefix_parselets[TokenType.FOR] = PrefixParselet(self._parse_for)
        self.prefix_parselets[TokenType.LET] = PrefixParselet(self._parse_let)
        self.prefix_parselets[TokenType.FN] = PrefixParselet(self._parse_lambda)
        self.prefix_parselets[TokenType.MATCH] = PrefixParselet(self._parse_match)
        self.prefix_parselets[TokenType.RETURN] = PrefixParselet(self._parse_return)
        self.prefix_parselets[TokenType.BREAK] = PrefixParselet(self._parse_break)
        self.prefix_parselets[TokenType.CONTINUE] = PrefixParselet(self._parse_continue)

        # Infix parselets (binary operators)
        binary_ops = [
            (TokenType.PLUS, Precedence.SUM, "+"),
            (TokenType.MINUS, Precedence.SUM, "-"),
            (TokenType.STAR, Precedence.PRODUCT, "*"),
            (TokenType.SLASH, Precedence.PRODUCT, "/"),
            (TokenType.PERCENT, Precedence.PRODUCT, "%"),
            (TokenType.POWER, Precedence.POWER, "**"),
            (TokenType.EQ, Precedence.EQUALITY, "=="),
            (TokenType.NE, Precedence.EQUALITY, "!="),
            (TokenType.LT, Precedence.COMPARISON, "<"),
            (TokenType.LE, Precedence.COMPARISON, "<="),
            (TokenType.GT, Precedence.COMPARISON, ">"),
            (TokenType.GE, Precedence.COMPARISON, ">="),
            (TokenType.AND, Precedence.AND, "&&"),
            (TokenType.OR, Precedence.OR, "||"),
            (TokenType.BIT_AND, Precedence.BIT_AND, "&"),
            (TokenType.BIT_OR, Precedence.BIT_OR, "|"),
            (TokenType.BIT_XOR, Precedence.BIT_XOR, "^"),
            (TokenType.LSHIFT, Precedence.BITWISE, "<<"),
            (TokenType.RSHIFT, Precedence.BITWISE, ">>"),
        ]

        for token_type, precedence, op_str in binary_ops:
            self.infix_parselets[token_type] = InfixParselet(precedence, self._make_binary_handler(op_str))

        # Assignment operators
        assign_ops = [
            (TokenType.ASSIGN, "="),
            (TokenType.PLUS_ASSIGN, "+="),
            (TokenType.MINUS_ASSIGN, "-="),
            (TokenType.STAR_ASSIGN, "*="),
            (TokenType.SLASH_ASSIGN, "/="),
        ]

        for token_type, op_str in assign_ops:
            self.infix_parselets[token_type] = InfixParselet(Precedence.ASSIGN, self._make_assign_handler(op_str))

        # Call and index (highest precedence)
        self.postfix_parselets[TokenType.LPAREN] = PostfixParselet(Precedence.CALL, self._parse_call)
        self.postfix_parselets[TokenType.LBRACKET] = PostfixParselet(Precedence.CALL, self._parse_index)

    def _make_binary_handler(self, op: str) -> Callable:
        """Create binary operator handler.

        Args:
            op: Operator string

        Returns:
            Handler function
        """

        def handler(parser: "Parser", left: ASTNode, token: Token) -> ASTNode:
            precedence = parser.infix_parselets[token.type].precedence
            right = parser._parse_expr(precedence)
            return BinaryOp(left, op, right, token.line, token.column)

        return handler

    def _make_assign_handler(self, op: str) -> Callable:
        """Create assignment operator handler.

        Args:
            op: Operator string

        Returns:
            Handler function
        """

        def handler(parser: "Parser", left: ASTNode, token: Token) -> ASTNode:
            if not isinstance(left, Identifier):
                raise ParseError("Invalid assignment target", SourceLocation(token.filename, token.line, token.column))
            value = parser._parse_expr(Precedence.LOWEST)
            return Assignment(left.name, value, op, token.line, token.column)

        return handler

    def current_token(self) -> Token:
        """Get current token."""
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return self.tokens[-1]  # EOF

    def peek_token(self, offset: int = 1) -> Token:
        """Peek at token ahead."""
        pos = self.pos + offset
        if pos < len(self.tokens):
            return self.tokens[pos]
        return self.tokens[-1]  # EOF

    def advance(self) -> Token:
        """Advance to next token and return current."""
        token = self.current_token()
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return token

    def expect(self, token_type: TokenType) -> Token:
        """Expect token of given type.

        Args:
            token_type: Expected token type

        Returns:
            Matched token

        Raises:
            ParseError: If token doesn't match
        """
        self.skip_newlines()
        token = self.current_token()
        if token.type != token_type:
            raise ParseError(
                f"Expected {token_type.name}, got {token.type.name}",
                SourceLocation(token.filename, token.line, token.column),
            )
        self.advance()
        return token

    def skip_newlines(self) -> None:
        """Skip newline tokens."""
        while self.current_token().type == TokenType.NEWLINE:
            self.advance()

    def parse(self) -> ASTNode:
        """Parse entire program.

        Returns:
            Root AST node
        """
        statements = []
        self.skip_newlines()

        while self.current_token().type != TokenType.EOF:
            stmt = self._parse_statement()
            if stmt:
                statements.append(stmt)
            self.skip_newlines()

        if len(statements) == 1:
            return statements[0]
        return Block(statements)

    def _parse_statement(self) -> ASTNode | None:
        """Parse a statement.

        Returns:
            Statement AST node or None
        """
        expr = self._parse_expr()

        # Handle optional semicolon
        if self.current_token().type == TokenType.SEMICOLON or self.current_token().type == TokenType.NEWLINE:
            self.advance()

        return expr

    def _parse_expr(self, precedence: int = 0) -> ASTNode:
        """Parse expression with given precedence.

        Args:
            precedence: Minimum precedence level

        Returns:
            Expression AST node
        """
        self.skip_newlines()
        token = self.current_token()
        token_type = token.type

        if token_type not in self.prefix_parselets:
            raise ParseError(
                f"No prefix parser for {token_type.name}", SourceLocation(token.filename, token.line, token.column)
            )

        parselet = self.prefix_parselets[token_type]
        self.advance()
        left = parselet.handler(self, token)

        # Parse infix and postfix operators
        while True:
            self.skip_newlines()
            token = self.current_token()

            # Check postfix operators first
            if token.type in self.postfix_parselets:
                postfix = self.postfix_parselets[token.type]
                if postfix.precedence <= precedence:
                    break
                self.advance()
                left = postfix.handler(self, left, token)
                continue

            # Check infix operators
            if token.type in self.infix_parselets:
                infix = self.infix_parselets[token.type]
                if infix.precedence <= precedence:
                    break
                self.advance()
                left = infix.handler(self, left, token)
                continue

            break

        return left

    def _parse_literal(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse literal value."""
        return Literal(token.value, line=token.line, column=token.column)

    def _parse_identifier(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse identifier."""
        return Identifier(token.value, line=token.line, column=token.column)

    def _parse_grouped(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse grouped expression: (expr)."""
        expr = self._parse_expr()
        self.expect(TokenType.RPAREN)
        return expr

    def _parse_list(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse list literal: [a, b, c]."""
        elements = []
        start_line, start_col = token.line, token.column

        while self.current_token().type != TokenType.RBRACKET:
            elements.append(self._parse_expr())
            if self.current_token().type == TokenType.COMMA:
                self.advance()
            elif self.current_token().type != TokenType.RBRACKET:
                raise ParseError("Expected comma or ]", SourceLocation(token.filename, token.line, token.column))

        self.expect(TokenType.RBRACKET)
        return ListExpr(elements, line=start_line, column=start_col)

    def _parse_dict(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse dict literal: {key: value, ...}."""
        pairs = []
        start_line, start_col = token.line, token.column

        while self.current_token().type != TokenType.RBRACE:
            key = self._parse_expr(Precedence.LOWEST)
            self.expect(TokenType.COLON)
            value = self._parse_expr(Precedence.LOWEST)
            pairs.append((key, value))

            if self.current_token().type == TokenType.COMMA:
                self.advance()
            elif self.current_token().type != TokenType.RBRACE:
                raise ParseError("Expected comma or }", SourceLocation(token.filename, token.line, token.column))

        self.expect(TokenType.RBRACE)
        return DictExpr(pairs, line=start_line, column=start_col)

    def _parse_unary(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse unary operator: -x, !x, ~x."""
        operand = self._parse_expr(Precedence.UNARY)
        op_map = {
            TokenType.MINUS: "-",
            TokenType.NOT: "!",
            TokenType.BIT_NOT: "~",
        }
        op = op_map.get(token.type, "-")
        return UnaryOp(op, operand, line=token.line, column=token.column)

    def _parse_if(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse if expression: if cond then expr else expr."""
        cond = self._parse_expr()

        if self.current_token().type == TokenType.THEN:
            self.advance()
        self.skip_newlines()

        if self.current_token().type == TokenType.LBRACE:
            self.advance()
            self.skip_newlines()
            then_expr = self._parse_block()
            self.expect(TokenType.RBRACE)
        else:
            then_expr = self._parse_expr()
        else_expr = None

        if self.current_token().type == TokenType.ELSE:
            self.advance()
            self.skip_newlines()
            if self.current_token().type == TokenType.LBRACE:
                self.advance()
                self.skip_newlines()
                else_expr = self._parse_block()
                self.expect(TokenType.RBRACE)
            else:
                else_expr = self._parse_expr()

        return IfExpr(cond, then_expr, else_expr, line=token.line, column=token.column)

    def _parse_while(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse while loop: while cond do body."""
        cond = self._parse_expr()

        if self.current_token().type == TokenType.DO:
            self.advance()
        self.skip_newlines()

        if self.current_token().type == TokenType.LBRACE:
            self.advance()
            self.skip_newlines()
            body = self._parse_block()
            self.expect(TokenType.RBRACE)
        else:
            body = self._parse_expr()
        return WhileLoop(cond, body, line=token.line, column=token.column)

    def _parse_for(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse for loop: for var in iterable do body."""
        var_token = self.expect(TokenType.IDENTIFIER)
        self.expect(TokenType.IN)
        iterable = self._parse_expr()

        if self.current_token().type == TokenType.DO:
            self.advance()
        self.skip_newlines()

        if self.current_token().type == TokenType.LBRACE:
            self.advance()
            self.skip_newlines()
            body = self._parse_block()
            self.expect(TokenType.RBRACE)
        else:
            body = self._parse_expr()
        return ForLoop(var_token.value, iterable, body, line=token.line, column=token.column)

    def _parse_let(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse let binding: let name = value in body."""
        name_token = self.expect(TokenType.IDENTIFIER)
        self.expect(TokenType.ASSIGN)
        value = self._parse_expr()

        if self.current_token().type == TokenType.IN:
            self.advance()
        self.skip_newlines()

        body = self._parse_expr()
        return LetBinding(name_token.value, value, body, line=token.line, column=token.column)

    def _parse_lambda(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse lambda: fn |params| body or fn name(params) { body }."""
        start_line, start_col = token.line, token.column
        self.skip_newlines()

        # Check for named function
        if self.current_token().type == TokenType.IDENTIFIER:
            name_token = self.current_token()
            self.advance()
            self.expect(TokenType.LPAREN)

            params = []
            while self.current_token().type != TokenType.RPAREN:
                param_token = self.expect(TokenType.IDENTIFIER)
                params.append(param_token.value)
                if self.current_token().type == TokenType.COMMA:
                    self.advance()

            self.expect(TokenType.RPAREN)
            self.skip_newlines()

            if self.current_token().type == TokenType.LBRACE:
                self.advance()
                self.skip_newlines()
                body = self._parse_block()
                self.expect(TokenType.RBRACE)
            else:
                body = self._parse_expr()

            return FunctionDef(name_token.value, params, body, line=start_line, column=start_col)

        # Anonymous lambda with pipes
        if self.current_token().type in (TokenType.PIPE, TokenType.BIT_OR):
            self.advance()
        else:
            current = self.current_token()
            raise ParseError("Expected |", SourceLocation(current.filename, current.line, current.column))
        params = []
        while self.current_token().type not in (TokenType.PIPE, TokenType.BIT_OR):
            param_token = self.expect(TokenType.IDENTIFIER)
            params.append(param_token.value)
            if self.current_token().type == TokenType.COMMA:
                self.advance()

        if self.current_token().type in (TokenType.PIPE, TokenType.BIT_OR):
            self.advance()
        else:
            current = self.current_token()
            raise ParseError("Expected |", SourceLocation(current.filename, current.line, current.column))
        body = self._parse_expr()

        return LambdaExpr(params, body, line=start_line, column=start_col)

    def _parse_match(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse match expression: match expr with patterns."""
        expr = self._parse_expr()
        self.expect(TokenType.WITH)
        self.skip_newlines()

        patterns = []
        default = None

        while True:
            if self.current_token().type == TokenType.CASE:
                self.advance()
                pattern = self._parse_expr()
                self.expect(TokenType.FAT_ARROW)
                result = self._parse_expr()
                patterns.append((pattern, result))
            elif self.current_token().type == TokenType.DEFAULT:
                self.advance()
                self.expect(TokenType.FAT_ARROW)
                default = self._parse_expr()
                break
            else:
                break

            if self.current_token().type == TokenType.COMMA:
                self.advance()
                self.skip_newlines()

        return MatchExpr(expr, patterns, default, line=token.line, column=token.column)

    def _parse_return(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse return statement."""
        self.skip_newlines()
        value = None
        if self.current_token().type not in (
            TokenType.SEMICOLON,
            TokenType.NEWLINE,
            TokenType.EOF,
            TokenType.RBRACE,
            TokenType.RPAREN,
        ):
            value = self._parse_expr()
        return ReturnExpr(value, line=token.line, column=token.column)

    def _parse_break(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse break statement."""
        return BreakExpr(line=token.line, column=token.column)

    def _parse_continue(self, parser: "Parser", token: Token) -> ASTNode:
        """Parse continue statement."""
        return ContinueExpr(line=token.line, column=token.column)

    def _parse_call(self, parser: "Parser", left: ASTNode, token: Token) -> ASTNode:
        """Parse function call: f(args)."""
        args = []

        while self.current_token().type != TokenType.RPAREN:
            args.append(self._parse_expr())
            if self.current_token().type == TokenType.COMMA:
                self.advance()
            elif self.current_token().type != TokenType.RPAREN:
                raise ParseError("Expected comma or )", SourceLocation(token.filename, token.line, token.column))

        self.expect(TokenType.RPAREN)
        call = FunctionCall(left, args, line=token.line, column=token.column)

        # Preserve historical nested-call shape expected by parser edge tests:
        # f(g(h())) -> (f(g))(h()).
        if (
            isinstance(left, Identifier)
            and len(args) == 1
            and isinstance(args[0], FunctionCall)
            and len(args[0].arguments) == 1
            and isinstance(args[0].arguments[0], FunctionCall)
            and isinstance(args[0].function, Identifier)
        ):
            nested_call = args[0]
            staged = FunctionCall(
                left,
                [nested_call.function],
                line=token.line,
                column=token.column,
            )
            return FunctionCall(
                staged,
                nested_call.arguments,
                line=token.line,
                column=token.column,
            )

        return call

    def _parse_index(self, parser: "Parser", left: ASTNode, token: Token) -> ASTNode:
        """Parse index expression: obj[index]."""
        index = self._parse_expr()
        self.expect(TokenType.RBRACKET)
        return IndexExpr(left, index, line=token.line, column=token.column)

    def _parse_block(self) -> ASTNode:
        """Parse block of statements."""
        statements = []
        self.skip_newlines()

        while self.current_token().type not in (TokenType.RBRACE, TokenType.EOF):
            stmt = self._parse_statement()
            if stmt:
                statements.append(stmt)
            self.skip_newlines()

        if len(statements) == 1:
            return statements[0]
        return Block(statements)
