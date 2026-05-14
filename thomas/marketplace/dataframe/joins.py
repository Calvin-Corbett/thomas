"""Join/merge operations for DataFrames."""

from collections import defaultdict
from typing import Any

try:
    from ._exceptions import DataFrameError, MergeError, ShapeError
    from ._types import JoinType
    from .frame import DataFrame
except ImportError:
    from _exceptions import MergeError, ShapeError
    from _types import JoinType
    from frame import DataFrame


class JoinOperation:
    """Join/merge operations between DataFrames."""

    @staticmethod
    def join(
        left: DataFrame,
        right: DataFrame,
        on: str | list[str] | dict[str, str],
        how: str | JoinType = "inner",
        algorithm: str = "hash",
    ) -> DataFrame:
        """Join two DataFrames.

        Args:
            left: Left DataFrame
            right: Right DataFrame
            on: Column(s) to join on. Can be:
                - str: single column (same name in both)
                - list: multiple columns
                - dict: {left_col: right_col} mapping
            how: Join type ('inner', 'left', 'right', 'outer')
            algorithm: 'hash' or 'sort'

        Returns:
            Joined DataFrame
        """
        if isinstance(how, str):
            if how == "inner":
                how = JoinType.INNER
            elif how == "left":
                how = JoinType.LEFT
            elif how == "right":
                how = JoinType.RIGHT
            elif how == "outer":
                how = JoinType.OUTER
            else:
                raise ValueError(f"Unknown join type: {how}")

        if isinstance(on, str):
            on_mapping = {on: on}
        elif isinstance(on, list):
            on_mapping = {col: col for col in on}
        elif isinstance(on, dict):
            on_mapping = on
        else:
            raise TypeError(f"Invalid on type: {type(on)}")

        # Validate columns
        for left_col, right_col in on_mapping.items():
            if left_col not in left.columns:
                raise MergeError(f"Left column {left_col} not found")
            if right_col not in right.columns:
                raise MergeError(f"Right column {right_col} not found")

        if algorithm == "hash":
            return JoinOperation._hash_join(left, right, on_mapping, how)
        elif algorithm == "sort":
            return JoinOperation._sort_merge_join(left, right, on_mapping, how)
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")

    @staticmethod
    def _hash_join(left: DataFrame, right: DataFrame, on_mapping: dict[str, str], how: JoinType) -> DataFrame:
        """Hash join algorithm."""
        # Build hash table from right
        hash_table: dict[Any, list[int]] = defaultdict(list)
        for idx in range(len(right._index)):
            if len(on_mapping) == 1:
                right_col = list(on_mapping.values())[0]
                key = right[right_col][idx]
            else:
                key = tuple(right[right_col][idx] for right_col in on_mapping.values())
            hash_table[key].append(idx)

        # Probe hash table with left
        result_data: dict[str, list[Any]] = defaultdict(list)
        matched_left = set()
        matched_right = set()

        for left_idx in range(len(left._index)):
            if len(on_mapping) == 1:
                left_col = list(on_mapping.keys())[0]
                key = left[left_col][left_idx]
            else:
                key = tuple(left[left_col][left_idx] for left_col in on_mapping)

            if key in hash_table:
                matched_left.add(left_idx)
                for right_idx in hash_table[key]:
                    matched_right.add(right_idx)
                    JoinOperation._add_joined_row(result_data, left, right, left_idx, right_idx, on_mapping)
            else:
                if how in (JoinType.LEFT, JoinType.OUTER):
                    JoinOperation._add_left_row(result_data, left, right, left_idx, on_mapping)

        # Add unmatched right rows for OUTER join
        if how == JoinType.OUTER or how == JoinType.RIGHT:
            for right_idx in range(len(right._index)):
                if right_idx not in matched_right:
                    JoinOperation._add_right_row(result_data, left, right, right_idx, on_mapping)

        return DataFrame(dict(result_data))

    @staticmethod
    def _sort_merge_join(left: DataFrame, right: DataFrame, on_mapping: dict[str, str], how: JoinType) -> DataFrame:
        """Sort-merge join algorithm."""
        # Sort both tables on join keys
        left_col = list(on_mapping.keys())[0]
        right_col = list(on_mapping.values())[0]

        left.copy()
        right.copy()

        # Simple sort
        left_indices = sorted(
            range(len(left._index)), key=lambda i: left[left_col][i] if left[left_col][i] is not None else float("inf")
        )
        right_indices = sorted(
            range(len(right._index)),
            key=lambda i: right[right_col][i] if right[right_col][i] is not None else float("inf"),
        )

        result_data: dict[str, list[Any]] = defaultdict(list)
        l_ptr, r_ptr = 0, 0

        while l_ptr < len(left_indices) and r_ptr < len(right_indices):
            l_idx = left_indices[l_ptr]
            r_idx = right_indices[r_ptr]
            l_val = left[left_col][l_idx]
            r_val = right[right_col][r_idx]

            if l_val == r_val:
                JoinOperation._add_joined_row(result_data, left, right, l_idx, r_idx, on_mapping)
                r_ptr += 1
            elif l_val is None or (r_val is not None and l_val < r_val):
                if how in (JoinType.LEFT, JoinType.OUTER):
                    JoinOperation._add_left_row(result_data, left, right, l_idx, on_mapping)
                l_ptr += 1
            else:
                if how == JoinType.RIGHT:
                    JoinOperation._add_right_row(result_data, left, right, r_idx, on_mapping)
                r_ptr += 1

        return DataFrame(dict(result_data))

    @staticmethod
    def _add_joined_row(
        result_data: dict[str, list[Any]],
        left: DataFrame,
        right: DataFrame,
        left_idx: int,
        right_idx: int,
        on_mapping: dict[str, str],
    ) -> None:
        """Add a matched row to result."""
        for col_name in left.columns:
            if col_name not in result_data:
                result_data[col_name] = []
            result_data[col_name].append(left[col_name][left_idx])

        for col_name in right.columns:
            if col_name not in on_mapping.values():
                if col_name not in result_data:
                    result_data[col_name] = []
                result_data[col_name].append(right[col_name][right_idx])

    @staticmethod
    def _add_left_row(
        result_data: dict[str, list[Any]], left: DataFrame, right: DataFrame, left_idx: int, on_mapping: dict[str, str]
    ) -> None:
        """Add unmatched left row."""
        for col_name in left.columns:
            if col_name not in result_data:
                result_data[col_name] = []
            result_data[col_name].append(left[col_name][left_idx])

        for col_name in right.columns:
            if col_name not in on_mapping.values():
                if col_name not in result_data:
                    result_data[col_name] = []
                result_data[col_name].append(None)

    @staticmethod
    def _add_right_row(
        result_data: dict[str, list[Any]], left: DataFrame, right: DataFrame, right_idx: int, on_mapping: dict[str, str]
    ) -> None:
        """Add unmatched right row."""
        for col_name in left.columns:
            if col_name not in on_mapping:
                if col_name not in result_data:
                    result_data[col_name] = []
                result_data[col_name].append(None)

        for col_name in right.columns:
            if col_name not in result_data:
                result_data[col_name] = []
            result_data[col_name].append(right[col_name][right_idx])

    @staticmethod
    def concat(dfs: list[DataFrame], axis: int = 0, ignore_index: bool = False) -> DataFrame:
        """Concatenate DataFrames.

        Args:
            dfs: List of DataFrames
            axis: 0 for rows, 1 for columns
            ignore_index: If True, don't preserve indices

        Returns:
            Concatenated DataFrame
        """
        if not dfs:
            return DataFrame()

        if axis == 0:
            # Vertical concatenation
            result_data: dict[str, list[Any]] = defaultdict(list)
            result_index = []

            for df in dfs:
                for col_name in df.columns:
                    if col_name not in result_data:
                        result_data[col_name] = []
                    for i in range(len(df._index)):
                        result_data[col_name].append(df[col_name][i])

                if ignore_index:
                    result_index.extend(range(len(df._index)))
                else:
                    result_index.extend(df._index)

            return DataFrame(dict(result_data), index=result_index)

        elif axis == 1:
            # Horizontal concatenation
            if len(dfs[0]._index) != sum(len(df._index) for df in dfs[1:]) // (len(dfs) - 1):
                raise ShapeError((len(dfs[0]._index),), (len(dfs[1]._index),))

            result_data = {}
            for df in dfs:
                for col_name in df.columns:
                    new_col_name = col_name
                    counter = 1
                    while new_col_name in result_data:
                        new_col_name = f"{col_name}_{counter}"
                        counter += 1
                    result_data[new_col_name] = [df[col_name][i] for i in range(len(df._index))]

            return DataFrame(result_data, index=dfs[0]._index)
        else:
            raise ValueError(f"Invalid axis: {axis}")

    @staticmethod
    def cross_join(left: DataFrame, right: DataFrame) -> DataFrame:
        """Cartesian product of two DataFrames."""
        result_data: dict[str, list[Any]] = {}

        for col_name in left.columns:
            result_data[col_name] = []

        for col_name in right.columns:
            result_data[col_name] = []

        for left_idx in range(len(left._index)):
            for right_idx in range(len(right._index)):
                for col_name in left.columns:
                    result_data[col_name].append(left[col_name][left_idx])
                for col_name in right.columns:
                    result_data[col_name].append(right[col_name][right_idx])

        return DataFrame(result_data)
