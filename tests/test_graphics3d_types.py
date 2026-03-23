from __future__ import annotations

from thomas.marketplace.graphics3d._types import Mat3


def test_mat3_transpose_swaps_rows_and_columns() -> None:
    matrix = Mat3(
        [
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
            [7.0, 8.0, 9.0],
        ]
    )

    transposed = matrix.transpose()

    assert transposed == Mat3(
        [
            [1.0, 4.0, 7.0],
            [2.0, 5.0, 8.0],
            [3.0, 6.0, 9.0],
        ]
    )


def test_mat3_transpose_identity_is_stable() -> None:
    identity = Mat3.identity()
    assert identity.transpose() == identity
