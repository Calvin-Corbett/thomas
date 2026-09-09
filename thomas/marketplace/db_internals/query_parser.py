"""
SQL query parser for tokenization and parsing.

This module implements:
- SQL tokenization (lexical analysis)
- Parsing SELECT (columns, FROM, WHERE, JOIN, GROUP BY, HAVING, ORDER BY, LIMIT)
- INSERT, UPDATE, DELETE statements
- CREATE TABLE, DROP TABLE, CREATE INDEX statements
- Expression parsing (arithmetic, comparison, logical, BETWEEN, IN, LIKE, IS NULL)
- Operator precedence handling
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from ._exceptions import ParseException, SyntaxException
from ._types import BinaryOpNode, ColumnNode, ExpressionNode, LiteralNode, UnaryOpNode


class TokenType(Enum):
    """Types of SQL tokens."""

    EOF = auto()
    KEYWORD = auto()
    IDENTIFIER = auto()
    NUMBER = auto()
    STRING = auto()
    OPERATOR = auto()
    LPAREN = auto()
    RPAREN = auto()
    COMMA = auto()
    SEMICOLON = auto()
    DOT = auto()
    STAR = auto()


@dataclass
class Token:
    """A lexical token."""

    type: TokenType
    value: str
    line: int = 0
    column: int = 0

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r})"


class Tokenizer:
    """Tokenizes SQL statements."""

    KEYWORDS = {
        "SELECT",
        "FROM",
        "WHERE",
        "JOIN",
        "INNER",
        "LEFT",
        "RIGHT",
        "OUTER",
        "ON",
        "GROUP",
        "BY",
        "HAVING",
        "ORDER",
        "ASC",
        "DESC",
        "LIMIT",
        "OFFSET",
        "INSERT",
        "INTO",
        "VALUES",
        "UPDATE",
        "SET",
        "DELETE",
        "CREATE",
        "TABLE",
        "DROP",
        "INDEX",
        "PRIMARY",
        "KEY",
        "UNIQUE",
        "NOT",
        "NULL",
        "DEFAULT",
        "CHECK",
        "FOREIGN",
        "REFERENCES",
        "AND",
        "OR",
        "AS",
        "CASE",
        "WHEN",
        "THEN",
        "ELSE",
        "END",
        "BETWEEN",
        "IN",
        "LIKE",
        "IS",
        "INT",
        "FLOAT",
        "VARCHAR",
        "BOOL",
        "DATE",
        "TIMESTAMP",
        "BLOB",
        "COUNT",
        "SUM",
        "AVG",
        "MIN",
        "MAX",
        "DISTINCT",
        "ALL",
        "CONSTRAINT",
        "ALTER",
        "ADD",
        "MODIFY",
        "RENAME",
    }

    OPERATORS = {
        "=",
        "<",
        ">",
        "<=",
        ">=",
        "!=",
        "<>",
        "+",
        "-",
        "*",
        "/",
        "%",
        "||",
        "&&",
    }

    def __init__(self, sql: str) -> None:
        """Initialize tokenizer with SQL string."""
        self.sql = sql
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        """Tokenize the SQL statement."""
        while self.pos < len(self.sql):
            self._skip_whitespace_and_comments()
            if self.pos >= len(self.sql):
                break

            char = self.sql[self.pos]

            if char == "(":
                self.tokens.append(Token(TokenType.LPAREN, "(", self.line, self.column))
                self._advance()
            elif char == ")":
                self.tokens.append(Token(TokenType.RPAREN, ")", self.line, self.column))
                self._advance()
            elif char == ",":
                self.tokens.append(Token(TokenType.COMMA, ",", self.line, self.column))
                self._advance()
            elif char == ";":
                self.tokens.append(Token(TokenType.SEMICOLON, ";", self.line, self.column))
                self._advance()
            elif char == ".":
                self.tokens.append(Token(TokenType.DOT, ".", self.line, self.column))
                self._advance()
            elif char == "*":
                self.tokens.append(Token(TokenType.STAR, "*", self.line, self.column))
                self._advance()
            elif char == "'":
                self._tokenize_string()
            elif char == '"':
                self._tokenize_identifier_quoted()
            elif char.isdigit():
                self._tokenize_number()
            elif char.isalpha() or char == "_":
                self._tokenize_identifier_or_keyword()
            elif char in self.OPERATORS or (
                self.pos < len(self.sql) - 1 and self.sql[self.pos : self.pos + 2] in self.OPERATORS
            ):
                self._tokenize_operator()
            else:
                self.pos += 1

        self.tokens.append(Token(TokenType.EOF, "", self.line, self.column))
        return self.tokens

    def _skip_whitespace_and_comments(self) -> None:
        """Skip whitespace and comments."""
        while self.pos < len(self.sql):
            if self.sql[self.pos].isspace():
                if self.sql[self.pos] == "\n":
                    self.line += 1
                    self.column = 1
                else:
                    self.column += 1
                self.pos += 1
            elif self.pos < len(self.sql) - 1 and self.sql[self.pos : self.pos + 2] == "--":
                # Skip line comment
                while self.pos < len(self.sql) and self.sql[self.pos] != "\n":
                    self.pos += 1
            elif self.pos < len(self.sql) - 1 and self.sql[self.pos : self.pos + 2] == "/*":
                # Skip block comment
                self.pos += 2
                while self.pos < len(self.sql) - 1:
                    if self.sql[self.pos : self.pos + 2] == "*/":
                        self.pos += 2
                        break
                    if self.sql[self.pos] == "\n":
                        self.line += 1
                        self.column = 1
                    self.pos += 1
            else:
                break

    def _tokenize_string(self) -> None:
        """Tokenize a string literal."""
        start_col = self.column
        self.pos += 1  # Skip opening quote
        self.column += 1
        value = ""

        while self.pos < len(self.sql):
            char = self.sql[self.pos]

            if char == "'":
                if self.pos + 1 < len(self.sql) and self.sql[self.pos + 1] == "'":
                    # Escaped quote
                    value += "'"
                    self.pos += 2
                    self.column += 2
                else:
                    # End of string
                    self.pos += 1
                    self.column += 1
                    break
            elif char == "\n":
                self.line += 1
                self.column = 1
                value += char
                self.pos += 1
            else:
                value += char
                self.pos += 1
                self.column += 1

        self.tokens.append(Token(TokenType.STRING, value, self.line, start_col))

    def _tokenize_identifier_quoted(self) -> None:
        """Tokenize a quoted identifier."""
        start_col = self.column
        self.pos += 1  # Skip opening quote
        self.column += 1
        value = ""

        while self.pos < len(self.sql) and self.sql[self.pos] != '"':
            value += self.sql[self.pos]
            if self.sql[self.pos] == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1
            self.pos += 1

        if self.pos < len(self.sql):
            self.pos += 1  # Skip closing quote
            self.column += 1

        self.tokens.append(Token(TokenType.IDENTIFIER, value, self.line, start_col))

    def _tokenize_number(self) -> None:
        """Tokenize a number."""
        start_col = self.column
        value = ""

        while self.pos < len(self.sql) and (self.sql[self.pos].isdigit() or self.sql[self.pos] == "."):
            value += self.sql[self.pos]
            self.pos += 1
            self.column += 1

        self.tokens.append(Token(TokenType.NUMBER, value, self.line, start_col))

    def _tokenize_identifier_or_keyword(self) -> None:
        """Tokenize an identifier or keyword."""
        start_col = self.column
        value = ""

        while self.pos < len(self.sql) and (self.sql[self.pos].isalnum() or self.sql[self.pos] == "_"):
            value += self.sql[self.pos]
            self.pos += 1
            self.column += 1

        upper_value = value.upper()
        if upper_value in self.KEYWORDS:
            self.tokens.append(Token(TokenType.KEYWORD, upper_value, self.line, start_col))
        else:
            self.tokens.append(Token(TokenType.IDENTIFIER, value, self.line, start_col))

    def _tokenize_operator(self) -> None:
        """Tokenize an operator."""
        start_col = self.column

        # Try two-character operators first
        if self.pos < len(self.sql) - 1:
            two_char = self.sql[self.pos : self.pos + 2]
            if two_char in self.OPERATORS:
                self.tokens.append(Token(TokenType.OPERATOR, two_char, self.line, start_col))
                self.pos += 2
                self.column += 2
                return

        # Single character operator
        if self.sql[self.pos] in self.OPERATORS:
            self.tokens.append(Token(TokenType.OPERATOR, self.sql[self.pos], self.line, start_col))
            self.pos += 1
            self.column += 1

    def _advance(self) -> None:
        """Advance position and track line/column."""
        if self.pos < len(self.sql) and self.sql[self.pos] == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        self.pos += 1


class Parser:
    """Parses SQL statements into AST-like structures."""

    FUNCTION_KEYWORDS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}

    def __init__(self, tokens: list[Token]) -> None:
        """Initialize parser with tokens."""
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> dict[str, Any]:
        """Parse the SQL statement and return AST."""
        if not self.tokens:
            raise ParseException("No tokens to parse")

        # Peek at first keyword to determine statement type
        token = self._current()
        if token.type == TokenType.KEYWORD:
            if token.value == "SELECT":
                return self._parse_select()
            elif token.value == "INSERT":
                return self._parse_insert()
            elif token.value == "UPDATE":
                return self._parse_update()
            elif token.value == "DELETE":
                return self._parse_delete()
            elif token.value == "CREATE":
                return self._parse_create()
            elif token.value == "DROP":
                return self._parse_drop()

        raise SyntaxException(f"Unexpected token: {token}")

    def _parse_select(self) -> dict[str, Any]:
        """Parse SELECT statement."""
        self._expect_keyword("SELECT")

        distinct = False
        if self._check_keyword("DISTINCT"):
            self._advance()
            distinct = True

        columns = self._parse_select_list()
        from_clause = None
        where_clause = None
        group_by_clause = None
        having_clause = None
        order_by_clause = None
        limit_clause = None
        offset_clause = None

        if self._check_keyword("FROM"):
            self._advance()
            from_clause = self._parse_from_clause()

        if self._check_keyword("WHERE"):
            self._advance()
            where_clause = self._parse_expression()

        if self._check_keyword("GROUP"):
            self._advance()
            self._expect_keyword("BY")
            group_by_clause = self._parse_expression_list()

        if self._check_keyword("HAVING"):
            self._advance()
            having_clause = self._parse_expression()

        if self._check_keyword("ORDER"):
            self._advance()
            self._expect_keyword("BY")
            order_by_clause = self._parse_order_by_list()

        if self._check_keyword("LIMIT"):
            self._advance()
            limit_clause = int(self._expect(TokenType.NUMBER).value)

        if self._check_keyword("OFFSET"):
            self._advance()
            offset_clause = int(self._expect(TokenType.NUMBER).value)

        return {
            "type": "SELECT",
            "distinct": distinct,
            "columns": columns,
            "from": from_clause,
            "where": where_clause,
            "group_by": group_by_clause,
            "having": having_clause,
            "order_by": order_by_clause,
            "limit": limit_clause,
            "offset": offset_clause,
        }

    def _parse_select_list(self) -> list[dict[str, Any]]:
        """Parse column list in SELECT."""
        columns = []

        if self._check(TokenType.STAR):
            self._advance()
            columns.append({"expr": "*", "alias": None})
        else:
            columns.append(
                {
                    "expr": self._parse_expression(),
                    "alias": self._parse_alias(),
                }
            )

            while self._check(TokenType.COMMA):
                self._advance()
                columns.append(
                    {
                        "expr": self._parse_expression(),
                        "alias": self._parse_alias(),
                    }
                )

        return columns

    def _parse_from_clause(self) -> dict[str, Any]:
        """Parse FROM clause."""
        table = self._expect(TokenType.IDENTIFIER).value
        alias = self._parse_alias()

        joins = []
        while (
            self._check_keyword("JOIN")
            or self._check_keyword("INNER")
            or self._check_keyword("LEFT")
            or self._check_keyword("RIGHT")
        ):
            join_type = "INNER"
            if self._check_keyword("LEFT"):
                self._advance()
                join_type = "LEFT"
                if self._check_keyword("OUTER"):
                    self._advance()
            elif self._check_keyword("RIGHT"):
                self._advance()
                join_type = "RIGHT"
                if self._check_keyword("OUTER"):
                    self._advance()

            self._expect_keyword("JOIN")
            right_table = self._expect(TokenType.IDENTIFIER).value
            right_alias = self._parse_alias()

            self._expect_keyword("ON")
            on_condition = self._parse_expression()

            joins.append(
                {
                    "type": join_type,
                    "table": right_table,
                    "alias": right_alias,
                    "condition": on_condition,
                }
            )

        return {
            "table": table,
            "alias": alias,
            "joins": joins,
        }

    def _parse_expression(self) -> ExpressionNode:
        """Parse an expression with operator precedence."""
        return self._parse_or_expr()

    def _parse_or_expr(self) -> ExpressionNode:
        """Parse OR expression."""
        left = self._parse_and_expr()

        while self._check_keyword("OR"):
            self._advance()
            right = self._parse_and_expr()
            left = BinaryOpNode(operator="OR", left=left, right=right)

        return left

    def _parse_and_expr(self) -> ExpressionNode:
        """Parse AND expression."""
        left = self._parse_comparison_expr()

        while self._check_keyword("AND"):
            self._advance()
            right = self._parse_comparison_expr()
            left = BinaryOpNode(operator="AND", left=left, right=right)

        return left

    def _parse_comparison_expr(self) -> ExpressionNode:
        """Parse comparison expression."""
        left = self._parse_additive_expr()

        if self._check(TokenType.OPERATOR):
            op = self._current().value
            if op in ["=", "<", ">", "<=", ">=", "!=", "<>"]:
                self._advance()
                right = self._parse_additive_expr()
                return BinaryOpNode(operator=op, left=left, right=right)

        if self._check_keyword("BETWEEN"):
            self._advance()
            lower = self._parse_additive_expr()
            self._expect_keyword("AND")
            upper = self._parse_additive_expr()
            return BinaryOpNode(
                operator="BETWEEN", left=left, right=BinaryOpNode(operator=",", left=lower, right=upper)
            )

        if self._check_keyword("IN"):
            self._advance()
            self._expect(TokenType.LPAREN)
            values = self._parse_expression_list()
            self._expect(TokenType.RPAREN)
            return BinaryOpNode(operator="IN", left=left, right=LiteralNode(value=values))

        if self._check_keyword("LIKE"):
            self._advance()
            pattern = self._parse_additive_expr()
            return BinaryOpNode(operator="LIKE", left=left, right=pattern)

        if self._check_keyword("IS"):
            self._advance()
            is_not = False
            if self._check_keyword("NOT"):
                self._advance()
                is_not = True
            self._expect_keyword("NULL")
            op = "IS NOT NULL" if is_not else "IS NULL"
            return UnaryOpNode(operator=op, operand=left)

        return left

    def _parse_additive_expr(self) -> ExpressionNode:
        """Parse addition/subtraction expression."""
        left = self._parse_multiplicative_expr()

        while self._check(TokenType.OPERATOR) and self._current().value in ["+", "-"]:
            op = self._current().value
            self._advance()
            right = self._parse_multiplicative_expr()
            left = BinaryOpNode(operator=op, left=left, right=right)

        return left

    def _parse_multiplicative_expr(self) -> ExpressionNode:
        """Parse multiplication/division expression."""
        left = self._parse_unary_expr()

        while self._check(TokenType.OPERATOR) and self._current().value in ["*", "/", "%"]:
            op = self._current().value
            self._advance()
            right = self._parse_unary_expr()
            left = BinaryOpNode(operator=op, left=left, right=right)

        return left

    def _parse_unary_expr(self) -> ExpressionNode:
        """Parse unary expression."""
        if self._check_keyword("NOT"):
            self._advance()
            operand = self._parse_unary_expr()
            return UnaryOpNode(operator="NOT", operand=operand)

        if self._check(TokenType.OPERATOR) and self._current().value == "-":
            self._advance()
            operand = self._parse_unary_expr()
            return UnaryOpNode(operator="-", operand=operand)

        return self._parse_primary_expr()

    def _parse_primary_expr(self) -> ExpressionNode:
        """Parse primary expression (literal, column, function, parenthesized)."""
        if self._check(TokenType.NUMBER):
            value = self._current().value
            self._advance()
            try:
                if "." in value:
                    return LiteralNode(value=float(value))
                else:
                    return LiteralNode(value=int(value))
            except ValueError:
                return LiteralNode(value=value)

        if self._check(TokenType.STRING):
            value = self._current().value
            self._advance()
            return LiteralNode(value=value)

        if self._check_keyword("NULL"):
            self._advance()
            return LiteralNode(value=None)

        if self._check(TokenType.LPAREN):
            self._advance()
            expr = self._parse_expression()
            self._expect(TokenType.RPAREN)
            return expr

        if self._check(TokenType.STAR):
            self._advance()
            return LiteralNode(value="*")

        if self._check(TokenType.IDENTIFIER) or (
            self._check(TokenType.KEYWORD) and self._current().value in self.FUNCTION_KEYWORDS
        ):
            name = self._current().value
            self._advance()

            # Check for function call
            if self._check(TokenType.LPAREN):
                self._advance()
                args = []
                if self._check(TokenType.STAR):
                    self._advance()
                    args = [LiteralNode(value="*")]
                elif not self._check(TokenType.RPAREN):
                    args = self._parse_expression_list()
                self._expect(TokenType.RPAREN)
                from ._types import FunctionCallNode

                return FunctionCallNode(function_name=name, arguments=args)

            return ColumnNode(column_name=name)

        raise SyntaxException(f"Unexpected token in expression: {self._current()}")

    def _parse_expression_list(self) -> list[ExpressionNode]:
        """Parse comma-separated expressions."""
        expressions = [self._parse_expression()]

        while self._check(TokenType.COMMA):
            self._advance()
            expressions.append(self._parse_expression())

        return expressions

    def _parse_order_by_list(self) -> list[tuple[ExpressionNode, str]]:
        """Parse ORDER BY clause."""
        items = []
        items.append(
            (self._parse_expression(), "ASC" if not self._check_keyword("DESC") else (self._advance() or "DESC"))
        )

        while self._check(TokenType.COMMA):
            self._advance()
            items.append(
                (self._parse_expression(), "ASC" if not self._check_keyword("DESC") else (self._advance() or "DESC"))
            )

        return items

    def _parse_insert(self) -> dict[str, Any]:
        """Parse INSERT statement."""
        self._expect_keyword("INSERT")
        self._expect_keyword("INTO")
        table = self._expect(TokenType.IDENTIFIER).value

        columns = None
        if self._check(TokenType.LPAREN):
            self._advance()
            columns = [self._expect(TokenType.IDENTIFIER).value]
            while self._check(TokenType.COMMA):
                self._advance()
                columns.append(self._expect(TokenType.IDENTIFIER).value)
            self._expect(TokenType.RPAREN)

        self._expect_keyword("VALUES")
        self._expect(TokenType.LPAREN)
        values = self._parse_expression_list()
        self._expect(TokenType.RPAREN)

        return {
            "type": "INSERT",
            "table": table,
            "columns": columns,
            "values": values,
        }

    def _parse_update(self) -> dict[str, Any]:
        """Parse UPDATE statement."""
        self._expect_keyword("UPDATE")
        table = self._expect(TokenType.IDENTIFIER).value
        self._expect_keyword("SET")

        assignments = {}
        col = self._expect(TokenType.IDENTIFIER).value
        self._expect(TokenType.OPERATOR)  # =
        assignments[col] = self._parse_expression()

        while self._check(TokenType.COMMA):
            self._advance()
            col = self._expect(TokenType.IDENTIFIER).value
            self._expect(TokenType.OPERATOR)  # =
            assignments[col] = self._parse_expression()

        where_clause = None
        if self._check_keyword("WHERE"):
            self._advance()
            where_clause = self._parse_expression()

        return {
            "type": "UPDATE",
            "table": table,
            "assignments": assignments,
            "where": where_clause,
        }

    def _parse_delete(self) -> dict[str, Any]:
        """Parse DELETE statement."""
        self._expect_keyword("DELETE")
        self._expect_keyword("FROM")
        table = self._expect(TokenType.IDENTIFIER).value

        where_clause = None
        if self._check_keyword("WHERE"):
            self._advance()
            where_clause = self._parse_expression()

        return {
            "type": "DELETE",
            "table": table,
            "where": where_clause,
        }

    def _parse_create(self) -> dict[str, Any]:
        """Parse CREATE statement."""
        self._expect_keyword("CREATE")

        if self._check_keyword("TABLE"):
            return self._parse_create_table()
        elif self._check_keyword("INDEX"):
            return self._parse_create_index()

        raise SyntaxException("Expected TABLE or INDEX after CREATE")

    def _parse_create_table(self) -> dict[str, Any]:
        """Parse CREATE TABLE statement."""
        self._expect_keyword("TABLE")
        table_name = self._expect(TokenType.IDENTIFIER).value
        self._expect(TokenType.LPAREN)

        columns = []
        columns.append(self._parse_column_def())

        while self._check(TokenType.COMMA):
            self._advance()
            columns.append(self._parse_column_def())

        self._expect(TokenType.RPAREN)

        return {
            "type": "CREATE_TABLE",
            "table_name": table_name,
            "columns": columns,
        }

    def _parse_column_def(self) -> dict[str, Any]:
        """Parse column definition."""
        col_name = self._expect(TokenType.IDENTIFIER).value
        col_type = self._expect(TokenType.KEYWORD).value

        nullable = True
        if self._check_keyword("NOT"):
            self._advance()
            self._expect_keyword("NULL")
            nullable = False

        default = None
        if self._check_keyword("DEFAULT"):
            self._advance()
            default = self._parse_primary_expr()

        return {
            "name": col_name,
            "type": col_type,
            "nullable": nullable,
            "default": default,
        }

    def _parse_create_index(self) -> dict[str, Any]:
        """Parse CREATE INDEX statement."""
        self._expect_keyword("INDEX")
        index_name = self._expect(TokenType.IDENTIFIER).value
        self._expect_keyword("ON")
        table_name = self._expect(TokenType.IDENTIFIER).value

        self._expect(TokenType.LPAREN)
        columns = [self._expect(TokenType.IDENTIFIER).value]
        while self._check(TokenType.COMMA):
            self._advance()
            columns.append(self._expect(TokenType.IDENTIFIER).value)
        self._expect(TokenType.RPAREN)

        return {
            "type": "CREATE_INDEX",
            "index_name": index_name,
            "table_name": table_name,
            "columns": columns,
        }

    def _parse_drop(self) -> dict[str, Any]:
        """Parse DROP statement."""
        self._expect_keyword("DROP")

        if self._check_keyword("TABLE"):
            self._advance()
            table = self._expect(TokenType.IDENTIFIER).value
            return {"type": "DROP_TABLE", "table": table}
        elif self._check_keyword("INDEX"):
            self._advance()
            index = self._expect(TokenType.IDENTIFIER).value
            return {"type": "DROP_INDEX", "index": index}

        raise SyntaxException("Expected TABLE or INDEX after DROP")

    def _parse_alias(self) -> str | None:
        """Parse optional alias."""
        if self._check_keyword("AS"):
            self._advance()
            return self._expect(TokenType.IDENTIFIER).value
        elif self._check(TokenType.IDENTIFIER) and not self._is_keyword_upcoming():
            return self._current().value

        return None

    def _is_keyword_upcoming(self) -> bool:
        """Check if upcoming token is a keyword."""
        return self._current().type == TokenType.KEYWORD

    def _current(self) -> Token:
        """Get current token."""
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return self.tokens[-1]  # EOF

    def _advance(self) -> Token:
        """Move to next token and return current."""
        current = self._current()
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return current

    def _check(self, token_type: TokenType) -> bool:
        """Check if current token matches type."""
        return self._current().type == token_type

    def _check_keyword(self, keyword: str) -> bool:
        """Check if current token is a specific keyword."""
        return self._current().type == TokenType.KEYWORD and self._current().value == keyword.upper()

    def _expect(self, token_type: TokenType) -> Token:
        """Consume token of expected type."""
        if not self._check(token_type):
            raise SyntaxException(f"Expected {token_type}, got {self._current().type}")
        return self._advance()

    def _expect_keyword(self, keyword: str) -> Token:
        """Consume keyword."""
        if not self._check_keyword(keyword):
            raise SyntaxException(f"Expected {keyword}, got {self._current().value}")
        return self._advance()
