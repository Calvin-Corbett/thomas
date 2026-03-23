"""Tests for DSL type system."""

import pytest

from thomas.marketplace.dsl import (
    BinaryOp,
    FunctionType,
    Identifier,
    IfExpr,
    LambdaExpr,
    ListExpr,
    ListType,
    Literal,
    SimpleType,
    TypeInference,
    TypeVariable,
    UnaryOp,
    Unifier,
)


class TestTypeInference:
    """Test type inference."""

    def test_infer_literal_int(self) -> None:
        """Test inferring integer type."""
        inference = TypeInference()
        ast = Literal(42)
        type_ = inference.infer(ast)
        assert isinstance(type_, SimpleType)
        assert type_.name == "int"

    def test_infer_literal_float(self) -> None:
        """Test inferring float type."""
        inference = TypeInference()
        ast = Literal(3.14)
        type_ = inference.infer(ast)
        assert isinstance(type_, SimpleType)
        assert type_.name == "float"

    def test_infer_literal_string(self) -> None:
        """Test inferring string type."""
        inference = TypeInference()
        ast = Literal("hello")
        type_ = inference.infer(ast)
        assert isinstance(type_, SimpleType)
        assert type_.name == "string"

    def test_infer_literal_bool(self) -> None:
        """Test inferring boolean type."""
        inference = TypeInference()
        ast = Literal(True)
        type_ = inference.infer(ast)
        assert isinstance(type_, SimpleType)
        assert type_.name == "bool"

    def test_infer_literal_none(self) -> None:
        """Test inferring none type."""
        inference = TypeInference()
        ast = Literal(None)
        type_ = inference.infer(ast)
        assert isinstance(type_, SimpleType)
        assert type_.name == "none"

    def test_infer_list(self) -> None:
        """Test inferring list type."""
        inference = TypeInference()
        ast = ListExpr([Literal(1), Literal(2)])
        type_ = inference.infer(ast)
        assert isinstance(type_, ListType)
        assert isinstance(type_.element_type, SimpleType)

    def test_infer_empty_list(self) -> None:
        """Test inferring empty list type."""
        inference = TypeInference()
        ast = ListExpr([])
        type_ = inference.infer(ast)
        assert isinstance(type_, ListType)

    def test_infer_lambda(self) -> None:
        """Test inferring lambda type."""
        inference = TypeInference()
        ast = LambdaExpr(["x"], Literal(42))
        type_ = inference.infer(ast)
        assert isinstance(type_, FunctionType)
        assert len(type_.arg_types) == 1

    def test_infer_binary_addition(self) -> None:
        """Test inferring addition type."""
        inference = TypeInference()
        ast = BinaryOp(Literal(1), "+", Literal(2))
        type_ = inference.infer(ast)
        # Should infer as int
        assert isinstance(type_, SimpleType)

    def test_infer_comparison(self) -> None:
        """Test inferring comparison type."""
        inference = TypeInference()
        ast = BinaryOp(Literal(1), "<", Literal(2))
        type_ = inference.infer(ast)
        assert isinstance(type_, SimpleType)
        assert type_.name == "bool"

    def test_infer_unary_not(self) -> None:
        """Test inferring not type."""
        inference = TypeInference()
        ast = UnaryOp("!", Literal(True))
        type_ = inference.infer(ast)
        assert isinstance(type_, SimpleType)
        assert type_.name == "bool"

    def test_infer_identifier(self) -> None:
        """Test inferring identifier type."""
        inference = TypeInference()
        inference.type_env.define("x", SimpleType("int"))
        ast = Identifier("x")
        type_ = inference.infer(ast)
        assert isinstance(type_, SimpleType)
        assert type_.name == "int"

    def test_infer_if_expression(self) -> None:
        """Test inferring if expression type."""
        inference = TypeInference()
        ast = IfExpr(Literal(True), Literal(1), Literal(2))
        type_ = inference.infer(ast)
        assert isinstance(type_, SimpleType)
        assert type_.name == "int"

    def test_fresh_type_variables(self) -> None:
        """Test generating fresh type variables."""
        inference = TypeInference()
        var1 = inference.type_env.fresh_var()
        var2 = inference.type_env.fresh_var()
        assert isinstance(var1, TypeVariable)
        assert isinstance(var2, TypeVariable)
        assert var1.name != var2.name


