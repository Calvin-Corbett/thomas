"""Cypher-subset query parser with recursive descent parsing and AST building."""

from typing import Any

from thomas.marketplace.graphdb._exceptions import QuerySyntaxError
from thomas.marketplace.graphdb._types import ASTNode, PatternElement
from thomas.marketplace.graphdb.query_parser import Token, TokenType


class Parser:
    """Recursive descent parser for Cypher queries.

    Converts a stream of tokens into an Abstract Syntax Tree (AST)
    representing the structure of a Cypher query.
    """

    def __init__(self, tokens: list[Token]) -> None:
        """Initialize parser.

        Args:
            tokens: List of tokens from lexer
        """
        self.tokens: list[Token] = tokens
        self.position: int = 0

    def parse(self) -> ASTNode:
        """Parse the tokens into an AST.

        Returns:
            ASTNode: Root AST node representing the complete query

        Raises:
            QuerySyntaxError: If parsing fails
        """
        return self._parse_query()

    def _current_token(self) -> Token:
        """Get current token.

        Returns:
            Token: The current token, or EOF if at end
        """
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return self.tokens[-1]  # EOF

    def _peek_token(self, offset: int = 1) -> Token:
        """Peek at next token.

        Args:
            offset: How many tokens ahead to look (default 1)

        Returns:
            Token: The token at the specified offset, or EOF if beyond end
        """
        pos: int = self.position + offset
        if pos < len(self.tokens):
            return self.tokens[pos]
        return self.tokens[-1]  # EOF

    def _advance(self) -> None:
        """Consume current token and move to next."""
        if self.position < len(self.tokens):
            self.position += 1

    def _expect(self, token_type: TokenType) -> Token:
        """Consume token of expected type.

        Args:
            token_type: The expected token type

        Returns:
            Token: The consumed token

        Raises:
            QuerySyntaxError: If token doesn't match expected type
        """
        token: Token = self._current_token()
        if token.type != token_type:
            raise QuerySyntaxError(
                f"Expected {token_type.name}, got {token.type.name}",
                token.position,
                token.value,
            )
        self._advance()
        return token

    def _parse_query(self) -> ASTNode:
        """Parse a complete query.

        Returns:
            ASTNode: The root QUERY node containing all clauses
        """
        root: ASTNode = ASTNode("QUERY")

        while self._current_token().type != TokenType.EOF:
            if self._current_token().type == TokenType.MATCH:
                root.add_child(self._parse_match())
            elif self._current_token().type == TokenType.WHERE:
                root.add_child(self._parse_where())
            elif self._current_token().type == TokenType.RETURN:
                root.add_child(self._parse_return())
            elif self._current_token().type == TokenType.CREATE:
                root.add_child(self._parse_create())
            elif self._current_token().type == TokenType.DELETE:
                root.add_child(self._parse_delete())
            elif self._current_token().type == TokenType.SET:
                root.add_child(self._parse_set())
            elif self._current_token().type == TokenType.ORDER:
                root.add_child(self._parse_order_by())
            elif self._current_token().type == TokenType.LIMIT:
                root.add_child(self._parse_limit())
            elif self._current_token().type == TokenType.SKIP:
                root.add_child(self._parse_skip())
            else:
                raise QuerySyntaxError(
                    f"Unexpected token: {self._current_token().type.name}",
                    self._current_token().position,
                )

        return root

    def _parse_match(self) -> ASTNode:
        """Parse MATCH clause.

        Returns:
            ASTNode: MATCH node with pattern children
        """
        self._expect(TokenType.MATCH)
        node: ASTNode = ASTNode("MATCH")

        patterns: list[ASTNode] = self._parse_pattern()
        for pattern in patterns:
            node.add_child(pattern)

        return node

    def _parse_pattern(self) -> list[ASTNode]:
        """Parse pattern (node-edge-node chains).

        Returns:
            List[ASTNode]: List of PATTERN nodes
        """
        patterns: list[ASTNode] = []

        while True:
            pattern: ASTNode = ASTNode("PATTERN")

            # Parse node
            node_elem: ASTNode = self._parse_pattern_node()
            pattern.add_child(node_elem)

            # Parse optional edges and following nodes
            while self._current_token().type in (TokenType.ARROW, TokenType.LEFT_ARROW):
                direction: str = self._current_token().value
                self._advance()

                edge_elem: ASTNode = self._parse_pattern_edge()
                if direction == "<-":
                    edge_elem.value = "<-"
                pattern.add_child(edge_elem)

                node_elem = self._parse_pattern_node()
                pattern.add_child(node_elem)

            patterns.append(pattern)

            if self._current_token().type != TokenType.COMMA:
                break
            self._advance()

        return patterns

    def _parse_pattern_node(self) -> ASTNode:
        """Parse a node in a pattern.

        Returns:
            ASTNode: NODE node with PatternElement value
        """
        self._expect(TokenType.LPAREN)

        variable: str | None = None
        if self._current_token().type == TokenType.IDENTIFIER:
            variable = self._current_token().value
            self._advance()

        labels: set[str] = set()
        if self._current_token().type == TokenType.COLON:
            self._advance()
            labels.add(self._expect(TokenType.IDENTIFIER).value)

            while self._current_token().type == TokenType.COLON:
                self._advance()
                labels.add(self._expect(TokenType.IDENTIFIER).value)

        properties: dict[str, Any] = {}
        if self._current_token().type == TokenType.LBRACE:
            properties = self._parse_map()

        self._expect(TokenType.RPAREN)

        node: ASTNode = ASTNode("NODE", variable)
        node.value = PatternElement(variable, "node", labels if labels else None, properties)
        return node

    def _parse_pattern_edge(self) -> ASTNode:
        """Parse an edge in a pattern.

        Returns:
            ASTNode: EDGE node with PatternElement value
        """
        self._expect(TokenType.LBRACKET)

        variable: str | None = None
        if self._current_token().type == TokenType.IDENTIFIER:
            variable = self._current_token().value
            self._advance()

        edge_type: str | None = None
        if self._current_token().type == TokenType.COLON:
            self._advance()
            edge_type = self._expect(TokenType.IDENTIFIER).value

        properties: dict[str, Any] = {}
        if self._current_token().type == TokenType.LBRACE:
            properties = self._parse_map()

        self._expect(TokenType.RBRACKET)

        node: ASTNode = ASTNode("EDGE", variable)
        node.value = PatternElement(variable, "edge", {edge_type} if edge_type else None, properties)
        return node

    def _parse_where(self) -> ASTNode:
        """Parse WHERE clause.

        Returns:
            ASTNode: WHERE node with expression value
        """
        self._expect(TokenType.WHERE)
        node: ASTNode = ASTNode("WHERE")
        expr: ASTNode = self._parse_expression()
        node.value = expr
        return node

    def _parse_expression(self) -> ASTNode:
        """Parse a WHERE expression.

        Returns:
            ASTNode: Expression AST node
        """
        return self._parse_or_expression()

    def _parse_or_expression(self) -> ASTNode:
        """Parse OR expression.

        Returns:
            ASTNode: OR node or left expression
        """
        left: ASTNode = self._parse_and_expression()

        while self._current_token().type == TokenType.OR:
            self._advance()
            right: ASTNode = self._parse_and_expression()
            or_node: ASTNode = ASTNode("OR")
            or_node.add_child(left)
            or_node.add_child(right)
            left = or_node

        return left

    def _parse_and_expression(self) -> ASTNode:
        """Parse AND expression.

        Returns:
            ASTNode: AND node or left expression
        """
        left: ASTNode = self._parse_not_expression()

        while self._current_token().type == TokenType.AND:
            self._advance()
            right: ASTNode = self._parse_not_expression()
            and_node: ASTNode = ASTNode("AND")
            and_node.add_child(left)
            and_node.add_child(right)
            left = and_node

        return left

    def _parse_not_expression(self) -> ASTNode:
        """Parse NOT expression.

        Returns:
            ASTNode: NOT node or comparison expression
        """
        if self._current_token().type == TokenType.NOT:
            self._advance()
            expr: ASTNode = self._parse_not_expression()
            not_node: ASTNode = ASTNode("NOT")
            not_node.add_child(expr)
            return not_node

        return self._parse_comparison()

    def _parse_comparison(self) -> ASTNode:
        """Parse comparison expression.

        Returns:
            ASTNode: COMPARISON node or additive expression
        """
        left: ASTNode = self._parse_additive()

        op_token: Token = self._current_token()
        if op_token.type in (
            TokenType.EQUALS,
            TokenType.NEQ,
            TokenType.LT,
            TokenType.GT,
            TokenType.LTE,
            TokenType.GTE,
        ):
            op: str = op_token.value
            self._advance()
            right: ASTNode = self._parse_additive()
            comp_node: ASTNode = ASTNode("COMPARISON", op)
            comp_node.add_child(left)
            comp_node.add_child(right)
            return comp_node

        return left

    def _parse_additive(self) -> ASTNode:
        """Parse additive expression.

        Returns:
            ASTNode: ADDITIVE node or multiplicative expression
        """
        left: ASTNode = self._parse_multiplicative()

        while self._current_token().type in (TokenType.PLUS, TokenType.MINUS):
            op: str = self._current_token().value
            self._advance()
            right: ASTNode = self._parse_multiplicative()
            add_node: ASTNode = ASTNode("ADDITIVE", op)
            add_node.add_child(left)
            add_node.add_child(right)
            left = add_node

        return left

    def _parse_multiplicative(self) -> ASTNode:
        """Parse multiplicative expression.

        Returns:
            ASTNode: MULTIPLICATIVE node or primary expression
        """
        left: ASTNode = self._parse_primary()

        while self._current_token().type in (TokenType.STAR, TokenType.SLASH):
            op: str = self._current_token().value
            self._advance()
            right: ASTNode = self._parse_primary()
            mult_node: ASTNode = ASTNode("MULTIPLICATIVE", op)
            mult_node.add_child(left)
            mult_node.add_child(right)
            left = mult_node

        return left

    def _parse_primary(self) -> ASTNode:
        """Parse primary expression.

        Returns:
            ASTNode: LITERAL, VARIABLE, PROPERTY, or parenthesized expression

        Raises:
            QuerySyntaxError: If primary expression is invalid
        """
        token: Token = self._current_token()

        if token.type == TokenType.IDENTIFIER:
            var_name: str = token.value
            self._advance()

            # Check for property access
            if self._current_token().type == TokenType.DOT:
                self._advance()
                prop_name: str = self._expect(TokenType.IDENTIFIER).value
                node: ASTNode = ASTNode("PROPERTY", f"{var_name}.{prop_name}")
                return node
            else:
                return ASTNode("VARIABLE", var_name)

        elif token.type == TokenType.STRING or token.type in (TokenType.INTEGER, TokenType.FLOAT):
            self._advance()
            return ASTNode("LITERAL", token.value)

        elif token.type == TokenType.TRUE:
            self._advance()
            return ASTNode("LITERAL", True)

        elif token.type == TokenType.FALSE:
            self._advance()
            return ASTNode("LITERAL", False)

        elif token.type == TokenType.NULL:
            self._advance()
            return ASTNode("LITERAL", None)

        elif token.type == TokenType.LPAREN:
            self._advance()
            expr: ASTNode = self._parse_expression()
            self._expect(TokenType.RPAREN)
            return expr

        else:
            raise QuerySyntaxError(f"Unexpected token: {token.type.name}", token.position, token.value)

    def _parse_return(self) -> ASTNode:
        """Parse RETURN clause.

        Returns:
            ASTNode: RETURN node with expressions and optional DISTINCT flag
        """
        self._expect(TokenType.RETURN)
        node: ASTNode = ASTNode("RETURN")

        if self._current_token().type == TokenType.DISTINCT:
            self._advance()
            node.value = {"distinct": True}

        # Parse return expressions
        return_exprs: list[tuple[str, str | None]] = []

        while True:
            expr: ASTNode = self._parse_additive()
            alias: str | None = None

            if self._current_token().type == TokenType.AS:
                self._advance()
                alias = self._expect(TokenType.IDENTIFIER).value

            return_exprs.append((self._ast_to_string(expr), alias))

            if self._current_token().type != TokenType.COMMA:
                break
            self._advance()

        if node.value is None:
            node.value = {}
        node.value["expressions"] = return_exprs

        return node

    def _parse_create(self) -> ASTNode:
        """Parse CREATE clause.

        Returns:
            ASTNode: CREATE node with pattern children
        """
        self._expect(TokenType.CREATE)
        node: ASTNode = ASTNode("CREATE")

        patterns: list[ASTNode] = self._parse_pattern()
        for pattern in patterns:
            node.add_child(pattern)

        return node

    def _parse_delete(self) -> ASTNode:
        """Parse DELETE clause.

        Returns:
            ASTNode: DELETE node with variable list
        """
        self._expect(TokenType.DELETE)
        node: ASTNode = ASTNode("DELETE")

        while True:
            var: str = self._expect(TokenType.IDENTIFIER).value
            node.value = (node.value or []) + [var]

            if self._current_token().type != TokenType.COMMA:
                break
            self._advance()

        return node

    def _parse_set(self) -> ASTNode:
        """Parse SET clause.

        Returns:
            ASTNode: SET node with assignments dictionary
        """
        self._expect(TokenType.SET)
        node: ASTNode = ASTNode("SET")

        assignments: dict[str, Any] = {}

        while True:
            var_or_prop: str = self._expect(TokenType.IDENTIFIER).value

            if self._current_token().type == TokenType.DOT:
                self._advance()
                prop: str = self._expect(TokenType.IDENTIFIER).value
                var_or_prop = f"{var_or_prop}.{prop}"

            self._expect(TokenType.EQUALS)
            value: ASTNode = self._parse_primary()

            assignments[var_or_prop] = self._ast_to_string(value)

            if self._current_token().type != TokenType.COMMA:
                break
            self._advance()

        node.value = assignments
        return node

    def _parse_order_by(self) -> ASTNode:
        """Parse ORDER BY clause.

        Returns:
            ASTNode: ORDER_BY node with order specifications
        """
        self._expect(TokenType.ORDER)
        self._expect(TokenType.BY)
        node: ASTNode = ASTNode("ORDER_BY")

        order_specs: list[tuple[str, str]] = []

        while True:
            expr_str: str = self._expect(TokenType.IDENTIFIER).value
            direction: str = "ASC"

            if self._current_token().type in (TokenType.ASC, TokenType.DESC):
                direction = self._current_token().value
                self._advance()

            order_specs.append((expr_str, direction))

            if self._current_token().type != TokenType.COMMA:
                break
            self._advance()

        node.value = order_specs
        return node

    def _parse_limit(self) -> ASTNode:
        """Parse LIMIT clause.

        Returns:
            ASTNode: LIMIT node with limit value
        """
        self._expect(TokenType.LIMIT)
        limit_val: int = self._expect(TokenType.INTEGER).value
        node: ASTNode = ASTNode("LIMIT", limit_val)
        return node

    def _parse_skip(self) -> ASTNode:
        """Parse SKIP clause.

        Returns:
            ASTNode: SKIP node with skip value
        """
        self._expect(TokenType.SKIP)
        skip_val: int = self._expect(TokenType.INTEGER).value
        node: ASTNode = ASTNode("SKIP", skip_val)
        return node

    def _parse_map(self) -> dict[str, Any]:
        """Parse a map/dictionary literal.

        Returns:
            Dict[str, Any]: Dictionary of key-value pairs

        Raises:
            QuerySyntaxError: If map syntax is invalid
        """
        self._expect(TokenType.LBRACE)
        result: dict[str, Any] = {}

        while self._current_token().type != TokenType.RBRACE:
            key: str = self._expect(TokenType.IDENTIFIER).value
            self._expect(TokenType.COLON)
            value_node: ASTNode = self._parse_primary()
            result[key] = self._ast_to_string(value_node)

            if self._current_token().type == TokenType.COMMA:
                self._advance()
            elif self._current_token().type != TokenType.RBRACE:
                raise QuerySyntaxError(
                    "Expected comma or }",
                    self._current_token().position,
                )

        self._expect(TokenType.RBRACE)
        return result

    @staticmethod
    def _ast_to_string(node: ASTNode) -> str:
        """Convert AST node to string for evaluation.

        Args:
            node: The AST node to convert

        Returns:
            str: String representation of the node
        """
        if node.type == "LITERAL":
            return repr(node.value)
        elif node.type == "VARIABLE" or node.type == "PROPERTY":
            return node.value
        elif node.type in ("ADDITIVE", "MULTIPLICATIVE", "COMPARISON"):
            left: str = Parser._ast_to_string(node.children[0])
            right: str = Parser._ast_to_string(node.children[1])
            return f"({left} {node.value} {right})"
        else:
            return str(node.value)


def parse_query(query: str) -> ASTNode:
    """Parse a Cypher query string.

    Args:
        query: Query string to parse

    Returns:
        ASTNode: Root AST node

    Raises:
        QuerySyntaxError: If parsing fails
    """
    from thomas.marketplace.graphdb.query_parser import Lexer

    lexer: Lexer = Lexer(query)
    tokens: list[Token] = lexer.tokenize()
    parser: Parser = Parser(tokens)
    return parser.parse()
