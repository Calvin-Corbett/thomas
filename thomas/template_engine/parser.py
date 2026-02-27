"""Template parser for building AST from tokens."""

from __future__ import annotations

from typing import Any

from ._exceptions import TemplateSyntaxError
from ._types import (
    Block,
    Call,
    Extends,
    FilterBlock,
    ForLoop,
    IfBlock,
    Include,
    Macro,
    Set,
    Template,
    TemplateNode,
    Text,
    Token,
    TokenType,
    Variable,
)


class Parser:
    """Parses token stream into AST."""

    def __init__(self, tokens: list[Token], name: str = "<template>") -> None:
        """
        Initialize the parser.

        Args:
            tokens: List of tokens from lexer
            name: Template name for error reporting
        """
        self.tokens = tokens
        self.pos = 0
        self.name = name
        self.current_token = tokens[0] if tokens else None

    def parse(self) -> Template:
        """
        Parse tokens into template AST.

        Returns:
            Template AST node
        """
        body = []
        while not self._at_end():
            if self._check(TokenType.EOF):
                break
            node = self._parse_node()
            if node:
                body.append(node)
        return Template(body=body)

    def _parse_node(self) -> TemplateNode | None:
        """Parse a single node."""
        if self._check(TokenType.TEXT):
            return self._parse_text()

        if self._check(TokenType.VAR_START):
            return self._parse_variable()

        if self._check(TokenType.BLOCK_START):
            node = self._parse_block()
            # _parse_block returns None if it's a block-end keyword
            # In that case, we just return None and let the caller handle it
            return node

        if self._at_end():
            return None

        # Skip unexpected standalone tokens
        if self._check(
            TokenType.BLOCK_END,
            TokenType.VAR_END,
        ):
            self._advance()
            return None

        # Block-end tokens should be handled by _parse_block
        if self._check(
            TokenType.ENDFOR,
            TokenType.ENDIF,
            TokenType.ENDBLOCK,
            TokenType.ELIF,
            TokenType.ELSE,
            TokenType.ENDMACRO,
            TokenType.ENDCALL,
            TokenType.ENDFILTER,
            TokenType.ENDSET,
        ):
            return None

        raise TemplateSyntaxError(f"Unexpected token: {self.current_token}", self.current_token.lineno)

    def _parse_text(self) -> Text:
        """Parse text node."""
        token = self._consume(TokenType.TEXT)
        return Text(value=token.value, lineno=token.lineno)

    def _parse_variable(self) -> Variable:
        """Parse variable expression: {{ expr }}."""
        lineno = self._consume(TokenType.VAR_START).lineno

        # Parse name
        if not self._check(TokenType.NAME):
            raise TemplateSyntaxError("Expected variable name", lineno)
        name_token = self._consume(TokenType.NAME)
        name = name_token.value

        # Parse attribute access and subscripts
        name = self._parse_access_chain(name)

        # Parse filters
        filters = []
        while self._match(TokenType.PIPE):
            filter_name_token = self._consume(TokenType.NAME)
            filter_name = filter_name_token.value

            # Parse filter arguments
            args = []
            if self._match(TokenType.LPAREN):
                args = self._parse_args()
                self._consume(TokenType.RPAREN)

            filters.append((filter_name, args))

        self._consume(TokenType.VAR_END)

        return Variable(name=name, filters=filters, lineno=lineno)

    def _parse_block(self) -> TemplateNode | None:
        """Parse block statement: {% ... %}."""
        # Check if NEXT token (after BLOCK_START) is a block-ending keyword
        if self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1].type in (
            TokenType.ELSE,
            TokenType.ELIF,
            TokenType.ENDFOR,
            TokenType.ENDIF,
            TokenType.ENDBLOCK,
            TokenType.ENDMACRO,
            TokenType.ENDCALL,
            TokenType.ENDFILTER,
            TokenType.ENDSET,
        ):
            # This is a block-ending token - don't parse it, return None
            return None

        lineno = self._consume(TokenType.BLOCK_START).lineno

        if self._check(TokenType.EOF):
            raise TemplateSyntaxError("Unexpected end of template", lineno)

        # Determine block type by first keyword
        if self._match(TokenType.FOR):
            return self._parse_for_loop(lineno)
        elif self._match(TokenType.IF):
            return self._parse_if_block(lineno)
        elif self._match(TokenType.BLOCK):
            return self._parse_named_block(lineno)
        elif self._match(TokenType.EXTENDS):
            return self._parse_extends(lineno)
        elif self._match(TokenType.INCLUDE):
            return self._parse_include(lineno)
        elif self._match(TokenType.MACRO):
            return self._parse_macro(lineno)
        elif self._match(TokenType.CALL):
            return self._parse_call_block(lineno)
        elif self._match(TokenType.FILTER):
            return self._parse_filter_block(lineno)
        elif self._match(TokenType.SET):
            return self._parse_set(lineno)
        else:
            raise TemplateSyntaxError(
                f"Unknown block type: {self.current_token.type.name}",
                lineno,
            )

    def _parse_for_loop(self, lineno: int) -> ForLoop:
        """Parse for loop: {% for var in iterable %}...{% endfor %}."""
        # Get target variable
        target_token = self._consume(TokenType.NAME)
        target = target_token.value

        # Expect 'in'
        if not self._match(TokenType.IN):
            raise TemplateSyntaxError("Expected 'in' after loop variable", lineno)

        # Get iterable expression
        iter_expr = self._parse_expression_until(TokenType.BLOCK_END)

        self._consume(TokenType.BLOCK_END)

        # Parse loop body
        body = self._parse_until([TokenType.ELSE, TokenType.ENDFOR])

        orelse = []
        if self._check(TokenType.BLOCK_START):
            saved_pos = self.pos
            self._advance()
            if self._check(TokenType.ELSE):
                self._consume(TokenType.ELSE)
                self._consume(TokenType.BLOCK_END)
                orelse = self._parse_until([TokenType.ENDFOR])
            else:
                self.pos = saved_pos

        # Consume endfor
        if self._check(TokenType.BLOCK_START):
            self._consume(TokenType.BLOCK_START)
            self._consume(TokenType.ENDFOR)
            self._consume(TokenType.BLOCK_END)

        return ForLoop(target=target, iter=iter_expr, body=body, orelse=orelse, lineno=lineno)

    def _parse_if_block(self, lineno: int) -> IfBlock:
        """Parse if block: {% if %}...{% elif %}...{% else %}...{% endif %}."""
        tests = []

        # Parse initial condition
        condition = self._parse_expression_until(TokenType.BLOCK_END)
        self._consume(TokenType.BLOCK_END)

        body = self._parse_until([TokenType.ELIF, TokenType.ELSE, TokenType.ENDIF])
        tests.append((condition, body))

        # Parse elif blocks
        while True:
            if not self._check(TokenType.BLOCK_START):
                break

            saved_pos = self.pos
            self._advance()

            if self._check(TokenType.ELIF):
                self._consume(TokenType.ELIF)
                condition = self._parse_expression_until(TokenType.BLOCK_END)
                self._consume(TokenType.BLOCK_END)
                body = self._parse_until([TokenType.ELIF, TokenType.ELSE, TokenType.ENDIF])
                tests.append((condition, body))
            else:
                self.pos = saved_pos
                break

        # Parse else block
        if self._check(TokenType.BLOCK_START):
            saved_pos = self.pos
            self._advance()

            if self._check(TokenType.ELSE):
                self._consume(TokenType.ELSE)
                self._consume(TokenType.BLOCK_END)
                body = self._parse_until([TokenType.ENDIF])
                tests.append((None, body))
            else:
                self.pos = saved_pos

        # Consume endif
        if self._check(TokenType.BLOCK_START):
            self._consume(TokenType.BLOCK_START)
            if self._check(TokenType.ENDIF):
                self._consume(TokenType.ENDIF)
                self._consume(TokenType.BLOCK_END)

        return IfBlock(tests=tests, lineno=lineno)

    def _parse_named_block(self, lineno: int) -> Block:
        """Parse named block: {% block name %}...{% endblock %}."""
        name_token = self._consume(TokenType.NAME)
        block_name = name_token.value

        self._consume(TokenType.BLOCK_END)

        body = self._parse_until([TokenType.ENDBLOCK])

        if self._check(TokenType.BLOCK_START):
            self._consume(TokenType.BLOCK_START)
            self._consume(TokenType.ENDBLOCK)
            self._consume(TokenType.BLOCK_END)

        return Block(name=block_name, body=body, lineno=lineno)

    def _parse_extends(self, lineno: int) -> Extends:
        """Parse extends: {% extends 'parent.html' %}."""
        parent_token = self._consume(TokenType.STRING)
        parent = parent_token.value

        self._consume(TokenType.BLOCK_END)

        return Extends(parent=parent, lineno=lineno)

    def _parse_include(self, lineno: int) -> Include:
        """Parse include: {% include 'file.html' %}."""
        template_token = self._consume(TokenType.STRING)
        template = template_token.value

        with_context = True
        if self._match(TokenType.WITH):
            self._consume(TokenType.NAME)  # 'context'

        self._consume(TokenType.BLOCK_END)

        return Include(template=template, with_context=with_context, lineno=lineno)

    def _parse_macro(self, lineno: int) -> Macro:
        """Parse macro definition: {% macro name(args) %}...{% endmacro %}."""
        name_token = self._consume(TokenType.NAME)
        macro_name = name_token.value

        self._consume(TokenType.LPAREN)

        # Parse arguments
        args = []
        defaults = {}
        while not self._check(TokenType.RPAREN):
            arg_token = self._consume(TokenType.NAME)
            args.append(arg_token.value)

            if self._match(TokenType.ASSIGN):
                # Default value
                default_val = self._parse_primary()
                defaults[arg_token.value] = default_val

            if not self._check(TokenType.RPAREN):
                self._consume(TokenType.COMMA)

        self._consume(TokenType.RPAREN)
        self._consume(TokenType.BLOCK_END)

        body = self._parse_until([TokenType.ENDMACRO])

        self._consume(TokenType.BLOCK_START)
        self._consume(TokenType.ENDMACRO)
        self._consume(TokenType.BLOCK_END)

        return Macro(name=macro_name, args=args, defaults=defaults, body=body, lineno=lineno)

    def _parse_call_block(self, lineno: int) -> Call:
        """Parse call block: {% call macro(args) %}...{% endcall %}."""
        name_token = self._consume(TokenType.NAME)
        name = name_token.value

        args = []
        kwargs = {}

        if self._match(TokenType.LPAREN):
            while not self._check(TokenType.RPAREN):
                if self._check_ahead_assign():
                    key_token = self._consume(TokenType.NAME)
                    self._consume(TokenType.ASSIGN)
                    value = self._parse_primary()
                    kwargs[key_token.value] = value
                else:
                    args.append(self._parse_primary())

                if not self._check(TokenType.RPAREN):
                    self._consume(TokenType.COMMA)
            self._consume(TokenType.RPAREN)

        self._consume(TokenType.BLOCK_END)

        # Skip body for call blocks (caller content)
        self._parse_until([TokenType.ENDCALL])

        self._consume(TokenType.BLOCK_START)
        self._consume(TokenType.ENDCALL)
        self._consume(TokenType.BLOCK_END)

        return Call(name=name, args=args, kwargs=kwargs, lineno=lineno)

    def _parse_filter_block(self, lineno: int) -> FilterBlock:
        """Parse filter block: {% filter name %}...{% endfilter %}."""
        name_token = self._consume(TokenType.NAME)
        filter_name = name_token.value

        args = []
        if self._match(TokenType.LPAREN):
            args = self._parse_args()
            self._consume(TokenType.RPAREN)

        self._consume(TokenType.BLOCK_END)

        body = self._parse_until([TokenType.ENDFILTER])

        self._consume(TokenType.BLOCK_START)
        self._consume(TokenType.ENDFILTER)
        self._consume(TokenType.BLOCK_END)

        return FilterBlock(name=filter_name, args=args, body=body, lineno=lineno)

    def _parse_set(self, lineno: int) -> Set:
        """Parse set statement: {% set x = value %}."""
        target_token = self._consume(TokenType.NAME)
        target = target_token.value

        self._consume(TokenType.ASSIGN)

        value = self._parse_expression_until(TokenType.BLOCK_END)

        self._consume(TokenType.BLOCK_END)

        return Set(target=target, value=value, lineno=lineno)

    def _parse_until(self, end_tokens: list[TokenType]) -> list[TemplateNode]:
        """Parse nodes until one of end_tokens is reached."""
        body = []
        while not self._at_end():
            # Check if we're at an end token (direct)
            if self._check(*end_tokens):
                break

            # Check if we're at a block start that could be an end token
            if self._check(TokenType.BLOCK_START):
                # Peek ahead to see if it's an end token
                saved_pos = self.pos
                self._advance()  # skip BLOCK_START
                if self._check(*end_tokens):
                    self.pos = saved_pos
                    break
                self.pos = saved_pos

            # Try to parse a node
            old_pos = self.pos
            node = self._parse_node()

            # Ensure we always made progress
            if self.pos == old_pos:
                # We didn't advance - break to avoid infinite loop
                break

            if node:
                body.append(node)

        return body

    def _parse_expression_until(self, end_token: TokenType) -> str:
        """Parse expression as string until end token."""
        start_pos = self.pos
        depth = 0

        while not self._at_end():
            if self._check(end_token) and depth == 0:
                break

            if self._check(TokenType.LPAREN, TokenType.LBRACKET, TokenType.LBRACE):
                depth += 1
            elif self._check(TokenType.RPAREN, TokenType.RBRACKET, TokenType.RBRACE):
                depth -= 1

            self._advance()

        # Reconstruct expression from tokens
        return self._reconstruct_tokens(start_pos, self.pos)

    def _parse_access_chain(self, name: str) -> str:
        """Parse attribute/subscript access: a.b.c or a[0]."""
        while True:
            if self._match(TokenType.DOT):
                if self._check(TokenType.NAME):
                    attr = self._consume(TokenType.NAME).value
                    name += "." + attr
                else:
                    break
            elif self._match(TokenType.LBRACKET):
                if self._check(TokenType.STRING):
                    key = self._consume(TokenType.STRING).value
                    name += f'["{key}"]'
                elif self._check(TokenType.NUMBER):
                    idx = self._consume(TokenType.NUMBER).value
                    name += f"[{idx}]"
                else:
                    break
                self._consume(TokenType.RBRACKET)
            else:
                break

        return name

    def _parse_args(self) -> list[Any]:
        """Parse function arguments."""
        args = []
        while not self._check(TokenType.RPAREN):
            args.append(self._parse_primary())
            if not self._check(TokenType.RPAREN):
                self._consume(TokenType.COMMA)
        return args

    def _parse_primary(self) -> Any:
        """Parse a primary expression."""
        if self._check(TokenType.STRING):
            return self._consume(TokenType.STRING).value
        elif self._check(TokenType.NUMBER):
            return self._consume(TokenType.NUMBER).value
        elif self._check(TokenType.TRUE):
            self._consume(TokenType.TRUE)
            return True
        elif self._check(TokenType.FALSE):
            self._consume(TokenType.FALSE)
            return False
        elif self._check(TokenType.NONE):
            self._consume(TokenType.NONE)
            return None
        elif self._check(TokenType.NAME):
            name = self._consume(TokenType.NAME).value
            return self._parse_access_chain(name)
        elif self._match(TokenType.LBRACKET):
            # List literal
            items = []
            while not self._check(TokenType.RBRACKET):
                items.append(self._parse_primary())
                if not self._check(TokenType.RBRACKET):
                    self._consume(TokenType.COMMA)
            self._consume(TokenType.RBRACKET)
            return items
        elif self._match(TokenType.LBRACE):
            # Dict literal
            items = {}
            while not self._check(TokenType.RBRACE):
                key = self._parse_primary()
                self._consume(TokenType.COLON)
                value = self._parse_primary()
                items[key] = value
                if not self._check(TokenType.RBRACE):
                    self._consume(TokenType.COMMA)
            self._consume(TokenType.RBRACE)
            return items
        else:
            raise TemplateSyntaxError(
                f"Unexpected token: {self.current_token}",
                self.current_token.lineno,
            )

    def _check_ahead_assign(self) -> bool:
        """Check if next token is NAME followed by ASSIGN."""
        if not self._check(TokenType.NAME):
            return False
        saved_pos = self.pos
        self._advance()
        result = self._check(TokenType.ASSIGN)
        self.pos = saved_pos
        return result

    def _reconstruct_tokens(self, start: int, end: int) -> str:
        """Reconstruct expression string from tokens."""
        parts = []
        for i in range(start, end):
            token = self.tokens[i]
            if token.type == TokenType.NAME:
                parts.append(token.value)
            elif token.type == TokenType.STRING:
                parts.append(f'"{token.value}"')
            elif token.type == TokenType.NUMBER:
                parts.append(str(token.value))
            elif token.type in (TokenType.TRUE, TokenType.FALSE, TokenType.NONE):
                parts.append(token.type.name.lower())
            elif token.type == TokenType.DOT:
                parts.append(".")
            elif token.type == TokenType.COMMA:
                parts.append(",")
            elif token.type == TokenType.COLON:
                parts.append(":")
            elif token.type == TokenType.LPAREN:
                parts.append("(")
            elif token.type == TokenType.RPAREN:
                parts.append(")")
            elif token.type == TokenType.LBRACKET:
                parts.append("[")
            elif token.type == TokenType.RBRACKET:
                parts.append("]")
            elif token.type == TokenType.LBRACE:
                parts.append("{")
            elif token.type == TokenType.RBRACE:
                parts.append("}")
            elif token.type == TokenType.EQ:
                parts.append("==")
            elif token.type == TokenType.NE:
                parts.append("!=")
            elif token.type == TokenType.LT:
                parts.append("<")
            elif token.type == TokenType.LE:
                parts.append("<=")
            elif token.type == TokenType.GT:
                parts.append(">")
            elif token.type == TokenType.GE:
                parts.append(">=")
            elif token.type == TokenType.AND:
                parts.append("and")
            elif token.type == TokenType.OR:
                parts.append("or")
            elif token.type == TokenType.NOT:
                parts.append("not")
            elif token.type == TokenType.IN:
                parts.append("in")
            elif token.type == TokenType.IS:
                parts.append("is")

        return " ".join(parts)

    # Utility methods
    def _match(self, *types: TokenType) -> bool:
        """Check if current token matches any type and consume it."""
        if self._check(*types):
            self._advance()
            return True
        return False

    def _check(self, *types: TokenType) -> bool:
        """Check if current token is one of the given types."""
        if self._at_end():
            return False
        return self.current_token.type in types

    def _consume(self, token_type: TokenType) -> Token:
        """Consume and return current token."""
        if self.current_token.type != token_type:
            raise TemplateSyntaxError(
                f"Expected {token_type.name}, got {self.current_token.type.name}",
                self.current_token.lineno,
            )
        token = self.current_token
        self._advance()
        return token

    def _advance(self) -> None:
        """Move to next token."""
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
            self.current_token = self.tokens[self.pos]

    def _at_end(self) -> bool:
        """Check if at end of tokens."""
        return self.current_token is None or self.current_token.type == TokenType.EOF