class TestUnification:
    """Test type unification."""

    def test_unify_same_type(self) -> None:
        """Test unifying same types."""
        unifier = Unifier()
        t1 = SimpleType("int")
        t2 = SimpleType("int")
        # Should not raise
        unifier.unify(t1, t2)

    def test_unify_type_variable(self) -> None:
        """Test unifying type variable."""
        unifier = Unifier()
        var = TypeVariable("a")
        t = SimpleType("int")
        unifier.unify(var, t)
        # After unification, var should map to int
        assert unifier._deref(var) == t

    def test_unify_list_types(self) -> None:
        """Test unifying list types."""
        unifier = Unifier()
        t1 = ListType(SimpleType("int"))
        t2 = ListType(SimpleType("int"))
        unifier.unify(t1, t2)

    def test_unify_function_types(self) -> None:
        """Test unifying function types."""
        unifier = Unifier()
        t1 = FunctionType([SimpleType("int")], SimpleType("string"))
        t2 = FunctionType([SimpleType("int")], SimpleType("string"))
        unifier.unify(t1, t2)

    def test_unify_incompatible_types(self) -> None:
        """Test unifying incompatible types."""
        from thomas.marketplace.dsl import UnificationError

        unifier = Unifier()
        t1 = SimpleType("int")
        t2 = SimpleType("string")
        with pytest.raises(UnificationError):
            unifier.unify(t1, t2)

    def test_unify_occurs_check(self) -> None:
        """Test occurs check prevents infinite types."""
        from thomas.marketplace.dsl import UnificationError

        unifier = Unifier()
        var = TypeVariable("a")
        list_type = ListType(var)
        # var cannot unify with ListType containing var
        with pytest.raises(UnificationError):
            unifier.unify(var, list_type)

    def test_unify_apply_substitution(self) -> None:
        """Test applying substitution after unification."""
        unifier = Unifier()
        var = TypeVariable("a")
        t = SimpleType("int")
        unifier.unify(var, t)

        # Apply substitution to function type with variable
        func_type = FunctionType([var], var)
        applied = unifier.apply(func_type)

        assert applied.arg_types[0] == t
        assert applied.return_type == t

    def test_deref_chain(self) -> None:
        """Test dereferencing through chains."""
        unifier = Unifier()
        var1 = TypeVariable("a")
        var2 = TypeVariable("b")
        t = SimpleType("int")

        unifier.unify(var1, var2)
        unifier.unify(var2, t)

        assert unifier._deref(var1) == t

    def test_unify_different_arity(self) -> None:
        """Test unifying functions with different arity."""
        from thomas.marketplace.dsl import UnificationError

        unifier = Unifier()
        t1 = FunctionType([SimpleType("int"), SimpleType("int")], SimpleType("int"))
        t2 = FunctionType([SimpleType("int")], SimpleType("int"))

        with pytest.raises(UnificationError):
            unifier.unify(t1, t2)

    def test_unify_list_element_types(self) -> None:
        """Test unifying list element types."""
        from thomas.marketplace.dsl import UnificationError

        unifier = Unifier()
        t1 = ListType(SimpleType("int"))
        t2 = ListType(SimpleType("string"))

        with pytest.raises(UnificationError):
            unifier.unify(t1, t2)


class TestTypeSystem:
    """Test type system integration."""

    def test_type_equality(self) -> None:
        """Test type equality."""
        t1 = SimpleType("int")
        t2 = SimpleType("int")
        t3 = SimpleType("string")

        assert t1 == t2
        assert t1 != t3

    def test_type_variable_equality(self) -> None:
        """Test type variable equality."""
        var1 = TypeVariable("a")
        var2 = TypeVariable("a")
        var3 = TypeVariable("b")

        assert var1 == var2
        assert var1 != var3

    def test_list_type_equality(self) -> None:
        """Test list type equality."""
        t1 = ListType(SimpleType("int"))
        t2 = ListType(SimpleType("int"))
        t3 = ListType(SimpleType("string"))

        assert t1 == t2
        assert t1 != t3

    def test_function_type_equality(self) -> None:
        """Test function type equality."""
        t1 = FunctionType([SimpleType("int")], SimpleType("string"))
        t2 = FunctionType([SimpleType("int")], SimpleType("string"))
        t3 = FunctionType([SimpleType("int")], SimpleType("int"))

        assert t1 == t2
        assert t1 != t3

    def test_type_string_representation(self) -> None:
        """Test type string representation."""
        t = SimpleType("int")
        assert str(t) == "int"

        var = TypeVariable("a")
        assert "'a" in str(var)

        list_t = ListType(SimpleType("int"))
        assert "[" in str(list_t) and "]" in str(list_t)

    def test_polymorphic_identity(self) -> None:
        """Test polymorphic identity function."""
        inference = TypeInference()
        ast = LambdaExpr(["x"], Identifier("x"))
        type_ = inference.infer(ast)

        assert isinstance(type_, FunctionType)
        assert len(type_.arg_types) == 1
        assert type_.return_type is not None
